"""FastAPI application entrypoint. TZ section 6.1.

Only routers that are implemented are wired up; more are added incrementally as
each module lands (keeps the app importable and deployable at every step).
"""
from __future__ import annotations

import time
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import config
from app.database import check_database_connection, engine, run_migrations
from app.exceptions import AIBudgetExceededError, AppException, ConsentRequiredError
from app.routers import health

logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Application starting...")
    try:
        await run_migrations()
        logger.info("Database migrations applied")
    except Exception as e:  # noqa: BLE001
        logger.error("Migration failed", error=str(e))
        raise
    if not await check_database_connection():
        logger.error("Database connection failed")
        raise RuntimeError("Cannot connect to database")
    logger.info("Application started successfully")
    yield
    logger.info("Application shutting down...")
    await engine.dispose()
    logger.info("Database connections closed")


app = FastAPI(
    title="Real Estate Intelligence Platform",
    description="AI-система разведки покупателей для агентства недвижимости",
    version="2.0.0",
    docs_url="/api/docs" if config.node_env == "development" else None,
    redoc_url="/api/redoc" if config.node_env == "development" else None,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if config.node_env == "development" else [config.base_url],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    start_time = time.time()
    response = await call_next(request)
    process_time = time.time() - start_time
    logger.info(
        "HTTP request",
        method=request.method,
        path=request.url.path,
        status_code=response.status_code,
        duration_ms=round(process_time * 1000, 2),
        client_ip=request.client.host if request.client else None,
    )
    return response


@app.exception_handler(AppException)
async def app_exception_handler(request: Request, exc: AppException):
    return JSONResponse(status_code=exc.status_code, content={"error": exc.detail, "code": exc.code})


@app.exception_handler(AIBudgetExceededError)
async def ai_budget_handler(request: Request, exc: AIBudgetExceededError):
    return JSONResponse(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        content={"error": "Превышен дневной лимит расходов на AI", "code": "AI_BUDGET_EXCEEDED"},
    )


@app.exception_handler(ConsentRequiredError)
async def consent_handler(request: Request, exc: ConsentRequiredError):
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={
            "error": "Требуется согласие на обработку персональных данных",
            "code": "CONSENT_REQUIRED",
        },
    )


# Routers (added incrementally)
app.include_router(health.router, prefix="/api", tags=["Health"])


@app.get("/")
async def root():
    return {
        "service": "Real Estate Intelligence Platform",
        "version": "2.0.0",
        "status": "running",
        "docs": "/api/docs" if config.node_env == "development" else None,
    }


@app.get("/health", include_in_schema=False)
async def health_check():
    """Root-level liveness probe (acceptance criterion: GET /health -> {"status":"ok"})."""
    return {"status": "ok"}
