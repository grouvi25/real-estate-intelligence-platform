"""Model metadata + PII hybrid-property tests (no database required)."""
import uuid


def test_tables_registered():
    from app.models import agency as _agency  # noqa: F401
    from app.models import manager as _manager  # noqa: F401
    from app.models.base import Base

    tables = Base.metadata.tables
    assert "agencies" in tables
    assert "managers" in tables


def test_agency_columns():
    from app.models import manager as _manager  # noqa: F401
    from app.models.base import Base

    cols = Base.metadata.tables["agencies"].columns
    for name in ("id", "name", "base_city", "subscription_plan", "settings", "created_at", "updated_at"):
        assert name in cols


def test_manager_columns_use_encrypted_names():
    from app.models import manager as _manager  # noqa: F401
    from app.models.base import Base

    cols = Base.metadata.tables["managers"].columns
    # PII must be persisted under *_encrypted BYTEA columns, never plaintext.
    assert "phone_encrypted" in cols
    assert "email_encrypted" in cols
    assert "phone" not in cols
    assert "email" not in cols
    for name in ("telegram_id", "max_user_id", "preferred_platform", "role", "is_active"):
        assert name in cols


def test_manager_phone_encryption_roundtrip():
    from app.models.manager import Manager

    m = Manager(agency_id=uuid.uuid4(), name="Иван")
    assert m.phone is None

    m.phone = "+79001234567"
    assert m._phone_encrypted is not None
    assert m._phone_encrypted != b"+79001234567"  # stored encrypted, not plaintext
    assert m.phone == "+79001234567"  # transparently decrypted

    m.phone = None
    assert m._phone_encrypted is None
    assert m.phone is None


def test_manager_email_encryption_roundtrip():
    from app.models.manager import Manager

    m = Manager(agency_id=uuid.uuid4(), name="Пётр")
    m.email = "petr@example.com"
    assert m._email_encrypted is not None
    assert m.email == "petr@example.com"
