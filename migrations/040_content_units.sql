-- migrations/040_content_units.sql
-- Signal Bus addendum: a content_unit is one piece of source content (a post,
-- listing, comment or message) from a channel. Signals reference the content
-- unit they were extracted from, so the same post can yield several signals and
-- we can dedup by (channel, external_id).

CREATE TABLE IF NOT EXISTS content_units (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agency_id UUID NOT NULL REFERENCES agencies(id) ON DELETE CASCADE,
    source_id UUID REFERENCES sources(id) ON DELETE SET NULL,
    channel TEXT NOT NULL,              -- avito / cian / telegram / max / vk
    external_id TEXT,                   -- id of the post/listing on the platform
    url TEXT,
    content_type TEXT,                  -- post / comment / listing / message
    raw_content TEXT,
    author_hash TEXT,
    author_display_name TEXT,
    published_at TIMESTAMPTZ,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (agency_id, channel, external_id)
);
CREATE INDEX IF NOT EXISTS idx_content_units_agency_channel
    ON content_units(agency_id, channel);
