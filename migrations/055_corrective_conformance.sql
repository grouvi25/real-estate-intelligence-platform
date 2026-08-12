-- Corrective conformance for the three approved REIP specifications.

UPDATE signals SET origin_system = 'reip_scouting' WHERE origin_system IS NULL;
ALTER TABLE signals ALTER COLUMN origin_system SET DEFAULT 'reip_scouting';
ALTER TABLE signals ALTER COLUMN origin_system SET NOT NULL;

ALTER TABLE signals DROP CONSTRAINT IF EXISTS signals_reply_status_check;
UPDATE signals SET reply_status = 'replied' WHERE reply_status = 'sent';
UPDATE signals SET reply_status = 'pending' WHERE reply_status IN ('none','draft','failed','skipped') OR reply_status IS NULL;
ALTER TABLE signals ALTER COLUMN reply_status SET DEFAULT 'pending';
ALTER TABLE signals ADD CONSTRAINT signals_reply_status_check
  CHECK (reply_status IN ('pending','replied','escalated','dismissed'));

UPDATE signals SET reply_channel = CASE reply_channel
  WHEN 'telegram' THEN 'tg_bot' WHEN 'max' THEN 'max_bot'
  WHEN 'vk' THEN 'vk_api' WHEN 'avito' THEN 'avito_api'
  WHEN 'cian' THEN 'cian_api' ELSE reply_channel END;

ALTER TABLE content_units ADD COLUMN IF NOT EXISTS title TEXT;
ALTER TABLE content_units ADD COLUMN IF NOT EXISTS topic_tag TEXT;
ALTER TABLE content_units ADD COLUMN IF NOT EXISTS platform TEXT;
ALTER TABLE content_units ADD COLUMN IF NOT EXISTS external_post_url TEXT;
UPDATE content_units SET title = COALESCE(title, NULLIF(left(raw_content, 200), ''), '??? ????????');
UPDATE content_units SET topic_tag = COALESCE(topic_tag, metadata ->> 'topic_tag');
UPDATE content_units SET platform = COALESCE(platform, channel);
UPDATE content_units SET external_post_url = COALESCE(external_post_url, url);
ALTER TABLE content_units ALTER COLUMN title SET NOT NULL;

ALTER TABLE agency_crm_config ADD COLUMN IF NOT EXISTS connector_type TEXT;
UPDATE agency_crm_config SET connector_type = COALESCE(connector_type, crm_type, 'generic_webhook');
ALTER TABLE agency_crm_config ALTER COLUMN connector_type SET DEFAULT 'generic_webhook';
ALTER TABLE agency_crm_config ALTER COLUMN connector_type SET NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_agency_crm_connector ON agency_crm_config(agency_id, connector_type);

DROP VIEW IF EXISTS v_signal_to_outcome;
CREATE VIEW v_signal_to_outcome AS
SELECT s.id signal_id, s.agency_id, s.origin_system, s.reply_channel, s.reply_status,
       s.segment, s.intent_score, s.status signal_status, s.created_at signal_created_at,
       cu.id content_unit_id, cu.topic_tag, cu.title content_title, cu.platform content_platform,
       l.id lead_id, l.status lead_status, l.utm_source, l.crm_deal_id,
       d.id deal_outcome_id, d.outcome, d.deal_amount deal_value,
       d.commission_amount, d.deal_closed_at
FROM signals s
LEFT JOIN content_units cu ON cu.id=s.content_unit_id
LEFT JOIN leads l ON l.source_signal_id=s.id
LEFT JOIN deal_outcomes d ON d.lead_id=l.id;
