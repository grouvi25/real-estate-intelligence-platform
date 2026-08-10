-- Coordinates for a property, so the card can put it on a map.
--
-- The catalogue stores a postal address and nothing else, and Yandex charges per
-- geocoding request. Looking the address up on every open would spend the daily
-- quota on the same twenty flats; found once and kept, it costs one request per
-- property for its lifetime.
--
-- geocoded_at also records a failure: an address the geocoder cannot resolve is
-- worth remembering, or every open retries it for ever.

ALTER TABLE properties ADD COLUMN IF NOT EXISTS lat DOUBLE PRECISION;
ALTER TABLE properties ADD COLUMN IF NOT EXISTS lon DOUBLE PRECISION;
ALTER TABLE properties ADD COLUMN IF NOT EXISTS geocoded_at TIMESTAMPTZ;
