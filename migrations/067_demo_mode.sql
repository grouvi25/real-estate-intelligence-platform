-- migrations/067_demo_mode.sql
-- ТЗ «Сигналы» v1.0, апгрейд C: демонстрационный режим.
--
-- Одна строка настроек (id = 1). Включает её оператор платформы. Демо-сессии и
-- демо-данные живут только в Redis: демо-запрос не делает ни одного SQL.
-- updated_by — Telegram id оператора: таблицы users в REIP нет, оператор
-- платформы определяется по Telegram id (platform_operators).

CREATE TABLE IF NOT EXISTS demo_config (
    id               INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    enabled          BOOLEAN NOT NULL DEFAULT FALSE,
    demo_city        TEXT NOT NULL DEFAULT 'Краснодар',
    session_ttl_min  INTEGER NOT NULL DEFAULT 30 CHECK (session_ttl_min BETWEEN 5 AND 1440),
    headline         TEXT NOT NULL DEFAULT 'Демо-режим REIP — данные синтетические',
    allowed_tabs     TEXT[] NOT NULL DEFAULT ARRAY['dashboard', 'signals', 'leads', 'analytics'],
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_by       BIGINT
);

INSERT INTO demo_config (id) VALUES (1) ON CONFLICT DO NOTHING;

-- «Оставьте заявку» из демо: заявка без Telegram, связь по телефону.
ALTER TABLE onboarding_requests ALTER COLUMN telegram_id DROP NOT NULL;
ALTER TABLE onboarding_requests ADD COLUMN IF NOT EXISTS source TEXT NOT NULL DEFAULT 'sales_bot';
ALTER TABLE onboarding_requests DROP CONSTRAINT IF EXISTS onboarding_requests_source_check;
ALTER TABLE onboarding_requests ADD CONSTRAINT onboarding_requests_source_check
    CHECK (source IN ('sales_bot', 'demo'));
