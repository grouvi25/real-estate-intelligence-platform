-- migrations/061_avito_sync.sql
-- ТЗ «Avito + фильтрация сигналов» v1, блок 1 (в ТЗ — 057, номер занят).
--
-- Ссылка на объявление хранится в уже существующем properties.source_url
-- (импорт каталога уже сверяет по нему), отдельный avito_url не нужен.
-- Таблица avito_tokens из ТЗ не заводится: токен живёт сутки, а синхронизация
-- раз в час спокойно получает новый.
-- avito_id уникален в пределах агентства: одно объявление могут выгрузить два
-- агентства-партнёра, глобальная уникальность, как в ТЗ, сломала бы второе.

ALTER TABLE properties ADD COLUMN IF NOT EXISTS avito_id BIGINT;
ALTER TABLE properties ADD COLUMN IF NOT EXISTS avito_status TEXT;
ALTER TABLE properties ADD COLUMN IF NOT EXISTS avito_synced_at TIMESTAMPTZ;
ALTER TABLE properties ADD COLUMN IF NOT EXISTS source_system TEXT NOT NULL DEFAULT 'manual';
CREATE UNIQUE INDEX IF NOT EXISTS idx_properties_agency_avito
    ON properties(agency_id, avito_id) WHERE avito_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_properties_source ON properties(agency_id, source_system);
