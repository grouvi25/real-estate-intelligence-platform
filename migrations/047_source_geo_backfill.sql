-- migrations/047_source_geo_backfill.sql
-- A source with no geo_location_id is inert, not merely incomplete. Both
-- collectors read the geo's keywords to pre-filter what they collect
-- (quick_filter), an empty keyword set fails the city check, and every message
-- read from that source is discarded. The source sits on the Источники screen
-- showing "в работе" and produces nothing, for ever, with no error anywhere.
--
-- The add-source form never asked for a city, so every hand-added source landed
-- that way. Rows already stored are repaired here when the answer is
-- unambiguous: the agency has exactly one city.

UPDATE sources s
SET geo_location_id = g.id
FROM geo_locations g
WHERE s.geo_location_id IS NULL
  AND g.agency_id = s.agency_id
  AND (SELECT COUNT(*) FROM geo_locations gg WHERE gg.agency_id = s.agency_id) = 1;
