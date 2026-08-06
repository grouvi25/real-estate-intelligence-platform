-- migrations/046_lead_escalation_stage.sql
-- TZ 32.3 escalation fired on a one-hour window: `4 <= hrs < 5`, `24 <= hrs < 25`,
-- `48 <= hrs < 49`, evaluated by an hourly task. Miss one run -- a deploy, a
-- worker restart, a slow queue -- and that lead's reminder is lost for good,
-- silently. Run twice inside the window and the manager is pinged twice.
--
-- Recording the highest stage already actioned makes the task idempotent and
-- catch-up safe: a lead overdue by 30 hours after a missed run still gets its
-- 24h escalation on the next pass.

ALTER TABLE leads ADD COLUMN IF NOT EXISTS escalation_stage SMALLINT DEFAULT 0;

-- Leads that already carry an escalation task are at stage 48; without this they
-- would be escalated a second time on the first run after deploy.
UPDATE leads SET escalation_stage = 48
WHERE escalation_stage = 0
  AND id IN (SELECT lead_id FROM tasks WHERE task_type = 'escalation' AND lead_id IS NOT NULL);

CREATE INDEX IF NOT EXISTS idx_leads_escalation
    ON leads(escalation_stage) WHERE status IN ('new', 'in_progress');
