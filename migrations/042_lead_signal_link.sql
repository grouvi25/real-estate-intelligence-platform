-- migrations/042_lead_signal_link.sql
-- Signal Bus addendum: link a lead back to the signal it originated from
-- (source_signal_id) and store the external CRM deal id once exported.

ALTER TABLE leads ADD COLUMN IF NOT EXISTS source_signal_id UUID
    REFERENCES signals(id) ON DELETE SET NULL;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS crm_deal_id TEXT;
CREATE INDEX IF NOT EXISTS idx_leads_source_signal ON leads(source_signal_id);
