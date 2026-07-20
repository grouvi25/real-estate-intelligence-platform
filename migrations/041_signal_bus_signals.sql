-- migrations/041_signal_bus_signals.sql
-- Signal Bus addendum: signals gain an origin system, a link to their content
-- unit, and a reply workflow (draft -> pending -> sent) so managers can respond
-- to a signal on the channel it came from, all tracked here.

ALTER TABLE signals ADD COLUMN IF NOT EXISTS origin_system TEXT;
ALTER TABLE signals ADD COLUMN IF NOT EXISTS content_unit_id UUID
    REFERENCES content_units(id) ON DELETE SET NULL;
ALTER TABLE signals ADD COLUMN IF NOT EXISTS reply_channel TEXT;
ALTER TABLE signals ADD COLUMN IF NOT EXISTS reply_status TEXT NOT NULL DEFAULT 'none';
ALTER TABLE signals ADD COLUMN IF NOT EXISTS reply_draft TEXT;
ALTER TABLE signals ADD COLUMN IF NOT EXISTS replied_by_manager_id UUID
    REFERENCES managers(id) ON DELETE SET NULL;
ALTER TABLE signals ADD COLUMN IF NOT EXISTS replied_at TIMESTAMPTZ;

ALTER TABLE signals DROP CONSTRAINT IF EXISTS signals_reply_status_check;
ALTER TABLE signals ADD CONSTRAINT signals_reply_status_check
    CHECK (reply_status IN ('none', 'draft', 'pending', 'sent', 'failed', 'skipped'));

CREATE INDEX IF NOT EXISTS idx_signals_reply_status
    ON signals(agency_id, reply_status) WHERE reply_status <> 'none';
