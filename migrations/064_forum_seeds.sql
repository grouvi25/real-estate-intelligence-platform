-- migrations/064_forum_seeds.sql
-- ТЗ «Сигналы» v1.0, апгрейд A: региональные форумы, которые администратор
-- платформы заносит вручную. Поисковик форумов (searchers/forums.py) ищет на
-- них ленты RSS и предлагает их кандидатами; robots.txt соблюдается.

CREATE TABLE IF NOT EXISTS discovery_forum_seeds (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    city         TEXT NOT NULL,
    domain       TEXT NOT NULL UNIQUE,
    description  TEXT,
    active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
