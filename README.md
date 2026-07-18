# Real Estate Intelligence Platform (REIP)

AI-платформа разведки покупателей недвижимости для агентства.

> **Суть системы:** находит людей с намерением купить в открытых источниках →
> квалифицирует их через AI → анализирует объекты и рынок → готовит менеджера к точному контакту.

## Статус

- **Версия ТЗ:** 2.0 FINAL + Дополнение v1.0 (Signal Bus & Attribution)
- **Этап:** каркас проекта (Часть 1 — Фундамент)

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
docker-compose up
```

Проверка: `GET /health` → `{"status": "ok"}`

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
tests/          # pytest
```

## Роадмап реализации

- [ ] **Часть 1 — Фундамент:** config, database, security, base models, auth, health, bot abstraction, AI service, encryption, миграция 001, Docker.
- [ ] **Часть 2:** ORM-модели, 152-ФЗ шифрование, Bot Abstraction, AI-роутинг, Celery-ядро.
- [ ] **Часть 3:** API-роутеры, Source Discovery, Intent Scoring, Matching, Lead Magnets, Mini App.
- [ ] **Часть 4:** Партнёрская сеть, Knowledge Moat, альтернативщики, деплой, мониторинг.
- [ ] **Дополнение v1.0:** Signal Bus, адаптеры каналов/CRM, сквозная атрибуция (миграции 040–044).
