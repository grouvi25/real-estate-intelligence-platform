-- migrations/009_task_escalation.sql
-- TZ section 32.3: escalate_overdue_leads creates an 'escalation' task, which the
-- original tasks.task_type CHECK (migration 001) does not allow yet. Extend it.

ALTER TABLE tasks DROP CONSTRAINT IF EXISTS tasks_task_type_check;
ALTER TABLE tasks ADD CONSTRAINT tasks_task_type_check CHECK (task_type IN (
    'contact', 'follow_up', 'showing', 'call_back', 'referral_confirmation',
    'alternative_sell', 'alternative_buy', 'escalation'
));
