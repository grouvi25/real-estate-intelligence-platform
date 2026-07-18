"""Pytest bootstrap: set required env vars BEFORE any app module is imported.

Uses setdefault so a real environment (CI / local .env) can still override.
"""
import os

from cryptography.fernet import Fernet

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
