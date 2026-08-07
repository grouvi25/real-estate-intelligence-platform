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
| `auth.py` | `/api/auth` | Telegram WebApp HMAC + MAX, **invite-only manager onboarding**, AI provider switch, agency settings (owner only). |
| `geo.py` | `/api/geo` | Geo protection, create, reserve, keyword discovery. |
| `signals.py` | `/api/signals` | List, create-lead, generate-reply, **triage queue: reply / escalate / dismiss / qualify (Signal Bus §5.1)**. |
| `leads.py` | `/api/leads` | List (incl. **phone lookup via blind index**), card+matches, status, match feedback, commercial-offer doc, process-alternative, **152-ФЗ export + erase**. |
| `properties.py` | `/api/properties` | List, PATCH (price → rematch), catalogue import, object report doc. |
| `lead_magnets.py` | `/api/lm` | LM-1..LM-6 (property finder, mortgage, object-check, districts, ROI) + subscribe. |
| `referrals.py` | `/api/referrals` | Partner referrals. |
| `deals.py` | `/api/deals` | Record deal outcome (Knowledge Moat). |
| `analytics.py` | `/api/analytics` | overview, funnel, managers, source-roi. |
| `webhooks.py` | `/api/webhooks` | Telegram webhook secret verification. |
| `health.py` | `/api` | `/health`, `/health/deep` (db, redis, ai, telegram_bot, celery_queue). |

## Services (`app/services/`)
Core: `ai_service`, `ai_cost_tracker`, `bot_abstraction`, `encryption`, `pii_anonymizer`, `consent_manager` (152-ФЗ §14 export / §21 erasure + phone lookup), `rate_limit`, `matching`, `intent_scoring`, `geo_protection`, `dedup_service`, `alternative_lead`, `alerts`, `crm_export`, `document_service`, `property_import`, `report_generator`, `readiness`, `platform_settings`, `storage`, `yc_logging`, `signal_bus`.
- `ai_providers/` — YandexGPT / GigaChat / OpenAI / Anthropic behind one interface, switchable at runtime.
- `lead_magnets/` — `mortgage_calculator`, `roi_calculator`, `districts`, `object_checker`.
- `channels/` — `base`, `classifieds` (Avito/CIAN — refuse with a reason until the agency has a professional account), `messaging` (Telegram/MAX/YouTube/RSS), `vk` + registry.
- `crm/` — `base`, `adapters` (Topnlab/amoCRM/Bitrix24/YUcrm) + registry. Selected per agency via `agency_crm_config`; deal ids flow back for attribution.

## Discovery & collectors
`app/discovery/`: `keyword_builder`, `source_finder` (candidate search + AI evaluation).
`app/collectors/` — each is credential-gated and a no-op without its key, so an
agency that has not supplied one simply collects nothing from that platform:
| Collector | Reads | Gate |
|-----------|-------|------|
| `telegram_collector.py` | Telethon userbot: candidate channels → messages | session file |
| `vk_collector.py` | walls, comments (`sort=desc`), board topics | `VK_SERVICE_TOKEN` |
| `youtube_collector.py` | comments under a channel's recent uploads (playlist walk: 1 quota unit vs 100 for search) | `YOUTUBE_API_KEY` |
| `rss_collector.py` | RSS/Atom feeds — regional news and forum digests | none (the source list is the switch) |
All write into content_units + signals with `origin_system = reip_scouting`.
Driven by `worker/tasks/collector_tasks.py`.

## Prompts (`app/prompts/`)
11 AI prompt modules (qualification, intent_scoring, pitch_generator, reply_generator, buyer_profile, object_analysis, market_analysis, listing_generator, geo_keywords, source_evaluation, daily_report). See "Deviations" below re: `match_scorer.py`.

## Workers (`worker/`)
`celery_app.py` (app + beat schedule). Tasks: `maintenance_tasks` (ai-cost reset, lead-urgency decay, escalate-overdue, dead-source check, queue-depth alert), `matching_tasks` (run + rematch-on-price-change + nightly price-drop sweep for prices changed outside the API), `collector_tasks` (telegram / vk / web), `geo_tasks`, `source_tasks`, `partner_tasks`, `knowledge_tasks` (weekly weight learning), `crm_tasks`, `signal_tasks`, `report_tasks` (daily manager report 07:30).

## Migrations (`migrations/`)
`001_init` .. `008_status_extensions` (core + product extensions), `040`–`044` (Signal Bus: content_units, signal reply fields, lead↔signal link, agency_crm_config, `v_signal_to_outcome` view), `045`–`053` (escalation stage, source geo backfill, agency invite token, platform settings, Signal Bus conformance to the addendum, PD erasure, triage statuses, property price watch). Applied idempotently by the SQL migration runner, one marker table per file.

## Mini App (`mini_app/`)
Vanilla-JS SPA (no bundler). `platform_init.js` (Telegram/MAX SDK + api), `js/api_client.js`, `js/components.js` (UI kit: skeletons, empty/error states, RU pluralisation), `js/router.js` (hash router), `js/auth.js`, `js/app.js` (bootstrap + bottom nav), `js/screens/*` (dashboard, signals, signal triage queue, leads, properties, analytics/settings, tasks, sources). `css/styles.css` is a token-based design system: every colour and metric is a custom property, states are `@media (hover: hover)` + `:focus-visible` + `:active`, no geometry animates, `prefers-reduced-motion` honoured, 44px minimum targets, light and dark.

## Deviations from the TZ file manifest
Recorded deliberately, not oversights. Both agreed with the client on 08.08.2026.

| TZ manifest | Here | Why |
|-------------|------|-----|
| `app/services/ai/prompts/match_scorer.py` — AI scores each lead↔property pairing | No such prompt; `services/matching.py` scores by weights | The TZ's own acceptance list (35.7) requires the weighted model — budget +30, segment +25, location +20, priorities +15, hot +10 — and the TZ's own code sample for section 16.2 is a pure arithmetic function. `match_scorer.py` appears only as a filename: no prompt text, no call site, no acceptance criterion. AI already runs on **both** inputs upstream (`buyer_profile` extracts the buyer's priorities, `object_analysis` extracts the property's strengths); the score compares those two AI-produced lists. A third AI call would re-judge what the first two extracted, at one call per catalogue entry per lead instead of one per surfaced match. Weights are additionally re-learned weekly from closed deals (Knowledge Moat), bounded to 5–45. |
| `source_scorer.py` as its own file | Source scoring lives inside `discovery/source_finder.py` | Functionally complete; splitting the file would move code without changing behaviour. |
| prompts under `app/services/ai/prompts/` | `app/prompts/` | The TZ's own code samples import `from app.prompts.…`; the manifest tree contradicts the TZ body, and the body won. |

## Infra & CI
`Dockerfile`, `docker-compose.yml`, `.github/workflows/ci.yml` (test + frontend + deploy to VPS), `pyproject.toml` (deps + optional `pdf`/`storage` extras), `.env.example`.

## Tests (`tests/`)
40+ test modules. Pure unit tests run everywhere; DB-integration tests gated behind `RUN_DB_TESTS=1` (run in CI against Postgres+Redis services).
