"""Tests for the PII anonymizer used before foreign AI calls."""
from app.services.pii_anonymizer import anonymize


def test_phone_is_masked():
    assert "[PHONE]" in anonymize("звоните +7 900 123-45-67 сегодня")
    assert "+7" not in anonymize("+7(900)123-45-67")


def test_email_is_masked():
    out = anonymize("почта ivan.petrov@example.com для связи")
    assert "[EMAIL]" in out
    assert "@example.com" not in out


def test_name_is_masked():
    out = anonymize("Покупатель Иван Петров ищет квартиру")
    assert "[NAME]" in out
    assert "Иван Петров" not in out


def test_no_pii_unchanged():
    text = "ищу двушку у моря до 8 млн"
    assert anonymize(text) == text


def test_empty_string():
    assert anonymize("") == ""
