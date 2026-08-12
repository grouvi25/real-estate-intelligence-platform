# REIP Railway Proxy

Минимальный внешний прокси для OpenAI и Anthropic. Backend отправляет только обезличенные промпты.

## Деплой

1. Создайте сервис в Railway из директории `railway_proxy`.
2. Задайте `PROXY_SECRET`, случайную строку длиной минимум 32 символа.
3. Откройте Railway-generated domain и сохраните URL.
4. Проверьте `GET https://<service>/health`, ответ должен быть `{"status":"ok"}`.

## REIP backend

```env
RAILWAY_PROXY_URL=https://<service>.up.railway.app
RAILWAY_PROXY_SECRET=<то же значение, что PROXY_SECRET>
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
```

OpenAI идёт на `/v1/chat/completions`, Anthropic на `/anthropic/v1/messages`. Все provider-запросы требуют `X-Proxy-Secret`; `/health` намеренно публичный для health checks.

## Локальная проверка

```bash
npm install
PROXY_SECRET=$(openssl rand -hex 32) npm start
curl http://localhost:3000/health
curl -i http://localhost:3000/v1/models
```

Второй запрос без секрета обязан вернуть `403`.
