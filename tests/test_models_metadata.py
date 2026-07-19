"""Model metadata, mapper configuration, and PII hybrid-property tests (no DB)."""
import uuid

from sqlalchemy.orm import configure_mappers

import app.models  # noqa: F401  (registers all models)
from app.models.base import Base

ALL_TABLES = {
    "agencies",
    "geo_locations",
    "protected_geos",
    "sources",
    "signals",
    "leads",
    "properties",
    "lead_property_matches",
    "managers",
    "tasks",
    "partner_agencies",
    "partner_referrals",
    "deal_outcomes",
    "source_discovery_log",
    "activity_log",
}


def test_all_tables_registered():
    assert ALL_TABLES.issubset(set(Base.metadata.tables))


def test_mappers_configure_without_error():
    # Raises if any relationship / FK reference is misconfigured.
    configure_mappers()


def test_pii_columns_are_encrypted_bytea():
    cols_leads = Base.metadata.tables["leads"].columns
    for name in ("name_encrypted", "phone_encrypted", "email_encrypted"):
        assert name in cols_leads
    assert "name" not in cols_leads and "phone" not in cols_leads
    assert "contact_phone_encrypted" in Base.metadata.tables["partner_agencies"].columns


def test_reserved_metadata_column_mapped_as_meta():
    # 'metadata' is reserved on declarative classes; must be a real DB column.
    assert "metadata" in Base.metadata.tables["sources"].columns
    assert "metadata" in Base.metadata.tables["activity_log"].columns


def test_source_discovery_log_has_processed_at_only():
    cols = Base.metadata.tables["source_discovery_log"].columns
    assert "processed_at" in cols
    assert "created_at" not in cols
    assert "updated_at" not in cols


def test_created_only_tables_have_no_updated_at():
    for table in ("protected_geos", "partner_referrals", "deal_outcomes", "activity_log"):
        cols = Base.metadata.tables[table].columns
        assert "created_at" in cols
        assert "updated_at" not in cols


def test_lead_pii_encryption_roundtrip():
    from app.models.lead import Lead

    lead = Lead(agency_id=uuid.uuid4(), source_type="lead_magnet")
    assert lead.name is None and lead.phone is None

    lead.name = "Иван Петров"
    lead.phone = "+79001234567"
    lead.email = "ivan@example.com"

    assert lead._name_encrypted is not None
    assert lead._name_encrypted != "Иван Петров".encode()
    assert lead.name == "Иван Петров"
    assert lead.phone == "+79001234567"
    assert lead.email == "ivan@example.com"
