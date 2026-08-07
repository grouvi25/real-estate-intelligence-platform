-- migrations/053_property_price_watch.sql
-- TZ 11.1 keeps price-change-rematch on a schedule; the implementation fires it
-- from the PATCH endpoint instead, which is better -- instant, and no pointless
-- sweeps -- but only covers price changes that come through the API. A price
-- edited by the catalogue import, by a CRM sync or straight in the database
-- silently skips the re-match, and the buyer whose budget the flat has just
-- dropped into never hears about it.
--
-- Remembering the price we last matched on is enough to notice those.

ALTER TABLE properties ADD COLUMN IF NOT EXISTS last_rematch_price INTEGER;

-- Existing rows start from where they are: only changes from now on count.
UPDATE properties SET last_rematch_price = price WHERE last_rematch_price IS NULL;
