"""Property catalogue import. TZ 14 (objects feed matching).

Production ran on two seed objects, so matching, pitches, offers and the funnel
analytics had nothing real to work with. Agencies keep inventory in Excel with
Russian headers and human-formatted values, so the parsing is where this either
works or quietly corrupts the catalogue.
"""
import pytest

from app.services.property_import import (
    map_row,
    normalize_header,
    parse_bool,
    parse_int,
    parse_number,
    parse_property_type,
    parse_readiness,
    parse_rooms,
    parse_status,
    unmapped_columns,
    validate_row,
)


@pytest.mark.parametrize("raw,expected", [
    ("8 500 000 ₽", 8_500_000),
    ("8500000", 8_500_000),
    ("8 500 000,00 руб.", 8_500_000),
    ("8,5 млн", 8_500_000),
    ("8.5 млн", 8_500_000),
    ("1,2 млрд", 1_200_000_000),
    ("850 тыс", 850_000),
    ("8.500.000", 8_500_000),  # dots as thousands separators
    ("2-комн", 2),             # a hyphen is not a minus sign here
    ("-5", -5),                # a real leading minus still works
    ("56,3", 56.3),
    ("", None),
    (None, None),
    ("—", None),
    (8500000, 8_500_000),
])
def test_parse_number_handles_human_formats(raw, expected):
    assert parse_number(raw) == expected


def test_parse_number_ignores_booleans():
    """bool is an int in Python; a "да" column must not become 1.0."""
    assert parse_number(True) is None


@pytest.mark.parametrize("raw,expected", [
    ("2", 2), ("2-комн", 2), ("2 комнаты", 2),
    ("двухкомнатная", 2), ("трёхкомнатная", 3), ("однокомнатная", 1),
    ("студия", 0), ("Студия", 0),
    ("", None),
])
def test_parse_rooms(raw, expected):
    assert parse_rooms(raw) == expected


@pytest.mark.parametrize("raw,expected", [
    ("квартира", "apartment"), ("2-комн. квартира", "apartment"),
    ("студия", "studio"), ("дом", "house"), ("коттедж", "house"),
    ("земельный участок", "land"), ("коммерческое помещение", "commercial"),
    ("apartment", "apartment"),
    ("", None), ("нечто", None),
])
def test_parse_property_type(raw, expected):
    assert parse_property_type(raw) == expected


@pytest.mark.parametrize("raw,expected", [
    ("сдан", "ready"), ("готов к заселению", "ready"),
    ("строится", "under_construction"), ("котлован", "foundation"),
    ("проектирование", "planning"), ("", None),
])
def test_parse_readiness(raw, expected):
    assert parse_readiness(raw) == expected


@pytest.mark.parametrize("raw,expected", [
    ("продан", "sold"), ("бронь", "reserved"), ("архив", "archive"),
    ("в продаже", "active"), ("", "active"), (None, "active"),
])
def test_parse_status_defaults_to_active(raw, expected):
    assert parse_status(raw) == expected


@pytest.mark.parametrize("raw,expected", [
    ("да", True), ("Да", True), ("+", True), ("новостройка", True), (True, True),
    ("нет", False), ("вторичка", False), ("0", False), (False, False),
    ("", None), ("может быть", None),
])
def test_parse_bool(raw, expected):
    assert parse_bool(raw) == expected


def test_normalize_header_and_unmapped_columns():
    assert normalize_header("Цена, ₽") == "цена"
    assert normalize_header("  Общая площадь  ") == "общаяплощадь"
    assert unmapped_columns(["Название", "Цена", "Риелтор", ""]) == ["Риелтор"]


# --- row mapping ------------------------------------------------------------

def test_map_row_from_a_russian_export():
    row = {
        "Название": " 2-комн. квартира у моря ",
        "Тип": "квартира",
        "Цена, ₽": "8 500 000",
        "Общая площадь": "56,3",
        "Комнат": "2-комн",
        "Этаж": "5",
        "Этажей": "9",
        "Район": "Толстый мыс",
        "Новостройка": "да",
        "Готовность": "сдан",
    }
    mapped = map_row(row, list(row))

    assert mapped["title"] == "2-комн. квартира у моря"
    assert mapped["property_type"] == "apartment"
    assert mapped["price"] == 8_500_000
    assert mapped["area_total"] == 56.3
    assert mapped["rooms"] == 2
    assert mapped["floor"] == 5 and mapped["floors_total"] == 9
    assert mapped["district"] == "Толстый мыс"
    assert mapped["is_new_build"] is True
    assert mapped["readiness_status"] == "ready"
    assert mapped["status"] == "active"
    # Derived, because matching and the market analytics both read it.
    assert mapped["price_per_sqm"] == int(8_500_000 / 56.3)


def test_map_row_infers_studio_from_room_count():
    mapped = map_row({"Название": "Студия", "Цена": "4 900 000", "Комнат": "студия"}, [])
    assert mapped["rooms"] == 0
    assert mapped["property_type"] == "studio"


def test_map_row_keeps_an_explicit_price_per_sqm():
    mapped = map_row(
        {"Название": "X", "Цена": "10 000 000", "Площадь": "50", "Цена за м2": "220000"}, [])
    assert mapped["price_per_sqm"] == 220_000


def test_map_row_ignores_blank_cells():
    mapped = map_row({"Название": "X", "Цена": "5 000 000", "Район": "  ", "Этаж": ""}, [])
    assert "district" not in mapped
    assert "floor" not in mapped


# --- validation -------------------------------------------------------------

def test_validate_requires_title_and_price():
    assert validate_row({"price": 5_000_000}) == "нет названия объекта"
    assert validate_row({"title": "X"}) == "нет цены"
    assert validate_row({"title": "X", "price": 0, "status": "active"}) is not None


def test_validate_rejects_a_catalogue_written_in_thousands():
    """8500 instead of 8 500 000 would make every object fit every budget."""
    problem = validate_row({"title": "X", "price": 8500, "status": "active"})
    assert problem is not None and "тысячах" in problem


def test_validate_accepts_a_good_row():
    assert validate_row({"title": "X", "price": 8_500_000, "status": "active",
                         "property_type": "apartment", "readiness_status": "ready"}) is None


def test_validate_rejects_values_outside_the_db_constraints():
    assert validate_row({"title": "X", "price": 5_000_000, "status": "черновик"}) is not None
    assert validate_row({"title": "X", "price": 5_000_000, "status": "active",
                         "property_type": "яхта"}) is not None


# --- file reading -----------------------------------------------------------

def test_read_csv_semicolon_and_cp1251():
    from app.services.property_import import read_rows

    csv_text = "Название;Цена;Комнат\r\nКвартира;8 500 000;2\r\n"
    rows, headers = read_rows(csv_text.encode("cp1251"), "catalogue.csv")

    assert headers == ["Название", "Цена", "Комнат"]
    assert rows[0]["Название"] == "Квартира"


def test_read_csv_utf8_with_bom():
    from app.services.property_import import read_rows

    rows, _ = read_rows("Название,Цена\nДом,12 000 000\n".encode("utf-8-sig"), "c.csv")
    assert rows[0]["Цена"] == "12 000 000"


def test_read_xlsx_roundtrip():
    from openpyxl import Workbook

    from app.services.property_import import read_rows

    import io
    wb = Workbook()
    ws = wb.active
    ws.append(["Название", "Цена", "Комнат"])
    ws.append(["Квартира у моря", 8500000, 2])
    ws.append([None, None, None])  # blank row must be dropped
    buf = io.BytesIO()
    wb.save(buf)

    rows, headers = read_rows(buf.getvalue(), "catalogue.xlsx")
    assert headers == ["Название", "Цена", "Комнат"]
    assert len(rows) == 1
    assert map_row(rows[0], headers)["price"] == 8_500_000


def test_parse_int_rounds():
    assert parse_int("56,7") == 57
    assert parse_int(None) is None


@pytest.mark.parametrize("header,field", [
    # Real export headers carry units and qualifiers; exact matching missed them
    # and a live dry-run reported "нет цены" for every row.
    ("Цена, руб.", "price"),
    ("Цена, ₽", "price"),
    ("Цена руб", "price"),
    ("Общая площадь, м2", "area_total"),
    ("Комнат, шт", "rooms"),
    ("Этажей в доме", "floors_total"),
    ("Название объекта", "title"),
    # Longest-first, so the more specific key wins over its own prefix.
    ("Цена за м2", "price_per_sqm"),
    ("Этаж", "floor"),
    ("Этажей", "floors_total"),
])
def test_match_column_tolerates_units_and_qualifiers(header, field):
    from app.services.property_import import match_column

    assert match_column(header) == field


def test_match_column_rejects_unrelated_headers():
    from app.services.property_import import match_column

    assert match_column("Риелтор") is None
    assert match_column("") is None
    assert match_column(None) is None
