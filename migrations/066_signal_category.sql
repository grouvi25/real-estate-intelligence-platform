-- migrations/066_signal_category.sql
-- ТЗ «Сигналы» v1.0, апгрейд B: категория сигнала и фильтр по ней.
--
-- Категория считается по словам, без ИИ (app/services/signal_classifier.py).
-- Уже собранные сигналы размечаются здесь теми же словами, кроме конкурентов:
-- их имена хранятся в настройках агентства, и такие сигналы разметит следующий
-- сбор или ручная правка.
--
-- Аренда как категория есть, но аренда по-прежнему отсекается до создания
-- сигнала (ТЗ «Фильтрация сигналов»), так что в «Аренде» окажутся только
-- сообщения, где покупка и съём перемешаны, — и это честно.

ALTER TABLE signals ADD COLUMN IF NOT EXISTS signal_category TEXT NOT NULL DEFAULT 'other';
ALTER TABLE signals DROP CONSTRAINT IF EXISTS signals_signal_category_check;
ALTER TABLE signals ADD CONSTRAINT signals_signal_category_check
    CHECK (signal_category IN ('purchase', 'rental', 'news', 'competitor', 'other'));

CREATE INDEX IF NOT EXISTS idx_signals_agency_category_created
    ON signals (agency_id, signal_category, created_at DESC);

CREATE TABLE IF NOT EXISTS agency_signal_filters (
    agency_id     UUID PRIMARY KEY REFERENCES agencies(id) ON DELETE CASCADE,
    enabled_cats  TEXT[] NOT NULL DEFAULT ARRAY['purchase', 'rental', 'news', 'competitor', 'other'],
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

UPDATE signals SET signal_category = CASE
    WHEN lower(raw_text) ~ '(куп|продаж|ипотек|взнос|рассрочк|новостройк|ищу квартир|ищу дом|ищу участ|присматрива|рассматрива|подобрать|подберите)' THEN 'purchase'
    WHEN lower(raw_text) ~ '(аренд|сдам|сдаю|сниму|снять|посуточно)' THEN 'rental'
    WHEN lower(raw_text) ~ '(закон|ставк|цб рф|льготн|субсиди|новост)' THEN 'news'
    ELSE 'other' END
 WHERE signal_category = 'other';
