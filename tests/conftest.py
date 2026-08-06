"""Pytest bootstrap: set required env vars BEFORE any app module is imported.

Uses setdefault so a real environment (CI / local .env) can still override.
"""
import os

from cryptography.fernet import Fernet

os.environ.setdefault("REIP_TESTING", "1")
os.environ.setdefault("ENCRYPTION_KEY", Fernet.generate_key().decode())
os.environ.setdefault("SECRET_KEY", "test-secret-key-at-least-32-chars-long-000")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://u:p@localhost:5432/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("YC_SERVICE_ACCOUNT_KEY_FILE", "/tmp/sa-key.json")
os.environ.setdefault("YC_FOLDER_ID", "b1gtest")
os.environ.setdefault("YC_S3_BUCKET", "test-bucket")
os.environ.setdefault("YC_S3_ACCESS_KEY", "test-access")
os.environ.setdefault("YC_S3_SECRET_KEY", "test-secret")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "123:TEST")
os.environ.setdefault("TELEGRAM_BOT_USERNAME", "test_bot")
os.environ.setdefault("BASE_URL", "https://test.local")
os.environ.setdefault("NODE_ENV", "development")


# --- the suite must not depend on what the host machine happens to have -------
#
# The variables above use setdefault so a real .env can override them. That made
# the suite quietly environment-dependent: run it on the production box, where
# every credential is real, and 14 tests fail -- test_collector_unavailable_
# without_creds, test_provider_configured_false_without_keys, /health/deep
# expecting ai: not_configured. They pass in CI only because CI has no keys, so
# the "credentials present" half of the code was never covered anywhere.
#
# Every optional credential is therefore pinned to "absent" for each test, and a
# test that needs one sets it explicitly. That is also the honest default: these
# are the values whose absence the code is supposed to survive.

import pytest  # noqa: E402

_OPTIONAL_CREDENTIALS = (
    "telethon_api_id", "telethon_api_hash", "telethon_phone", "telethon_dc_port",
    "vk_service_token", "youtube_api_key",
    "max_bot_token", "max_bot_username", "max_webhook_secret",
    "telegram_webhook_secret",
    "openai_api_key", "anthropic_api_key",
    "yandex_gpt_api_key", "yandex_gpt_folder_id",
    "gigachat_client_id", "gigachat_client_secret",
    "railway_proxy_url", "railway_proxy_secret",
    "yookassa_shop_id", "yookassa_secret_key",
    "admin_telegram_id",
)


@pytest.fixture(autouse=True)
def _no_ambient_credentials(monkeypatch):
    from app.config import config
    from app.services.ai_service import AIProvider

    for name in _OPTIONAL_CREDENTIALS:
        monkeypatch.setattr(config, name, None, raising=False)
    # The provider is picked from config at call time; production runs OpenAI,
    # which made provider-specific tests fail on a configured box.
    monkeypatch.setattr(config, "ai_default_provider", AIProvider.YANDEX_GPT, raising=False)
    monkeypatch.setattr(config, "node_env", "development", raising=False)


# --- and must never run against a database that is not a test database --------
#
# RUN_DB_TESTS=1 makes the suite create agencies, leads, geos and protected
# cities for real, in whatever DATABASE_URL happens to point at. Run inside the
# production container -- where that variable is the production database -- and
# it writes them straight into it: 197 test agencies and 98 test leads, cleaned
# up afterwards by hand from a dump.
#
# The database name has to say it is a test one. CI's is `reip_test`; production
# is `realestate`, and now says so before a single row is written.

def _refuse_a_non_test_database() -> None:
    if os.getenv("RUN_DB_TESTS") != "1":
        return
    url = os.environ.get("DATABASE_URL", "")
    name = url.rsplit("/", 1)[-1].split("?")[0].lower()
    if "test" not in name:
        raise RuntimeError(
            f"DATABASE_URL указывает на базу '{name}', а не на тестовую. "
            "Тесты с RUN_DB_TESTS=1 пишут в неё агентства, лидов и города. "
            "Назовите тестовую базу так, чтобы в имени было 'test'."
        )


_refuse_a_non_test_database()
