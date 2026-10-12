-- migrations/069_land_area_nbsp.sql
-- 068 не заполнил ни одного объекта: Avito ставит между числом и «сот.»
-- неразрывный пробел (U+00A0), а \s в регулярках Postgres его не ловит.
-- Python-разбор (parse_title) его ловит, так что новые объявления были в порядке.

UPDATE properties
SET land_area_sotki = replace(substring(lower(title) FROM '(\d+(?:[.,]\d+)?)[\s ]*сот'), ',', '.')::REAL
WHERE land_area_sotki IS NULL
  AND lower(title) ~ '\d+(?:[.,]\d+)?[\s ]*сот';

UPDATE properties
SET land_area_sotki = replace(substring(lower(title) FROM '(\d+(?:[.,]\d+)?)[\s ]*га\M'), ',', '.')::REAL * 100
WHERE land_area_sotki IS NULL
  AND lower(title) ~ '\d+(?:[.,]\d+)?[\s ]*га\M';
