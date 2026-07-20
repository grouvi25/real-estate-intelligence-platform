# File manifest — Real Estate Intelligence Platform (REIP)

TZ section 34. Map of every source file and what it does. Grouped by area.

## Application core (`app/`)
| File | Purpose |
|------|---------|
| `app/main.py` | FastAPI entrypoint: lifespan (migrations + init), middleware, exception handlers, router wiring, `/mini-app` static mount. |
| `app/config.py` | Pydantic settings (env-driven). |
| `app/database.py` | Async engine, session dependency, SQL-file migration runner (NullPool under tests). |
| `app/dependencies.py` | `get_current_manager` — JWT auth context (agency-scoped). |
| `app/security.py` | JWT create/decode (HS256). |
| `app/exceptions.py` | App exception hierarchy (consent, geo-protected, budget, etc.). |
| `app/logging_config.py` | structlog JSON logging setup. |

## Models (`app/models/`)
15 base tables + Signal Bus additions: `agency`, `agency_crm_config`, `manager`, `geo_location`, `protected_geo`, `source`, `source_discovery_log`, `signal`, `content_unit`, `lead`, `property`, `match`, `match_exclusion`, `task`, `partner_agency`, `partner_referral`, `deal_outcome`, `activity_log`. `base.py` holds `Base` + timestamp mixins. PII columns are encrypted (Fernet) via hybrid properties.

## Routers (`app/routers/`)
| Router | Prefix | Endpoints |
|--------|--------|-----------|
| `auth.py` | `/api/auth` | Telegram WebApp HMAC + MAX (dev). |
| `geo.py` | `/api/geo` | Geo protection, create, reserve, keyword discovery. |
| `signals.py` | `/api/signals` | List, create-lead, generate-reply, **reply queue + send (Signal Bus)**. |
| `leads.py` | `/api/leads` | List, card+matches, status, match feedback, commercial-offer doc, process-alternative. |
| `properties.py` | `/api/properties` | List, PATCH (price → rematch), object report doc. |
| `lead_magnets.py` | `/api/lm` | LM-1..LM-6 (property finder, mortgage, object-check, districts, ROI) + subscribe. |
| `referrals.py` | `/api/referrals` | Partner referrals. |
| `deals.py` | `/api/deals` | Record deal outcome (Knowledge Moat). |
| `analytics.py` | `/api/analytics` | overview, funnel, managers, source-roi. |
| `webhooks.py` | `/api/webhooks` | Telegram webhook secret verification. |
| `health.py` | `/api` | `/health`, `/health/deep` (db, redis, ai, telegram_bot, celery_queue). |

## Services (`app/services/`)
Core: `ai_service`, `ai_cost_tracker`, `bot_abstraction`, `encryption`, `pii_anonymizer`, `rate_limit`, `matching`, `intent_scoring`, `geo_protection`, `dedup_service`, `alternative_lead`, `alerts`, `crm_export`, `document_service`, `storage`, `signal_bus`.
- `lead_magnets/` — `mortgage_calculator`, `roi_calculator`, `districts`, `object_checker`.
- `channels/` — `base`, `classifieds` (Avito/CIAN), `messaging` (Telegram/MAX), `vk` + registry.
- `crm/` — `base`, `adapters` (Topnlab/amoCRM/Bitrix24/YUcrm) + registry.

## Discovery (`app/discovery/`)
`keyword_builder`, `source_finder` (Telethon search stub + evaluation).

## Prompts (`app/prompts/`)
11 AI prompt modules (qualification, intent_scoring, pitch_generator, reply_generator, buyer_profile, object_analysis, market_analysis, listing_generator, geo_keywords, source_evaluation, daily_report).

## Workers (`worker/`)
`celery_app.py` (app + beat schedule). Tasks: `maintenance_tasks` (ai-cost reset, lead-score decay, escalate-overdue, dead-source check), `matching_tasks` (run + rematch-on-price-change), `geo_tasks`, `source_tasks`, `partner_tasks`, `knowledge_tasks`, `crm_tasks`.

## Migrations (`migrations/`)
`001_init` .. `008_status_extensions` (core + product extensions) and `040`–`044` (Signal Bus: content_units, signal reply fields, lead↔signal link, agency_crm_config, `v_signal_to_outcome` view). Applied idempotently by the SQL migration runner.

## Mini App (`mini_app/`)
Vanilla-JS SPA (no bundler). `platform_init.js` (Telegram/MAX SDK + api), `js/api_client.js`, `js/components.js` (UI), `js/router.js` (hash router), `js/auth.js`, `js/app.js` (bootstrap + bottom nav), `js/screens/*` (dashboard, signals, signal reply queue, leads, properties, analytics, settings). Theming via Telegram CSS variables.

## Infra & CI
`Dockerfile`, `docker-compose.yml`, `.github/workflows/ci.yml` (test + frontend + deploy to VPS), `pyproject.toml` (deps + optional `pdf`/`storage` extras), `.env.example`.

## Tests (`tests/`)
40+ test modules. Pure unit tests run everywhere; DB-integration tests gated behind `RUN_DB_TESTS=1` (run in CI against Postgres+Redis services).
