"""API smoke tests via TestClient.

TestClient is *not* used as a context manager here, so the lifespan (migrations +
DB connection) does not run - these endpoints don't need it.
"""
from fastapi.testclient import TestClient

from app.main import app


def test_root():
    client = TestClient(app)
    r = client.get("/")
    assert r.status_code == 200
    body = r.json()
    assert body["service"] == "Real Estate Intelligence Platform"
    assert body["version"] == "2.0.0"
    assert body["status"] == "running"


def test_root_health_ok():
    client = TestClient(app)
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_api_health():
    client = TestClient(app)
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["version"] == "2.0.0"
    assert "timestamp" in body


def test_api_deep_health_shape():
    client = TestClient(app)
    r = client.get("/api/health/deep")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] in ("ok", "degraded")
    assert "database" in body["checks"]
    assert "redis" in body["checks"]
    assert body["checks"]["ai"] == "not_configured"
    # Section 33 additions.
    assert "telegram_bot" in body["checks"]
    assert "celery_queue" in body["checks"]


def test_mini_app_served():
    client = TestClient(app)
    r = client.get("/mini-app/")
    assert r.status_code == 200
    assert "Real Estate Intelligence" in r.text


def test_the_api_schema_is_not_public_in_production(monkeypatch):
    """/api/docs was closed and /openapi.json was left open — the same map of
    every endpoint and every field, one URL away."""
    from app.config import config

    monkeypatch.setattr(config, "node_env", "production")
    import importlib

    import app.main as main
    reloaded = importlib.reload(main)
    try:
        assert reloaded.app.openapi_url is None
        assert reloaded.app.docs_url is None
    finally:
        monkeypatch.setattr(config, "node_env", "development")
        importlib.reload(main)
