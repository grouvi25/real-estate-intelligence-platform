-- migrations/044_signal_outcome_view.sql
-- Signal Bus addendum: end-to-end attribution view. Traces every signal through
-- its lead to the final deal outcome so the funnel and per-channel ROI can be
-- computed in one place.

CREATE OR REPLACE VIEW v_signal_to_outcome AS
SELECT
    s.id                AS signal_id,
    s.agency_id         AS agency_id,
    s.origin_system     AS origin_system,
    s.segment           AS segment,
    s.intent_score      AS intent_score,
    s.status            AS signal_status,
    s.reply_status      AS reply_status,
    s.created_at        AS signal_created_at,
    l.id                AS lead_id,
    l.status            AS lead_status,
    l.utm_source        AS utm_source,
    d.id                AS deal_outcome_id,
    d.outcome           AS outcome,
    d.commission_amount AS commission_amount,
    d.deal_closed_at    AS deal_closed_at
FROM signals s
LEFT JOIN leads l ON l.source_signal_id = s.id
LEFT JOIN deal_outcomes d ON d.lead_id = l.id;
