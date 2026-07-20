-- migrations/005_match_feedback.sql
-- TZ section 32: match feedback loop. When a manager rejects a suggested match we
-- record why (free text + a category) and add a hard exclusion so the matching
-- engine never re-suggests that property to that lead.

ALTER TABLE lead_property_matches ADD COLUMN IF NOT EXISTS rejection_reason TEXT;
ALTER TABLE lead_property_matches ADD COLUMN IF NOT EXISTS rejection_category TEXT;
ALTER TABLE lead_property_matches ADD COLUMN IF NOT EXISTS feedback_given_at TIMESTAMPTZ;

CREATE TABLE IF NOT EXISTS match_exclusions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agency_id UUID NOT NULL REFERENCES agencies(id) ON DELETE CASCADE,
    lead_id UUID NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
    property_id UUID NOT NULL REFERENCES properties(id) ON DELETE CASCADE,
    category TEXT,
    reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (lead_id, property_id)
);
CREATE INDEX IF NOT EXISTS idx_match_exclusions_lead ON match_exclusions(lead_id);
