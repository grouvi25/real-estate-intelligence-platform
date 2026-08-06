-- migrations/049_platform_settings.sql
-- TZ 2.2 calls the AI providers "переключаемые из админки", and the acceptance
-- checklist (35.4) spells it out: switched without a restart. They were not
-- switchable at all -- the provider came from AI_DEFAULT_PROVIDER in .env, so
-- moving off a foreign provider meant editing a file on the server and
-- restarting the containers.
--
-- That is not a convenience: OpenAI and Anthropic are reached through the proxy
-- with an anonymised prompt, YandexGPT and GigaChat keep the data in Russia, and
-- the choice between them is a 152-ФЗ decision the owner should be able to make
-- at any moment.

CREATE TABLE IF NOT EXISTS platform_settings (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_by  UUID
);
