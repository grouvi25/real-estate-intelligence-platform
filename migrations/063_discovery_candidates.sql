-- migrations/063_discovery_candidates.sql
-- ТЗ «Сигналы» v1.0, апгрейд A, раздел 3: кандидаты автопоиска и журнал запусков.
--
-- Отличия от ТЗ, все из-за реальной схемы:
-- * ключи — UUID: agencies.id у нас UUID, а не BIGINT;
-- * у кандидата есть geo_location_id: поиск идёт по городу агентства, и
--   источник, созданный из кандидата, должен попасть в тот же город, иначе
--   сборщик не знает, по каким словам его фильтровать;
-- * source_id — источник, созданный из кандидата (ACTIVATE/SANDBOX или ручная
--   активация), чтобы кабинет показывал, во что превратилась находка.
-- Уже проверенный кандидат не тестируется заново каждый час: UNIQUE по
-- (agency_id, platform, external_id) и retry_after для песочницы.

CREATE TABLE IF NOT EXISTS discovery_candidates (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agency_id        UUID NOT NULL REFERENCES agencies(id) ON DELETE CASCADE,
    geo_location_id  UUID REFERENCES geo_locations(id) ON DELETE SET NULL,
    platform         TEXT NOT NULL,
    external_id      TEXT NOT NULL,
    name             TEXT,
    url              TEXT,
    rank_score       DOUBLE PRECISION,
    sandbox_score    DOUBLE PRECISION,
    verdict          TEXT CHECK (verdict IN ('ACTIVATE', 'SANDBOX', 'REJECT')),
    is_alive         BOOLEAN,
    decided_by       TEXT NOT NULL DEFAULT 'discovery' CHECK (decided_by IN ('discovery', 'manager')),
    source_id        UUID REFERENCES sources(id) ON DELETE SET NULL,
    discovered_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    tested_at        TIMESTAMPTZ,
    retry_after      TIMESTAMPTZ,
    raw_meta         JSONB NOT NULL DEFAULT '{}',
    UNIQUE (agency_id, platform, external_id)
);

CREATE INDEX IF NOT EXISTS idx_discovery_candidates_retry
    ON discovery_candidates (agency_id, verdict, retry_after);

CREATE TABLE IF NOT EXISTS discovery_log (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agency_id        UUID REFERENCES agencies(id) ON DELETE CASCADE,
    geo_location_id  UUID REFERENCES geo_locations(id) ON DELETE SET NULL,
    run_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    city             TEXT,
    found            INTEGER NOT NULL DEFAULT 0,
    passed_dup       INTEGER NOT NULL DEFAULT 0,
    tested           INTEGER NOT NULL DEFAULT 0,
    activated        INTEGER NOT NULL DEFAULT 0,
    sandboxed        INTEGER NOT NULL DEFAULT 0,
    rejected         INTEGER NOT NULL DEFAULT 0,
    by_platform      JSONB NOT NULL DEFAULT '{}',
    errors           JSONB NOT NULL DEFAULT '{}',
    duration_s       DOUBLE PRECISION
);

CREATE INDEX IF NOT EXISTS idx_discovery_log_agency_run ON discovery_log (agency_id, run_at DESC);
