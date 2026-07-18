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
