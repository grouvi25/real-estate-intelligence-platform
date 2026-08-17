# Траблшутинг и аварийное восстановление (ТЗ раздел 25)

## Частые проблемы

| Симптом | Диагностика | Решение |
|---|---|---|
| **Вебхуки не доходят** | `journalctl -u nginx \| grep 499`; проверить `setWebhook` | Проверить SSL, firewall, URL вебхука. Убедиться, что порт 443 открыт. Секрет-токен вебхука должен совпадать (`TELEGRAM_WEBHOOK_SECRET`). |
| **AI таймаутит (504)** | Nginx error log; `proxy_read_timeout` | Увеличить до 120s. Проверить квоты YandexGPT в консоли YC. Проверить дневной AI-бюджет (`/api/health/deep`, логи `AI budget exceeded`). |
| **Celery задачи висят в PENDING** | `celery -A worker.celery_app inspect active` | Перезапустить worker (`docker compose restart worker`). Проверить `REDIS_URL` и доступность Redis. |
| **Шифрование падает** | `cryptography.fernet.InvalidToken` | Проверить `ENCRYPTION_KEY` в `.env` — ровно 44 символа base64. **Потеря ключа = потеря доступа к ПД.** |
| **Потеря данных в БД** | `aws s3 ls s3://reip-storage-b1g3nanpk/backups/db/` | Восстановить из ежедневного дампа — процедура ниже. |
| **Деплой падает на конфликте контейнеров** | `Conflict. The container name ... already in use` | Убрать осиротевшие контейнеры: `docker ps -a --filter name=reip-app-1`. CD сериализован (`concurrency`) — параллельных деплоев не будет. |
| **`/health/deep` = degraded** | Поле `checks` в ответе | Смотреть, что именно `error`: `database` (проверить `DATABASE_URL`, доступность PG), `redis` (`REDIS_URL`). |

## Регламент бэкапов

- **PostgreSQL:** `deploy/backup-db.sh` по cron в 03:00 каждый день — `pg_dump` в
  `s3://reip-storage-b1g3nanpk/backups/db/`, хранение 7 дней, на диске машины
  остаются две последние копии. Управляемый PostgreSQL со своими снапшотами
  стоил бы дороже всей остальной инфраструктуры вместе взятой, поэтому база
  живёт в контейнере, а роль снапшотов выполняет этот дамп.
- **Object Storage:** включён S3 Versioning — он же страхует и сами дампы.
- **`.env` и `sa-key.json`:** хранятся в Vault / Password Manager, **не в git** (`.gitignore` блокирует `.env`, `*.key`, `secrets/`).

### Восстановление базы из дампа

```bash
cd /opt/reip
# 1. Взять нужную копию (список: backups/db/ в Object Storage)
docker compose run --rm --no-deps -v /opt/reip/backups:/backups \
  app python -c "import boto3,os; boto3.client('s3', endpoint_url=os.environ['YC_S3_ENDPOINT'], aws_access_key_id=os.environ['YC_S3_ACCESS_KEY'], aws_secret_access_key=os.environ['YC_S3_SECRET_KEY']).download_file(os.environ['YC_S3_BUCKET'], 'backups/db/ИМЯ.sql.gz', '/backups/restore.sql.gz')"
# 2. Остановить всё, что пишет в базу
docker compose stop app worker beat
# 3. Накатить (дамп сделан с --clean --if-exists, чистить руками не нужно)
zcat backups/restore.sql.gz | docker compose exec -T db psql -U re_app -d realestate
# 4. Поднять обратно и проверить
docker compose up -d && curl -fsS localhost:8000/api/health/deep
```

## Быстрые команды (на VPS, `/opt/reip`)

```bash
docker compose ps                     # статус контейнеров
docker compose logs app --tail 100    # логи приложения (JSON, structlog)
docker compose logs worker --tail 100 # логи Celery worker
docker compose restart app worker     # перезапуск без пересборки
docker compose up -d --build          # передеплой (обычно делает CD автоматически)
curl -fsS localhost:8000/api/health/deep   # проверка зависимостей
```

## Telegram: почему он ходит через прокси

Из Yandex Cloud (ru-central1) Telegram недоступен целиком — ни `api.telegram.org`,
ни дата-центры MTProto, куда стучится Telethon. Проверено с обеих сторон: с
сервера Beget в Москве все адреса отвечают, из облака — ни один.

Поэтому все **исходящие** обращения к Telegram идут через SOCKS5:
`TELEGRAM_PROXY_URL=socks5://172.17.0.1:1080`. Канал держит служба
`reip-telegram-proxy` на сервере 194.156.116.209 — обратный SSH-туннель,
который слушает на docker-мосту облачной машины. Служба с автозапуском и
перезапуском, к другим проектам на том сервере отношения не имеет.

Вебхуки через прокси не идут: их Telegram доставляет к нам сам, а входящие
подключения не фильтруются.

Если Telegram перестал отвечать:

```bash
# на облачной машине: жив ли канал
ss -ltn | grep 1080
docker compose exec app python -c "import httpx,os; from app.config import config; print(httpx.get(f'https://api.telegram.org/bot{config.telegram_bot_token}/getMe', proxy=config.telegram_proxy_url, timeout=20).json()['ok'])"

# на сервере 194.156.116.209: состояние службы
systemctl status reip-telegram-proxy
systemctl restart reip-telegram-proxy
```

`/api/health/deep` проверяет дата-центр по-настоящему: `telethon: unreachable`
означает, что канал лежит. Раньше там стояло `active` всегда, когда прописаны
ключи, и молчаливо скрывало, что сбор не работает.

## Логи

Docker пишет через драйвер `journald` (задано в `/etc/docker/daemon.json`), а
контейнер `logs` — Unified Agent — читает журнал и отправляет всё в Cloud
Logging. Поэтому логи доступны тремя способами:

```bash
docker compose logs app --tail 100        # как обычно, драйвер journald это умеет
journalctl -t reip-app-1 -f               # то же самое с хоста
yc logging read --group-name default --folder-id b1g3nanpk22hv91s5kcb --since 1h
```

Если в Cloud Logging пусто, а `docker compose logs logs` показывает
`sd_journal_get_data failed` — агент собран с libsystemd от Ubuntu 18.04 и не
читает сжатые записи журнала. Сжатие отключено (`Compress=no` в
`/etc/systemd/journald.conf`); после его случайного возврата нужно снова
выключить, повернуть журнал и сбросить состояние агента:

```bash
sudo journalctl --rotate && sudo journalctl --vacuum-time=1s
docker compose rm -sf logs && docker volume rm reip_ua_state && docker compose up -d logs
```
