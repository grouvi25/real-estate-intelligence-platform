"""Tests for PII encryption (Fernet)."""
from cryptography.fernet import Fernet

from app.services.encryption import decrypt_pii, encrypt_pii


def test_encrypt_decrypt_roundtrip():
    plain = "Иван Петров +7 900 123-45-67"
    enc = encrypt_pii(plain)
    assert isinstance(enc, bytes)
    assert enc != plain.encode("utf-8")
    assert decrypt_pii(enc) == plain


def test_encrypt_none_and_empty():
    assert encrypt_pii(None) is None
    assert encrypt_pii("") is None


def test_decrypt_none():
    assert decrypt_pii(None) is None


def test_decrypt_wrong_key_returns_sentinel():
    # Data encrypted with a different key must not decrypt.
    other = Fernet(Fernet.generate_key())
    bad = other.encrypt(b"secret data")
    assert decrypt_pii(bad) == "[DECRYPTION_ERROR]"


def test_ciphertext_is_non_deterministic():
    # Fernet embeds a random IV -> same plaintext yields different ciphertext.
    a = encrypt_pii("same value")
    b = encrypt_pii("same value")
    assert a != b
    assert decrypt_pii(a) == decrypt_pii(b) == "same value"
