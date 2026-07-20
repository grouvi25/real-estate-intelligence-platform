-- migrations/006_lead_utm.sql
-- TZ section 32: UTM / attribution. Landing pages and lead magnets pass through
-- UTM tags so source-ROI analytics can attribute deals back to campaigns.

ALTER TABLE leads ADD COLUMN IF NOT EXISTS utm_source TEXT;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS utm_medium TEXT;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS utm_campaign TEXT;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS utm_content TEXT;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS utm_term TEXT;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS referrer TEXT;
CREATE INDEX IF NOT EXISTS idx_leads_utm ON leads(agency_id, utm_source, utm_campaign);
