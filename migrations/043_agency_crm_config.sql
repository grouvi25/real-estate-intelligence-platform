-- migrations/043_agency_crm_config.sql
-- Signal Bus addendum: per-agency CRM connector configuration. Supports several
-- Russian CRMs (Topnlab, amoCRM, Bitrix24, YUcrm). The API key is stored
-- encrypted (BYTEA, Fernet) like other secrets; never in plaintext.

CREATE TABLE IF NOT EXISTS agency_crm_config (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agency_id UUID NOT NULL REFERENCES agencies(id) ON DELETE CASCADE,
    crm_type TEXT NOT NULL,             -- topnlab / amocrm / bitrix24 / yucrm
    base_url TEXT,
    api_key_encrypted BYTEA,
    config JSONB NOT NULL DEFAULT '{}'::jsonb,
    field_mapping JSONB NOT NULL DEFAULT '{}'::jsonb,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (agency_id, crm_type)
);
CREATE INDEX IF NOT EXISTS idx_agency_crm_config_agency ON agency_crm_config(agency_id);
