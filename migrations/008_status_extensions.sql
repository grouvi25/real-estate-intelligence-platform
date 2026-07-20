-- migrations/008_status_extensions.sql
-- TZ section 32 introduces two new lifecycle states that the original CHECK
-- constraints (migration 001) don't allow yet:
--   * sources: 'dead' (set by check_dead_sources)
--   * lead_property_matches: 'presented' and 'accepted' (manager feedback)
-- Recreate the constraints with the extended value sets.

ALTER TABLE sources DROP CONSTRAINT IF EXISTS sources_status_check;
ALTER TABLE sources ADD CONSTRAINT sources_status_check
    CHECK (status IN ('sandbox', 'active', 'paused', 'blocked', 'dead'));

ALTER TABLE lead_property_matches DROP CONSTRAINT IF EXISTS lead_property_matches_status_check;
ALTER TABLE lead_property_matches ADD CONSTRAINT lead_property_matches_status_check
    CHECK (status IN ('suggested', 'sent', 'viewed', 'interested', 'rejected', 'presented', 'accepted'));
