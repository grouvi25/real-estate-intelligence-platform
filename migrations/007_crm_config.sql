-- migrations/007_crm_config.sql
-- TZ section 32: outbound CRM export. Agencies can push qualified leads to their
-- own CRM via a webhook. crm_field_mapping maps REIP lead fields to the CRM's
-- expected payload keys.

ALTER TABLE agencies ADD COLUMN IF NOT EXISTS crm_export_enabled BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE agencies ADD COLUMN IF NOT EXISTS crm_type TEXT;
ALTER TABLE agencies ADD COLUMN IF NOT EXISTS crm_webhook_url TEXT;
ALTER TABLE agencies ADD COLUMN IF NOT EXISTS crm_field_mapping JSONB NOT NULL DEFAULT '{}'::jsonb;
