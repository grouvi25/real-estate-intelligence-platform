-- migrations/004_task_urgency.sql
-- TZ section 32: SLA escalation. Overdue leads get an urgent, escalated task so
-- managers don't let hot leads go cold. escalate_overdue_leads (Celery) flips
-- is_urgent and stamps escalated_at.

ALTER TABLE tasks ADD COLUMN IF NOT EXISTS is_urgent BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS escalated_at TIMESTAMPTZ;
CREATE INDEX IF NOT EXISTS idx_tasks_urgent ON tasks(agency_id, is_urgent) WHERE is_urgent;
