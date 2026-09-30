-- migrations/062_ai_bot.sql
-- ТЗ «AI-бот продажник» v1, раздел 2 (в ТЗ — 058, номер занят).
--
-- Черновик ответа в публичный чат живёт там, где он уже живёт по дополнению
-- Signal Bus, — signals.reply_draft / reply_status, и показывается в той же
-- очереди ответов Mini App. bot_public_replies только учитывает, что бот сделал
-- и чем кончилось, — для статистики и для отложенной отправки (Semi-Auto).
--
-- 152-ФЗ: до согласия в диалоге хранится только то, без чего бот не может
-- вести разговор (последние сообщения, собранные параметры). Отказ от
-- согласия или «стоп» стирают историю; см. app/services/bot_conversation.py.

ALTER TABLE agencies ADD COLUMN IF NOT EXISTS bot_mode TEXT NOT NULL DEFAULT 'disabled';
ALTER TABLE agencies DROP CONSTRAINT IF EXISTS agencies_bot_mode_check;
ALTER TABLE agencies ADD CONSTRAINT agencies_bot_mode_check
    CHECK (bot_mode IN ('disabled', 'assist', 'semi_auto', 'auto'));
ALTER TABLE agencies ADD COLUMN IF NOT EXISTS bot_reply_threshold INTEGER NOT NULL DEFAULT 60;
ALTER TABLE agencies ADD COLUMN IF NOT EXISTS bot_semi_auto_delay INTEGER NOT NULL DEFAULT 5;
ALTER TABLE agencies ADD COLUMN IF NOT EXISTS bot_daily_reply_limit INTEGER NOT NULL DEFAULT 50;
ALTER TABLE agencies ADD COLUMN IF NOT EXISTS bot_tone_ab_test TEXT NOT NULL DEFAULT 'expert';
ALTER TABLE agencies ADD COLUMN IF NOT EXISTS bot_settings JSONB NOT NULL DEFAULT '{}';

CREATE TABLE IF NOT EXISTS bot_conversations (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agency_id        UUID NOT NULL REFERENCES agencies(id) ON DELETE CASCADE,
    user_platform    TEXT NOT NULL,             -- telegram | max
    user_id          BIGINT NOT NULL,
    username         TEXT,
    display_name     TEXT,
    state            TEXT NOT NULL DEFAULT 'greeting' CHECK (state IN (
        'greeting', 'qualifying', 'consent_pending', 'qualified', 'escalated', 'done', 'silent')),
    history          JSONB NOT NULL DEFAULT '[]',
    collected_data   JSONB NOT NULL DEFAULT '{}',
    lead_id          UUID REFERENCES leads(id) ON DELETE SET NULL,
    signal_id        UUID REFERENCES signals(id) ON DELETE SET NULL,
    bot_mode         TEXT NOT NULL DEFAULT 'assist',
    tone_variant     TEXT NOT NULL DEFAULT 'expert',
    last_user_msg_at TIMESTAMPTZ,
    reminded_at      TIMESTAMPTZ,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- Один открытый диалог на человека в агентстве.
CREATE UNIQUE INDEX IF NOT EXISTS idx_bot_conv_open
    ON bot_conversations(agency_id, user_platform, user_id)
    WHERE state NOT IN ('done', 'silent', 'qualified');

CREATE TABLE IF NOT EXISTS bot_public_replies (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agency_id         UUID NOT NULL REFERENCES agencies(id) ON DELETE CASCADE,
    signal_id         UUID NOT NULL REFERENCES signals(id) ON DELETE CASCADE,
    reply_text        TEXT NOT NULL,
    tone_variant      TEXT NOT NULL DEFAULT 'expert',
    mode              TEXT NOT NULL,             -- режим агентства в момент генерации
    status            TEXT NOT NULL DEFAULT 'draft' CHECK (status IN (
        'draft', 'scheduled', 'sent', 'failed', 'rejected')),
    fail_reason       TEXT,
    scheduled_for     TIMESTAMPTZ,
    sent_at           TIMESTAMPTZ,
    sent_by           TEXT,                      -- bot | manager
    approved_by       UUID REFERENCES managers(id) ON DELETE SET NULL,
    got_response      BOOLEAN NOT NULL DEFAULT FALSE,
    converted_to_lead BOOLEAN NOT NULL DEFAULT FALSE,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_bot_reply_signal ON bot_public_replies(signal_id);
CREATE INDEX IF NOT EXISTS idx_bot_reply_agency ON bot_public_replies(agency_id, created_at DESC);

CREATE TABLE IF NOT EXISTS bot_learning_pool (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agency_id       UUID NOT NULL REFERENCES agencies(id) ON DELETE CASCADE,
    conversation_id UUID UNIQUE REFERENCES bot_conversations(id) ON DELETE CASCADE,
    tone_variant    TEXT,
    scenario        JSONB NOT NULL,              -- [{"user_message": ..., "bot_reply": ...}]
    outcome         TEXT NOT NULL CHECK (outcome IN (
        'lead_created', 'deal', 'escalated_converted', 'negative')),
    weight          REAL NOT NULL DEFAULT 1.0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Лид, собранный ботом в личке, — отдельный источник (ТЗ 5.3: source_type
-- "bot_dm"); ограничение из 001 его не знало, и первый же лид от бота упал бы.
ALTER TABLE leads DROP CONSTRAINT IF EXISTS leads_source_type_check;
ALTER TABLE leads ADD CONSTRAINT leads_source_type_check CHECK (source_type IN (
    'signal', 'lead_magnet', 'manual', 'referral', 'incoming_call', 'bot_dm'));
