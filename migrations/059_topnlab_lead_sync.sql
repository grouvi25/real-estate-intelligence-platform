-- migrations/059_topnlab_lead_sync.sql
-- ТЗ «Интеграция с TopNLab CRM» v1.0, раздел 3.2: что уже ушло в TopNLab.
--
-- Реквизиты подключения (appkey, ID компании, виртуальный номер, флаг
-- синхронизации) лежат не в agencies, как предлагает раздел 3.1, а в уже
-- существующей agency_crm_config: там ключ шифруется, там же его задаёт владелец
-- в кабинете, и так требует дополнение Signal Bus §4.3. Вторая копия настроек
-- CRM в agencies разошлась бы с первой.
--
-- topnlab_client_id — insertedId заявки из importClient. Пока он пуст, лид в
-- TopNLab не отправлялся; повтор задачи по нему не создаст вторую заявку.

ALTER TABLE leads ADD COLUMN IF NOT EXISTS topnlab_client_id BIGINT;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS topnlab_synced_at TIMESTAMPTZ;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS topnlab_task_id BIGINT;
CREATE INDEX IF NOT EXISTS idx_leads_topnlab_client
    ON leads(agency_id, topnlab_client_id) WHERE topnlab_client_id IS NOT NULL;
