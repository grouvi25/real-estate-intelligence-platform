-- migrations/060_saas_layer.sql
-- ТЗ «SaaS-слой: коммерциализация платформы» v1, раздел 2 (в ТЗ — 059, номер занят).
--
-- Отличия от ТЗ, все в сторону уже принятых в проекте правил:
-- * Лимиты тарифа NULL = «без ограничений». В ТЗ умолчания 3 менеджера / 1 город,
--   и действующее агентство заказчика сразу упёрлось бы в них. Новые агентства
--   получают лимиты своего тарифа при онбординге.
-- * Токен бота, телефон и e-mail владельца, телефон из заявки — BYTEA,
--   шифруются в приложении (Fernet), как остальные ПД и секреты (152-ФЗ).
-- * Существующим агентствам подписка бессрочная (expires_at NULL) и активная.

ALTER TABLE agencies ADD COLUMN IF NOT EXISTS subscription_active BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE agencies ADD COLUMN IF NOT EXISTS subscription_expires_at TIMESTAMPTZ;
ALTER TABLE agencies ADD COLUMN IF NOT EXISTS subscription_started_at TIMESTAMPTZ;
ALTER TABLE agencies ADD COLUMN IF NOT EXISTS monthly_price_rub INTEGER NOT NULL DEFAULT 0;
ALTER TABLE agencies ADD COLUMN IF NOT EXISTS one_time_price_rub INTEGER NOT NULL DEFAULT 0;
ALTER TABLE agencies ADD COLUMN IF NOT EXISTS max_managers INTEGER;
ALTER TABLE agencies ADD COLUMN IF NOT EXISTS max_cities INTEGER;
ALTER TABLE agencies ADD COLUMN IF NOT EXISTS monthly_ai_budget_rub INTEGER;
ALTER TABLE agencies ADD COLUMN IF NOT EXISTS telegram_bot_token_encrypted BYTEA;
ALTER TABLE agencies ADD COLUMN IF NOT EXISTS telegram_bot_username TEXT;
ALTER TABLE agencies ADD COLUMN IF NOT EXISTS telegram_webhook_secret TEXT;
ALTER TABLE agencies ADD COLUMN IF NOT EXISTS onboarding_completed_at TIMESTAMPTZ;
ALTER TABLE agencies ADD COLUMN IF NOT EXISTS platform_notes TEXT;
ALTER TABLE agencies ADD COLUMN IF NOT EXISTS owner_telegram_id BIGINT;
ALTER TABLE agencies ADD COLUMN IF NOT EXISTS owner_phone_encrypted BYTEA;
ALTER TABLE agencies ADD COLUMN IF NOT EXISTS owner_email_encrypted BYTEA;
ALTER TABLE agencies ADD COLUMN IF NOT EXISTS logo_url TEXT;
ALTER TABLE agencies ADD COLUMN IF NOT EXISTS brand_color TEXT;
ALTER TABLE agencies ADD COLUMN IF NOT EXISTS welcome_message TEXT;
CREATE UNIQUE INDEX IF NOT EXISTS idx_agencies_bot_username
    ON agencies(lower(telegram_bot_username)) WHERE telegram_bot_username IS NOT NULL;

CREATE TABLE IF NOT EXISTS subscription_plans (
    id                TEXT PRIMARY KEY,           -- start | pro | isolated
    name              TEXT NOT NULL,
    one_time_price    INTEGER NOT NULL,
    monthly_price     INTEGER NOT NULL DEFAULT 0,
    max_managers      INTEGER NOT NULL DEFAULT 3,
    max_cities        INTEGER NOT NULL DEFAULT 1,
    monthly_ai_budget INTEGER NOT NULL DEFAULT 1500,
    bot_mode_allowed  TEXT NOT NULL DEFAULT 'assist',
    features          JSONB NOT NULL DEFAULT '{}',
    is_active         BOOLEAN NOT NULL DEFAULT TRUE,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO subscription_plans
    (id, name, one_time_price, monthly_price, max_managers, max_cities, monthly_ai_budget,
     bot_mode_allowed, features)
VALUES
    ('start', 'Старт', 250000, 0, 3, 1, 1500, 'assist',
     '{"avito_sync": true, "ai_bot": false}'),
    ('pro', 'Про', 350000, 15000, 5, 2, 3000, 'semi_auto',
     '{"avito_sync": true, "ai_bot": true}'),
    ('isolated', 'Выделенный', 500000, 20000, 20, 5, 10000, 'auto',
     '{"avito_sync": true, "ai_bot": true, "white_label": true}')
ON CONFLICT (id) DO NOTHING;

CREATE TABLE IF NOT EXISTS billing_events (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agency_id        UUID REFERENCES agencies(id) ON DELETE CASCADE,
    onboarding_request_id UUID,
    event_type       TEXT NOT NULL CHECK (event_type IN (
        'payment', 'refund', 'trial_start', 'subscription_renewed',
        'subscription_expired', 'manually_extended', 'discount_applied',
        'suspended', 'unsuspended')),
    amount_rub       INTEGER,
    payment_method   TEXT,                        -- yookassa | tinkoff | manual | promo
    payment_id       TEXT,
    months_added     INTEGER NOT NULL DEFAULT 0,
    expires_at_after TIMESTAMPTZ,
    note             TEXT,
    created_by       TEXT NOT NULL DEFAULT 'system',
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_billing_agency ON billing_events(agency_id, created_at DESC);
-- Один платёж ЮKassa засчитывается один раз, сколько бы уведомлений ни пришло.
CREATE UNIQUE INDEX IF NOT EXISTS idx_billing_payment_once
    ON billing_events(payment_method, payment_id) WHERE payment_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS platform_operators (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    telegram_id  BIGINT NOT NULL UNIQUE,
    username     TEXT,
    display_name TEXT,
    is_active    BOOLEAN NOT NULL DEFAULT TRUE,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS onboarding_requests (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    telegram_id     BIGINT NOT NULL,
    username        TEXT,
    display_name    TEXT,
    phone_encrypted BYTEA,
    city_name       TEXT NOT NULL,
    agency_name     TEXT NOT NULL,
    plan_id         TEXT NOT NULL DEFAULT 'start' REFERENCES subscription_plans(id),
    status          TEXT NOT NULL DEFAULT 'pending' CHECK (status IN (
        'pending', 'payment_pending', 'paid', 'completed', 'rejected')),
    payment_link    TEXT,
    payment_id      TEXT,
    agency_id       UUID REFERENCES agencies(id) ON DELETE SET NULL,
    operator_notes  TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_onboarding_status ON onboarding_requests(status, created_at DESC);
