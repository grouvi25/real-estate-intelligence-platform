#!/usr/bin/env bash
# Ежедневный дамп базы в Object Storage. ТЗ раздел 25.
#
# Управляемый PostgreSQL со своими снапшотами обошёлся бы дороже всей остальной
# инфраструктуры, поэтому база живёт в контейнере, а роль снапшотов выполняет
# этот дамп: ежедневно, с хранением 7 дней и включённым версионированием бакета.
#
# Ставится в cron root: 0 3 * * * /opt/reip/deploy/backup-db.sh >> /var/log/reip-backup.log 2>&1
set -euo pipefail

PROJECT_DIR=/opt/reip
BACKUP_DIR=$PROJECT_DIR/backups
STAMP=$(date +%Y%m%d-%H%M)
FILE=$BACKUP_DIR/reip-$STAMP.sql.gz

mkdir -p "$BACKUP_DIR"
cd "$PROJECT_DIR"

echo "[$(date --iso-8601=seconds)] дамп базы"
# --clean --if-exists: восстановление накатывается на непустую базу без ручной чистки.
docker compose exec -T db pg_dump -U re_app --clean --if-exists realestate | gzip -9 > "$FILE"

SIZE=$(stat -c %s "$FILE")
echo "[$(date --iso-8601=seconds)] дамп готов: $FILE ($SIZE байт)"

# Образ приложения даёт boto3 и ключи из .env; сам скрипт монтируем с диска,
# чтобы правка бэкапа не требовала пересборки образа.
docker compose run --rm --no-deps \
  -v "$BACKUP_DIR:/backups:ro" \
  -v "$PROJECT_DIR/deploy:/deploy:ro" \
  app python /deploy/backup_upload.py "/backups/$(basename "$FILE")"

# На диске держим только две последние копии: остальное уже в Object Storage,
# а место на минимальной машине тратить незачем.
ls -1t "$BACKUP_DIR"/reip-*.sql.gz | tail -n +3 | xargs -r rm -f
echo "[$(date --iso-8601=seconds)] готово"
