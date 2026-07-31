# Real Estate Intelligence Platform (REIP)

AI-платформа разведки покупателей недвижимости для агентства.

> **Суть системы:** находит людей с намерением купить в открытых источниках →
> квалифицирует их через AI → анализирует объекты и рынок → готовит менеджера к точному контакту.

## Статус

- **Версия ТЗ:** 2.0 FINAL + Дополнение v1.0 (Signal Bus & Attribution)
- **Разделы ТЗ 1–35:** реализованы, развёрнуты и проверены на живом стенде
- **Прод:** https://reip.grouvi.online — деплой автоматический из `main`
- **Тесты:** 393 Python + 14 Mini App, прогоняются в CI на живых Postgres и Redis

Что система пока не делает: не находит живых покупателей. Конвейер исправен на
каждом стыке, но в Telegram по Геленджику профильных чатов почти нет — это
вопрос источников, а не кода. Подробности и полный перечень открытых пунктов —
в [docs/audit.md](docs/audit.md).

## Технический стек

| Слой | Технология |
|------|-----------|
| Язык | Python 3.11+ (type hints обязательны) |
| Фреймворк | FastAPI 0.109+ (async, OpenAPI 3.1) |
| БД | PostgreSQL 15 (Yandex Managed Service) |
| ORM | SQLAlchemy 2.0 + asyncpg |
| Очереди | Redis 7 + Celery 5.3 |
| Боты | aiogram 3.3 (Telegram) + MAX Bot API |
| Mini App | HTML + Vanilla JS / Vue 3 (mobile-first, 390px) |
| Хранилище | Yandex Object Storage (S3-compatible) |
| Деплой | Yandex Cloud (Compute Cloud + Container Registry) |
| Логирование | structlog + Yandex Cloud Logging |

## Соответствие 152-ФЗ

- ✅ Все персональные данные хранятся в Yandex Cloud (ru-central1).
- ✅ ПД шифруются в приложении (Fernet, AES-128-CBC + HMAC-SHA256).
- ⚠️ Зарубежные AI (OpenAI/Anthropic) вызываются только через Railway-прокси и только с обезличенным промптом.
- ❌ Никакие ПД не покидают РФ.

## Что система НЕ делает

- ❌ Не продаёт квартиры вместо риелтора
- ❌ Не пишет в личку без opt-in
- ❌ Не покупает и не использует базы телефонов
- ❌ Не обходит антибот-защиту площадок (ЦИАН, Авито)
- ❌ Не выдаёт AI за живого человека при контакте
- ❌ Не хранит ПД за пределами РФ

## Локальный запуск

```bash
cp .env.example .env   # заполнить ключами
docker compose up
```

Проверка: `GET /health` → `{"status": "ok"}`

Схема применяется автоматически при старте. Вручную — любым из двух путей,
они дают одинаковый результат:

```bash
alembic upgrade head
```

## Эксплуатация

| Задача | Как |
|---|---|
| Загрузить каталог объектов | Mini App → Объекты → «Загрузить каталог» (CSV/XLSX, сначала проверка) |
| Добавить чат для мониторинга | Mini App → Профиль → Источники |
| Вход аккаунта-коллектора | `docker compose exec app python scripts/telethon_login.py` |
| Установить вебхук Telegram | `docker compose exec app python scripts/set_telegram_webhook.py --set` |
| Нагрузочный тест | `python scripts/loadtest.py --url https://reip.grouvi.online --rps 50` |

Ключи, без которых части системы работают в урезанном режиме и не падают:
`YC_*` (логи в Cloud Logging и Object Storage → иначе локальный диск),
`MAX_BOT_*` (кабинет в MAX), `TELETHON_*` (сбор из Telegram).

## Структура проекта

```
app/            # FastAPI-приложение (ядро, модели, роутеры, сервисы)
  models/       # SQLAlchemy ORM
  routers/      # API endpoints
  services/     # AI, боты, шифрование, matching, discovery
    ai_providers/  # YandexGPT, GigaChat, OpenAI (proxy)
    channels/      # адаптеры каналов ответа (Signal Bus, доп. v1.0)
    crm/           # адаптеры CRM (Topnlab/amoCRM/Bitrix24/YUcrm, доп. v1.0)
  collectors/   # Telethon, VK, YouTube, RSS
  discovery/    # Source Discovery Engine
  prompts/      # 10 системных AI-промптов
worker/         # Celery worker + фоновые задачи
mini_app/       # Telegram/MAX Mini App (единый код)
railway_proxy/  # прокси для зарубежных AI
migrations/     # SQL-миграции
alembic/        # Alembic поверх тех же файлов (ТЗ 35.1)
tests/          # pytest
```

## Реализация

- [x] **Часть 1 — Фундамент:** config, database, security, base models, auth, health, bot abstraction, AI service, encryption, миграции, Docker.
- [x] **Часть 2:** ORM-модели, 152-ФЗ шифрование, Bot Abstraction, AI-роутинг, Celery-ядро.
- [x] **Часть 3:** API-роутеры, Source Discovery, Intent Scoring, Matching, Lead Magnets, Mini App.
- [x] **Часть 4:** Партнёрская сеть, Knowledge Moat, альтернативщики, деплой, мониторинг.
- [x] **Дополнение v1.0:** Signal Bus, адаптеры каналов/CRM, сквозная атрибуция (миграции 040–044).

Развёрнуто сверх ТЗ по результатам работы на живых данных: экраны «Задачи» и
«Источники», импорт каталога, договор и чек-лист в PDF, отправка логов в
Yandex Cloud Logging, обработка `/start` в Telegram и MAX.
