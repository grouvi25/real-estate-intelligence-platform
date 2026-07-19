-- migrations/002_geo_protection.sql
-- TZ section 28: geo protection with partner offers.
-- Additive ALTER on protected_geos (created in 001). protection_radius_km already
-- exists from 001, so only partner_agency_id + status are added.

ALTER TABLE protected_geos
    ADD COLUMN IF NOT EXISTS partner_agency_id UUID REFERENCES partner_agencies(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'active' CHECK (status IN ('active', 'inactive'));

CREATE INDEX IF NOT EXISTS idx_protected_geos_city ON protected_geos(city_name);
