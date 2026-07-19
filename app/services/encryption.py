"""PII encryption using Fernet (AES-128-CBC + HMAC-SHA256). TZ section 8.1.

The encryption key lives only in ENCRYPTION_KEY (env), never in the database.
"""
from __future__ import annotations

import hashlib
import hmac
import re
from typing import Optional

import structlog
from cryptography.fernet import Fernet

from app.config import config

logger = structlog.get_logger()


def _get_fernet() -> Fernet:
    """Initialize Fernet from ENCRYPTION_KEY (44-char base64)."""
    try:
        return Fernet(config.encryption_key.encode())
    except Exception as e:  # noqa: BLE001
        logger.error(
            "Invalid ENCRYPTION_KEY. Must be 32 bytes base64 encoded (44 chars).",
            error=str(e),
        )
        raise ValueError("Invalid encryption key format") from e


_fernet = _get_fernet()


def encrypt_pii(value: Optional[str]) -> Optional[bytes]:
    """Encrypt a PII string. Returns bytes for storage in a BYTEA column."""
    if not value:
        return None
    return _fernet.encrypt(value.encode("utf-8"))


def decrypt_pii(encrypted_bytes: Optional[bytes]) -> Optional[str]:
    """Decrypt PII. Returns a sentinel on key mismatch / corrupted data."""
    if not encrypted_bytes:
        return None
    try:
        return _fernet.decrypt(encrypted_bytes).decode("utf-8")
    except Exception:  # noqa: BLE001
        logger.error("PII decryption failed. Possible key mismatch or data corruption.")
        return "[DECRYPTION_ERROR]"


def phone_blind_index(phone: Optional[str]) -> Optional[str]:
    """Deterministic HMAC of a normalized phone, for duplicate lookups.

    Digits-only normalization means "+7 900 123-45-67" and "+79001234567" collide,
    which is what we want for dedup. The blind index reveals nothing about the phone
    without the secret key, and is stored alongside the encrypted value.
    """
    if not phone:
        return None
    digits = re.sub(r"\D", "", phone)
    if not digits:
        return None
    return hmac.new(config.secret_key.encode(), digits.encode(), hashlib.sha256).hexdigest()
