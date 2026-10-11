"""DemoModeMiddleware. ТЗ «Сигналы» v1.0, раздел 7.3.

A request carrying X-Demo-Token is answered here and never reaches a router:

* GET of a path the demo covers (signals, leads, analytics, dashboard) -> the
  synthetic dataset from Redis;
* GET/PATCH /api/demo/session -> the session itself (PATCH switches the city);
* anything else -> 403 {"error": "demo_restricted"}.

The ТЗ lists blocked paths and lets the rest through to handlers that check
request.state.is_demo. That is a deny-list: every endpoint added later would be
open to a demo visitor until somebody remembered to check the flag. Here it is
the other way round -- only the paths the demo knows are answered, and no
handler, and so no database, ever sees a demo request.
"""
from __future__ import annotations

import json

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

logger = structlog.get_logger()

HEADER = "x-demo-token"
DEMO_HEADERS = {"X-Demo": "1", "Cache-Control": "no-store"}


def _restricted() -> JSONResponse:
    return JSONResponse({"error": "demo_restricted", "code": "DEMO_RESTRICTED",
                         "message": "Недоступно в демо-режиме — доступно после подключения"},
                        status_code=403, headers=DEMO_HEADERS)


class DemoModeMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        token = request.headers.get(HEADER)
        # The request form writes an onboarding request and reads nothing; it is
        # the one demo action that goes on to a real handler.
        path = request.url.path
        if not token or not path.startswith("/api/") or path.rstrip("/") == "/api/demo/request":
            return await call_next(request)

        from app.services.demo import session as demo  # noqa: PLC0415
        from app.services.demo.generator import DEMO_CITIES, respond  # noqa: PLC0415

        redis = demo.redis_client()
        try:
            cfg = await demo.get_config(redis)
            if not cfg.get("enabled"):
                return JSONResponse({"error": "demo_disabled", "code": "DEMO_DISABLED",
                                     "message": "Демо-режим сейчас выключен"},
                                    status_code=403, headers=DEMO_HEADERS)
            sess = await demo.read_session(redis, token)
            if sess is None:
                return JSONResponse({"error": "demo_expired", "code": "DEMO_EXPIRED",
                                     "message": "Демо-сессия закончилась — откройте демо заново"},
                                    status_code=401, headers=DEMO_HEADERS)
            path = request.url.path.rstrip("/") or "/"
            request.state.is_demo = True
            request.state.demo_city = sess["city"]

            if path == "/api/demo/session":
                if request.method == "PATCH":
                    try:
                        body = json.loads(await request.body() or b"{}")
                    except ValueError:
                        body = {}
                    sess = await demo.set_city(redis, token, str(body.get("city") or ""))
                    if sess is None:
                        return JSONResponse({"error": "Такого города в демо нет", "code": "DEMO_CITY"},
                                            status_code=400, headers=DEMO_HEADERS)
                elif request.method != "GET":
                    return _restricted()
                return JSONResponse({"city": sess["city"], "cities": DEMO_CITIES,
                                     "allowed_tabs": cfg["allowed_tabs"],
                                     "headline": cfg["headline"]}, headers=DEMO_HEADERS)

            if request.method != "GET":
                return _restricted()
            tabs = _tabs_of(path)
            if tabs and not tabs & set(cfg["allowed_tabs"]):
                return _restricted()
            data = await demo.get_data(redis, sess["city"])
            body = respond(data, path, dict(request.query_params), sess["city"])
            if body is None:
                return _restricted()
            if body.get("__demo_not_found__"):
                return JSONResponse({"error": "Не найдено — в этом городе такой записи нет",
                                     "code": "NOT_FOUND"}, status_code=404, headers=DEMO_HEADERS)
            return JSONResponse(body, headers=DEMO_HEADERS)
        except Exception as e:  # noqa: BLE001 - never fall through to a real handler
            logger.warning("Demo request failed", path=request.url.path, error=str(e)[:160])
            return JSONResponse({"error": "Демо временно недоступно", "code": "DEMO_UNAVAILABLE"},
                                status_code=503, headers=DEMO_HEADERS)
        finally:
            await redis.aclose()


def _tabs_of(path: str) -> set:
    """Demo tabs that read this path (for allowed_tabs). The dashboard shows the
    overview and the timeline too, so those belong to both."""
    if path.startswith("/api/signals") or path == "/api/agency/signal-filter":
        return {"signals"}
    if path.startswith("/api/leads"):
        return {"leads"}
    if path in ("/api/analytics/overview", "/api/analytics/timeline"):
        return {"dashboard", "analytics"}
    if path == "/api/tasks/summary":
        return {"dashboard"}
    if path.startswith("/api/analytics"):
        return {"analytics"}
    return set()
