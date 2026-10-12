-- migrations/068_land_area.sql
-- Площадь участка в сотках: Avito пишет её в заголовке («Участок 6 сот. (ИЖС)»,
-- «Дом 120 м² на участке 6 сот.»), а у объекта была только площадь в м².
-- Уже загруженные объекты заполняются из заголовка; гектары переводятся в сотки.

ALTER TABLE properties ADD COLUMN IF NOT EXISTS land_area_sotki REAL;

UPDATE properties
SET land_area_sotki = replace(substring(lower(title) FROM '(\d+(?:[.,]\d+)?)\s*сот'), ',', '.')::REAL
WHERE land_area_sotki IS NULL
  AND lower(title) ~ '\d+(?:[.,]\d+)?\s*сот';

UPDATE properties
SET land_area_sotki = replace(substring(lower(title) FROM '(\d+(?:[.,]\d+)?)\s*га\M'), ',', '.')::REAL * 100
WHERE land_area_sotki IS NULL
  AND lower(title) ~ '\d+(?:[.,]\d+)?\s*га\M';
