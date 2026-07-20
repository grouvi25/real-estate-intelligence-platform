# Траблшутинг и аварийное восстановление (ТЗ раздел 25)

## Частые проблемы

| Симптом | Диагностика | Решение |
|---|---|---|
| **Вебхуки не доходят** | `journalctl -u nginx \| grep 499`; проверить `setWebhook` | Проверить SSL, firewall, URL вебхука. Убедиться, что порт 443 открыт. Секрет-токен вебхука должен совпадать (`TELEGRAM_WEBHOOK_SECRET`). |
| **AI таймаутит (504)** | Nginx error log; `proxy_read_timeout` | Увеличить до 120s. Проверить квоты YandexGPT в консоли YC. Проверить дневной AI-бюджет (`/api/health/deep`, логи `AI budget exceeded`). |
| **Celery задачи висят в PENDING** | `celery -A worker.celery_app inspect active` | Перезапустить worker (`docker compose restart worker`). Проверить `REDIS_URL` и доступность Redis. |
| **Шифрование падает** | `cryptography.fernet.InvalidToken` | Проверить `ENCRYPTION_KEY` в `.env` — ровно 44 символа base64. **Потеря ключа = потеря доступа к ПД.** |
| **Потеря данных в БД** | YC Console → Managed PostgreSQL → Backups | Восстановить из снапшота: `yc managed-postgresql cluster restore`. |
| **Деплой падает на конфликте контейнеров** | `Conflict. The container name ... already in use` | Убрать осиротевшие контейнеры: `docker ps -a --filter name=reip-app-1`. CD сериализован (`concurrency`) — параллельных деплоев не будет. |
| **`/health/deep` = degraded** | Поле `checks` в ответе | Смотреть, что именно `error`: `database` (проверить `DATABASE_URL`, доступность PG), `redis` (`REDIS_URL`). |

## Регламент бэкапов

- **PostgreSQL:** автоматические снапшоты YC (ежедневно, хранение 7 дней).
- **Object Storage:** включён S3 Versioning.
- **`.env` и `sa-key.json`:** хранятся в Vault / Password Manager, **не в git** (`.gitignore` блокирует `.env`, `*.key`, `secrets/`).

## Быстрые команды (на VPS, `/opt/reip`)

```bash
docker compose ps                     # статус контейнеров
docker compose logs app --tail 100    # логи приложения (JSON, structlog)
docker compose logs worker --tail 100 # логи Celery worker
docker compose restart app worker     # перезапуск без пересборки
docker compose up -d --build          # передеплой (обычно делает CD автоматически)
curl -fsS localhost:8000/api/health/deep   # проверка зависимостей
```
