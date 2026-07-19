-- migrations/003_lead_dedup.sql
-- Blind index for phone dedup. Fernet ciphertext is non-deterministic and cannot
-- be queried; phone_hash is a deterministic HMAC of the normalized phone used only
-- for duplicate lookups (the phone itself stays encrypted in phone_encrypted).

ALTER TABLE leads ADD COLUMN IF NOT EXISTS phone_hash TEXT;
CREATE INDEX IF NOT EXISTS idx_leads_phone_hash ON leads(agency_id, phone_hash);
