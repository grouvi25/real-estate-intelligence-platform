-- migrations/052_signal_triage_statuses.sql
-- The addendum (§5.2) defines four states for a signal in the triage queue:
--
--     pending    новый сигнал, ждёт реакции специалиста
--     replied    ответ отправлен через соответствующий канал
--     escalated  передан старшему менеджеру
--     dismissed  признан нерелевантным
--
-- The implementation had six of its own — none / draft / pending / sent /
-- failed / skipped — with no escalated and no dismissed. The two missing ones
-- are not labels, they are the only ways a signal can leave the queue without
-- being answered: a manager could neither drop an irrelevant signal nor hand a
-- hard one upward, so the queue only ever grew.
--
-- The delivery states earn their keep (a failed send is not an unanswered
-- signal), so they stay alongside the addendum's four rather than being
-- replaced by them; 'sent' and 'replied' are the same state under two names, so
-- the stored value moves to the addendum's word.

-- Order matters: the old CHECK does not allow 'replied', so rewriting the value
-- before dropping it fails the whole migration.
ALTER TABLE signals DROP CONSTRAINT IF EXISTS signals_reply_status_check;

UPDATE signals SET reply_status = 'replied' WHERE reply_status = 'sent';

ALTER TABLE signals ADD CONSTRAINT signals_reply_status_check
    CHECK (reply_status IN (
        -- addendum §5.2
        'pending', 'replied', 'escalated', 'dismissed',
        -- delivery detail the addendum does not model but the manager needs
        'none', 'draft', 'failed', 'skipped'
    ));

-- Escalation and dismissal need to be attributable afterwards.
ALTER TABLE signals ADD COLUMN IF NOT EXISTS triage_reason TEXT;
ALTER TABLE signals ADD COLUMN IF NOT EXISTS triaged_by_manager_id UUID
    REFERENCES managers(id) ON DELETE SET NULL;
ALTER TABLE signals ADD COLUMN IF NOT EXISTS triaged_at TIMESTAMPTZ;
