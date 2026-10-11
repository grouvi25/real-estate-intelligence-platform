-- migrations/065_sources_discovery_fields.sql
-- ТЗ «Сигналы» v1.0, апгрейд A: откуда источник и жив ли он.
--
-- health_status: healthy | degraded (читается, но давно молчит) | dead (не
-- читается) | unknown. Три неудачи подряд — status = 'disabled': сборщик такой
-- источник не опрашивает, но строка и её история остаются.

ALTER TABLE sources ADD COLUMN IF NOT EXISTS discovered_by TEXT;
ALTER TABLE sources ADD COLUMN IF NOT EXISTS sandbox_score DOUBLE PRECISION;
ALTER TABLE sources ADD COLUMN IF NOT EXISTS last_health_check TIMESTAMPTZ;
ALTER TABLE sources ADD COLUMN IF NOT EXISTS health_status TEXT NOT NULL DEFAULT 'unknown';
ALTER TABLE sources ADD COLUMN IF NOT EXISTS consecutive_failures INTEGER NOT NULL DEFAULT 0;
ALTER TABLE sources ADD COLUMN IF NOT EXISTS last_post_at TIMESTAMPTZ;

ALTER TABLE sources DROP CONSTRAINT IF EXISTS sources_health_status_check;
ALTER TABLE sources ADD CONSTRAINT sources_health_status_check
    CHECK (health_status IN ('unknown', 'healthy', 'degraded', 'dead'));

ALTER TABLE sources DROP CONSTRAINT IF EXISTS sources_status_check;
ALTER TABLE sources ADD CONSTRAINT sources_status_check
    CHECK (status IN ('sandbox', 'active', 'paused', 'blocked', 'dead', 'disabled'));

-- Источники, найденные старым еженедельным поиском, — тоже находки автопоиска.
UPDATE sources SET discovered_by = CASE WHEN auto_found THEN 'discovery' ELSE 'manual' END
 WHERE discovered_by IS NULL;
