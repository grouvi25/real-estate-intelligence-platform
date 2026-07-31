-- Repost dedup for signals (see app/services/intent_scoring.content_fingerprint).
-- Agencies repost the same listing verbatim with a new message id each time, so
-- content_unit dedup alone let one advert into the queue five times.
ALTER TABLE signals ADD COLUMN IF NOT EXISTS content_fingerprint TEXT;
CREATE INDEX IF NOT EXISTS idx_signals_fingerprint
    ON signals(agency_id, content_fingerprint)
    WHERE content_fingerprint IS NOT NULL
