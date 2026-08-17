-- Убирает наследие переименования из миграции 055.
--
-- 043 создала agency_crm_config.crm_type TEXT NOT NULL. 055 переименовала поле
-- в connector_type: добавила новую колонку, перелила значения, поставила
-- умолчание и NOT NULL — но старую колонку оставила как есть, тоже NOT NULL и
-- без умолчания.
--
-- Модель (app/models/agency_crm_config.py) знает только connector_type, а
-- crm_type у неё — синоним на уровне Python. Значит в INSERT старая колонка не
-- попадает вовсе, база подставляет NULL и падает на NOT NULL. Именно это ломало
-- восемнадцать тестов в CI, начиная с 12 августа.
--
-- Данные уже перенесены (055 строка 30), читателей у старой колонки нет —
-- удаляем её вместе с уникальным ограничением, которое на неё опиралось.

ALTER TABLE agency_crm_config DROP CONSTRAINT IF EXISTS agency_crm_config_agency_id_crm_type_key;
ALTER TABLE agency_crm_config DROP COLUMN IF EXISTS crm_type;
