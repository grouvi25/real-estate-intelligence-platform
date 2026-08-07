-- migrations/050_signal_bus_conformance.sql
-- Bringing the Signal Bus addendum's own acceptance items to what it specifies.
--
-- 1. origin_system held the PLATFORM ('telegram', 'vk') where the addendum
--    (§2.1) defines it as the SYSTEM a signal came from: 'reip_scouting' |
--    'content_engine' | 'direct_inbound'. Everything already collected therefore
--    looked like several different systems, and once the Content Engine lands
--    there would have been no way to tell its signals from our own scouting.
--    The platform is not lost: it is what reply_channel is for, and both
--    collectors already set it.
--
-- 2. v_signal_to_outcome (§2.4) was missing the content_units join, so the
--    example query the addendum itself gives -- revenue by content topic --
--    could not run at all. It was also missing reply_channel and crm_deal_id.

UPDATE signals
SET reply_channel = COALESCE(reply_channel, origin_system)
WHERE origin_system IN ('telegram', 'vk', 'max', 'avito', 'cian');

UPDATE signals
SET origin_system = 'reip_scouting'
WHERE origin_system IS NULL
   OR origin_system NOT IN ('reip_scouting', 'content_engine', 'direct_inbound');

-- CREATE OR REPLACE cannot reorder or rename a view's columns; the new shape
-- adds reply_channel in the middle, so the old view has to go first.
DROP VIEW IF EXISTS v_signal_to_outcome;

CREATE VIEW v_signal_to_outcome AS
SELECT
    s.id                AS signal_id,
    s.agency_id         AS agency_id,
    s.origin_system     AS origin_system,
    s.reply_channel     AS reply_channel,
    s.reply_status      AS reply_status,
    s.segment           AS segment,
    s.intent_score      AS intent_score,
    s.status            AS signal_status,
    s.created_at        AS signal_created_at,
    cu.id               AS content_unit_id,
    cu.metadata ->> 'topic_tag'  AS topic_tag,
    cu.raw_content      AS content_title,
    cu.channel          AS content_platform,
    l.id                AS lead_id,
    l.status            AS lead_status,
    l.utm_source        AS utm_source,
    l.crm_deal_id       AS crm_deal_id,
    d.id                AS deal_outcome_id,
    d.outcome           AS outcome,
    d.deal_amount       AS deal_value,
    d.commission_amount AS commission_amount,
    d.deal_closed_at    AS deal_closed_at
FROM signals s
LEFT JOIN content_units cu ON cu.id = s.content_unit_id
LEFT JOIN leads l          ON l.source_signal_id = s.id
LEFT JOIN deal_outcomes d  ON d.lead_id = l.id;
