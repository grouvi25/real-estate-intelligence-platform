# Финальный чек-лист приёмки MVP → PROD (ТЗ раздел 26)

Статусы: ✅ готово · ⚙️ частично · ⏳ впереди

## 🟢 Инфраструктура и безопасность
- ✅ Docker Compose поднимается без ошибок (dev-стенд через CD; отдельный prod-профиль — ⏳)
- ⏳ SSL-сертификат + редирект HTTP→HTTPS (стенд на `:8000`; nginx+TLS впереди)
- ✅ Все секреты в `.env`, в коде нет токенов/ключей
- ✅ `ENCRYPTION_KEY` валиден; ПД в БД читаются только через hybrid-свойства (Fernet)
- ✅ `.gitignore` блокирует `.env`, `*.key`, `secrets/`

## 🔵 Ядро и API
- ✅ `POST /api/auth/platform` принимает initData TG/MAX, выдаёт JWT (WebApp-HMAC)
- ⚙️ Мульти-гео: город → генерация keywords (Celery) → discovery (поиск источников — заглушка до Telethon-коллектора)
- ✅ `POST /api/signals/{id}/create-lead` фиксирует согласие 152-ФЗ (IP, UA, текст, версия)
- ✅ Лид-магниты `/api/lm/...` без авторизации, требуют чекбокс согласия (иначе 400)
- ✅ Matching engine по весам ТЗ (бюджет +30, сегмент +25, локация +20, приоритеты +15, hot +10)

## 🟣 AI и автоматизация
- ✅ Двухступенчатый intent scoring (quick_filter → AI)
- ⚙️ AI-провайдеры переключаются через `config.ai_default_provider` (без перезапуска — через админку — ⏳)
- ✅ PII anonymizer удаляет телефоны/имена перед OpenAI/Anthropic
- ✅ Логирование AI-стоимости (module, provider, tokens, cost_rub) в JSON-логи
- ✅ При превышении дневного бюджета — `429 AI_BUDGET_EXCEEDED`; мягкий алерт на 90%

## 🟠 Партнёры и Knowledge Moat
- ✅ `POST /api/referrals` создаёт запись, шлёт уведомление партнёру, ставит задачу подтверждения
- ✅ Celery `check_referral_expiry` помечает просроченные (>expiry) как `expired`
- ✅ Альтернативщик: 2 задачи + матчинг по `target_purchase_budget`
- ✅ Вс 03:00 `update_knowledge_moat`: Source ROI + веса в `agency.settings`

## 🟡 Деплой и мониторинг
- ⏳ Mini App статика по `https://domain/mini-app/` (файлы есть; отдача через nginx — впереди)
- ✅ `/api/health/deep` возвращает статус DB, Redis, AI (с таймаутами)
- ⏳ Nginx reverse-proxy `/api/` и `/webhooks/` (стенд напрямую `:8000`)
- ✅ Structlog пишет JSON
- ⚙️ Алерт на AI-бюджет >90% ✅; алерт на очередь Celery >50 — ⏳

## 🔴 Go-Live
- ⚙️ Сквозной поток менеджера: API готово (сигнал → лид → питч → задача); экраны Mini App — ⏳
- ⏳ Ежедневный отчёт руководителю 07:30 (`report_generator` — впереди)
- ⏳ Нагрузочный тест 50 RPS
- ✅ `README.md` актуален; онбординг агентства через `PLATFORM_OWNER_AGENCY_ID`

---

**Инженерное качество:** каждый модуль покрыт автотестами (~147), CI прогоняет `ruff` + `pytest` (Postgres + Redis) + синтаксис Mini App JS; CD автоматически деплоит на VPS при зелёных тестах. Все известные дефекты иллюстративного ТЗ исправлены и задокументированы в истории коммитов.
