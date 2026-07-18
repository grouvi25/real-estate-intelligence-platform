"""Tests for app.config settings and validators."""
import pytest


def test_config_loads_from_env():
    from app.config import config

    assert config.database_url.startswith("postgresql+asyncpg://")
    assert config.node_env == "development"
    assert len(config.encryption_key) == 44


def test_ai_models_mapping_complete():
    from app.config import config

    models = config.ai_models
    for module in (
        "intent_scoring",
        "buyer_profile",
        "object_analysis",
        "matching_pitch",
        "reply_generator",
        "source_evaluation",
        "daily_report",
        "geo_keywords",
        "market_analysis",
        "listing_generator",
    ):
        assert module in models
        assert models[module].startswith("yandexgpt")


def test_encryption_key_must_be_44_chars(monkeypatch):
    from app.config import Settings

    monkeypatch.setenv("ENCRYPTION_KEY", "too-short")
    with pytest.raises(ValueError, match="Fernet key"):
        Settings()


def test_secret_key_min_length(monkeypatch):
    from cryptography.fernet import Fernet

    from app.config import Settings

    monkeypatch.setenv("ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("SECRET_KEY", "short")
    with pytest.raises(ValueError, match="at least 32"):
        Settings()
