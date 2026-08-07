-- migrations/051_pd_erasure.sql
-- 152-ФЗ §21: the subject may withdraw consent, and the operator must then stop
-- processing and destroy their personal data. Consent was recorded from the
-- start; erasure had no implementation and no trace — see
-- app/services/consent_manager.py.
--
-- The mark is on the lead rather than a deletion because the row is also the
-- agency's own accounting: which source it came from, how the deal ended, what
-- it earned. None of that identifies anybody once the name, phone, email and
-- the raw message are gone.

ALTER TABLE leads ADD COLUMN IF NOT EXISTS pd_erased_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_leads_pd_erased ON leads(pd_erased_at)
    WHERE pd_erased_at IS NOT NULL;
