"""Tests for the phone blind index used for lead dedup."""
from app.services.encryption import phone_blind_index


def test_same_number_different_format_matches():
    assert phone_blind_index("+7 900 123-45-67") == phone_blind_index("+79001234567")


def test_different_numbers_differ():
    assert phone_blind_index("+79001234567") != phone_blind_index("+79007654321")


def test_none_empty_and_no_digits():
    assert phone_blind_index(None) is None
    assert phone_blind_index("") is None
    assert phone_blind_index("---") is None


def test_index_is_sha256_hex():
    assert len(phone_blind_index("+79001234567")) == 64
