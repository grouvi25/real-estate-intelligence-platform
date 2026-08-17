"""Кладёт дамп базы в Object Storage и убирает просроченные. ТЗ раздел 25.

Запускается внутри образа приложения — там уже есть boto3 и ключи Object
Storage из .env, так что на хосте не нужно ни awscli, ни виртуального окружения.

Вызов:  python deploy/backup_upload.py /backups/reip-20260816.sql.gz
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone

import boto3

PREFIX = "backups/db/"
KEEP_DAYS = 7
# Пустой или обрезанный дамп заливать нельзя: он вытеснит собой рабочую копию,
# и подмену заметят только когда восстанавливаться будет уже нечего.
MIN_BYTES = 10_000


def main() -> int:
    path = sys.argv[1]
    size = os.path.getsize(path)
    if size < MIN_BYTES:
        print(f"дамп подозрительно мал: {size} байт — заливка отменена", file=sys.stderr)
        return 1

    bucket = os.environ["YC_S3_BUCKET"]
    s3 = boto3.client(
        "s3",
        endpoint_url=os.environ.get("YC_S3_ENDPOINT", "https://storage.yandexcloud.net"),
        aws_access_key_id=os.environ["YC_S3_ACCESS_KEY"],
        aws_secret_access_key=os.environ["YC_S3_SECRET_KEY"],
        region_name=os.environ.get("YC_S3_REGION", "ru-central1"),
    )

    key = PREFIX + os.path.basename(path)
    s3.upload_file(path, bucket, key)
    print(f"залито: s3://{bucket}/{key} ({size} байт)")

    cutoff = datetime.now(timezone.utc) - timedelta(days=KEEP_DAYS)
    removed = 0
    pages = s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=PREFIX)
    for page in pages:
        for obj in page.get("Contents", []):
            if obj["LastModified"] < cutoff:
                s3.delete_object(Bucket=bucket, Key=obj["Key"])
                removed += 1
    print(f"удалено просроченных копий: {removed} (храним {KEEP_DAYS} дней)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
