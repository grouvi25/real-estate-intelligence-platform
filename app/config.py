"""Application configuration via Pydantic Settings.

Follows TZ section 4.1. All secrets are read from environment variables / .env,
never hardcoded.
"""
from __future__ import annotations

from enum import Enum
from typing import Literal, Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AIProvider(str, Enum):
    YANDEX_GPT = "yandexgpt"
    GIGACHAT = "gigachat"
    OPENAI = "openai"
    ANTHROPIC = "anthropic"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # === YANDEX CLOUD ===
    yc_service_account_key_file: str = Field(..., alias="YC_SERVICE_ACCOUNT_KEY_FILE")
    yc_folder_id: str = Field(..., alias="YC_FOLDER_ID")
    yc_region: str = Field(default="ru-central1", alias="YC_REGION")

    # === DATABASES (RU only) ===
    database_url: str = Field(..., alias="DATABASE_URL")
    redis_url: str = Field(..., alias="REDIS_URL")

    # === OBJECT STORAGE ===
    yc_s3_endpoint: str = Field(default="https://storage.yandexcloud.net", alias="YC_S3_ENDPOINT")
    yc_s3_bucket: str = Field(..., alias="YC_S3_BUCKET")
    yc_s3_access_key: str = Field(..., alias="YC_S3_ACCESS_KEY")
    yc_s3_secret_key: str = Field(..., alias="YC_S3_SECRET_KEY")
    yc_s3_region: str = Field(default="ru-central1", alias="YC_S3_REGION")

    # === AI - RUSSIAN PROVIDERS ===
    yandex_gpt_folder_id: Optional[str] = Field(default=None, alias="YANDEX_GPT_FOLDER_ID")
    yandex_gpt_api_key: Optional[str] = Field(default=None, alias="YANDEX_GPT_API_KEY")
    gigachat_client_id: Optional[str] = Field(default=None, alias="GIGACHAT_CLIENT_ID")
    gigachat_client_secret: Optional[str] = Field(default=None, alias="GIGACHAT_CLIENT_SECRET")
    gigachat_scope: str = Field(default="GIGACHAT_API_PERS", alias="GIGACHAT_SCOPE")
    # Sber's GigaChat serves TLS from the "Russian Trusted Root CA", which isn't in
    # the default trust store. Verification is off by default; set to true once the
    # CA bundle is installed on the host.
    gigachat_verify_ssl: bool = Field(default=False, alias="GIGACHAT_VERIFY_SSL")

    # === AI - FOREIGN (via Railway proxy) ===
    railway_proxy_url: Optional[str] = Field(default=None, alias="RAILWAY_PROXY_URL")
    railway_proxy_secret: Optional[str] = Field(default=None, alias="RAILWAY_PROXY_SECRET")
    openai_api_key: Optional[str] = Field(default=None, alias="OPENAI_API_KEY")
    anthropic_api_key: Optional[str] = Field(default=None, alias="ANTHROPIC_API_KEY")

    # === AI CONFIG ===
    ai_default_provider: AIProvider = Field(default=AIProvider.YANDEX_GPT, alias="AI_DEFAULT_PROVIDER")
    ai_default_model: str = Field(default="yandexgpt-pro", alias="AI_DEFAULT_MODEL")
    ai_daily_budget_rub: float = Field(default=1000.0, alias="AI_DAILY_BUDGET_RUB")
    ai_signal_batch_size: int = Field(default=50, alias="AI_SIGNAL_BATCH_SIZE")

    # === BOTS ===
    telegram_bot_token: str = Field(..., alias="TELEGRAM_BOT_TOKEN")
    telegram_bot_username: str = Field(..., alias="TELEGRAM_BOT_USERNAME")
    telegram_webhook_path: str = Field(default="/telegram/webhook", alias="TELEGRAM_WEBHOOK_PATH")
    telegram_webhook_secret: Optional[str] = Field(default=None, alias="TELEGRAM_WEBHOOK_SECRET")
    max_bot_token: Optional[str] = Field(default=None, alias="MAX_BOT_TOKEN")
    max_bot_username: Optional[str] = Field(default=None, alias="MAX_BOT_USERNAME")
    max_webhook_path: str = Field(default="/max/webhook", alias="MAX_WEBHOOK_PATH")
    max_base_url: str = Field(default="https://botapi.max.ru", alias="MAX_BASE_URL")
    # Shared secret echoed back in X-Max-Bot-Api-Secret; set when subscribing the
    # webhook (POST /subscriptions). Plain comparison, not an HMAC.
    max_webhook_secret: Optional[str] = Field(default=None, alias="MAX_WEBHOOK_SECRET")

    # Telethon (separate account for reading chats)
    telethon_session_name: str = Field(default="monitor_session", alias="TELETHON_SESSION_NAME")
    telethon_api_id: Optional[int] = Field(default=None, alias="TELETHON_API_ID")
    telethon_api_hash: Optional[str] = Field(default=None, alias="TELETHON_API_HASH")
    telethon_phone: Optional[str] = Field(default=None, alias="TELETHON_PHONE")
    # Pin MTProto to an alternative Telegram port (443 / 80 / 5222) when the host
    # cannot reach a DC on the default one. 0/None keeps Telethon's own choice.
    telethon_dc_port: Optional[int] = Field(default=None, alias="TELETHON_DC_PORT")

    # === EXTERNAL INTEGRATIONS ===
    vk_service_token: Optional[str] = Field(default=None, alias="VK_SERVICE_TOKEN")
    vk_api_version: str = Field(default="5.199", alias="VK_API_VERSION")
    youtube_api_key: Optional[str] = Field(default=None, alias="YOUTUBE_API_KEY")
    # Yandex Maps JS API (ТЗ 2.3). The key is public by design — it is
    # restricted by domain in the Yandex cabinet, not kept secret — so the
    # cabinet may hand it to the browser.
    yandex_maps_api_key: Optional[str] = Field(default=None, alias="YANDEX_MAPS_API_KEY")
    # The geocoder is a separate product with its own key, even on the same
    # account. It is billed per request and never leaves the server.
    yandex_geocoder_api_key: Optional[str] = Field(
        default=None, alias="YANDEX_GEOCODER_API_KEY")
    yookassa_shop_id: Optional[str] = Field(default=None, alias="YOOKASSA_SHOP_ID")
    yookassa_secret_key: Optional[str] = Field(default=None, alias="YOOKASSA_SECRET_KEY")

    # === APPLICATION ===
    base_url: str = Field(..., alias="BASE_URL")
    secret_key: str = Field(..., alias="SECRET_KEY")
    encryption_key: str = Field(..., alias="ENCRYPTION_KEY")  # 32 bytes, base64 (44 chars)
    node_env: Literal["development", "production"] = Field(default="production", alias="NODE_ENV")
    admin_telegram_id: Optional[int] = Field(default=None, alias="ADMIN_TELEGRAM_ID")

    # === 152-FZ ===
    consent_version: str = Field(default="1.0", alias="CONSENT_VERSION")
    pd_storage_region: str = Field(default="ru-central1", alias="PD_STORAGE_REGION")
    pd_encryption_enabled: bool = Field(default=True, alias="PD_ENCRYPTION_ENABLED")

    # === GEO PROTECTION ===
    platform_owner_agency_id: Optional[str] = Field(default=None, alias="PLATFORM_OWNER_AGENCY_ID")
    geo_protection_radius_km: int = Field(default=100, alias="GEO_PROTECTION_RADIUS_KM")

    # === PARTNERS ===
    referral_expiry_days: int = Field(default=30, alias="REFERRAL_EXPIRY_DAYS")
    referral_confirmation_hours: int = Field(default=24, alias="REFERRAL_CONFIRMATION_HOURS")

    # === AI MODELS BY TASK ===
    @property
    def ai_models(self) -> dict[str, str]:
        return {
            "intent_scoring": "yandexgpt-lite",
            "buyer_profile": "yandexgpt-pro",
            "object_analysis": "yandexgpt-pro",
            "matching_pitch": "yandexgpt-pro",
            "reply_generator": "yandexgpt-lite",
            "source_evaluation": "yandexgpt-lite",
            "daily_report": "yandexgpt-pro",
            "geo_keywords": "yandexgpt-pro",
            "market_analysis": "yandexgpt-lite",
            "listing_generator": "yandexgpt-pro",
        }

    @property
    def openai_models(self) -> dict[str, str]:
        """OpenAI model per task (via Railway proxy). Heavy analytical tasks use
        gpt-4o; the rest use the cheaper gpt-4o-mini."""
        heavy = {"buyer_profile", "object_analysis", "matching_pitch", "daily_report"}
        return {module: ("gpt-4o" if module in heavy else "gpt-4o-mini")
                for module in self.ai_models}

    @property
    def gigachat_models(self) -> dict[str, str]:
        """GigaChat model per task. Heavy analytical tasks use GigaChat-Pro."""
        heavy = {"buyer_profile", "object_analysis", "matching_pitch", "daily_report"}
        return {module: ("GigaChat-Pro" if module in heavy else "GigaChat")
                for module in self.ai_models}

    @property
    def anthropic_models(self) -> dict[str, str]:
        """Anthropic model per task (via proxy). Heavy tasks use Sonnet."""
        heavy = {"buyer_profile", "object_analysis", "matching_pitch", "daily_report"}
        return {module: ("claude-3-5-sonnet-latest" if module in heavy
                         else "claude-3-5-haiku-latest")
                for module in self.ai_models}

    @field_validator("encryption_key")
    @classmethod
    def validate_encryption_key(cls, v: str) -> str:
        """ENCRYPTION_KEY must be a valid Fernet key (32 bytes base64 = 44 chars)."""
        if len(v) != 44:
            raise ValueError(
                "ENCRYPTION_KEY must be a valid Fernet key (32 bytes, base64 encoded = 44 chars)"
            )
        return v

    @field_validator("secret_key")
    @classmethod
    def validate_secret_key(cls, v: str) -> str:
        """SECRET_KEY must be long enough for JWT signing."""
        if len(v) < 32:
            raise ValueError("SECRET_KEY must be at least 32 characters")
        return v


# Global settings instance
config = Settings()
