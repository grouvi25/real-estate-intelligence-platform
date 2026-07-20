"""Document rendering tests (TZ 32). HTML is pure; PDF path is optional."""
import pytest

from app.exceptions import AppException
from app.services import document_service as ds


def test_render_commercial_offer_html():
    html = ds.render_html("commercial_offer", {
        "agency_name": "Агентство Море",
        "manager_name": "Анна",
        "client_name": "Иван",
        "properties": [
            {"title": "2к у моря", "price": 7_000_000, "match_score": 88, "pitch": "Отличный вид"},
        ],
    })
    assert "2к у моря" in html
    assert "7 000 000" in html  # money filter with thin spaces
    assert "Иван" in html
    assert "88%" in html


def test_render_object_report_html():
    html = ds.render_html("object_report", {
        "title": "Пентхаус",
        "price": 30_000_000,
        "address": "ул. Морская, 1",
        "district": "Центр",
        "rooms": 4,
        "area_total": 120,
        "floor": 10,
        "floors_total": 12,
        "description": "Прекрасный вид",
    })
    assert "Пентхаус" in html
    assert "30 000 000" in html
    assert "ул. Морская, 1" in html


def test_render_unknown_type_raises():
    with pytest.raises(AppException) as exc:
        ds.render_html("bogus", {})
    assert exc.value.code == "UNKNOWN_DOCUMENT_TYPE"


def test_money_filter_handles_none():
    html = ds.render_html("object_report", {"title": "X", "price": None})
    assert "—" in html


def test_render_pdf_without_weasyprint_raises_501():
    # WeasyPrint isn't installed in the base/test environment (optional 'pdf' extra).
    try:
        import weasyprint  # noqa: F401
    except Exception:
        with pytest.raises(AppException) as exc:
            ds.render_pdf("object_report", {"title": "X", "price": 1})
        assert exc.value.status_code == 501
        assert exc.value.code == "PDF_UNAVAILABLE"
