import sqlite3

import pytest

from emporio_agent.config import RAW_DATA_DIR
from emporio_agent.data_loader import (
    build_database,
    compute_availability,
    get_connection,
    parse_payment_method,
)
from emporio_agent.text_utils import digits_only, normalize_text


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    path = build_database(tmp_path_factory.mktemp("db") / "store.db", RAW_DATA_DIR)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


def scalar(conn, sql, *params):
    return conn.execute(sql, params).fetchone()[0]


def test_row_counts_match_the_raw_files(db):
    assert scalar(db, "SELECT COUNT(*) FROM categories") == 9
    assert scalar(db, "SELECT COUNT(*) FROM products") == 65
    assert scalar(db, "SELECT COUNT(*) FROM customers") == 50
    assert scalar(db, "SELECT COUNT(*) FROM orders") == 20
    assert scalar(db, "SELECT COUNT(*) FROM order_items") == 22
    assert scalar(db, "SELECT COUNT(*) FROM promotions") == 25


def test_availability_combines_status_and_stock(db):
    availability = lambda pid: scalar(db, "SELECT availability FROM products WHERE product_id = ?", pid)
    assert availability(95) == "in_stock"  # Takamine GD20
    assert availability(96) == "out_of_stock"  # active, but stock = 0
    assert availability(113) == "discontinued"
    assert availability(130) == "coming_soon"


def test_compute_availability_edge_cases():
    assert compute_availability("active", 0) == "out_of_stock"
    assert compute_availability("discontinued", 10) == "discontinued"
    assert compute_availability("something_else", 10) == "unavailable"


def test_only_active_promotions_are_exposed(db):
    promoted = {row[0] for row in db.execute("SELECT product_id FROM active_promotions")}
    assert promoted == {90, 94, 121, 127}
    assert scalar(db, "SELECT discount_percent FROM active_promotions WHERE product_id = 127") == 10


def test_inactive_promotions_are_kept_but_not_active(db):
    # Product 96 had two past promotions (18% and 40%); neither is active.
    assert scalar(db, "SELECT COUNT(*) FROM promotions WHERE product_id = 96") == 2
    assert scalar(db, "SELECT COUNT(*) FROM active_promotions WHERE product_id = 96") == 0


def test_payment_method_is_split_into_type_and_installments(db):
    assert parse_payment_method("credit_6x") == ("credit", 6)
    assert parse_payment_method("pix") == ("pix", 1)
    row = db.execute("SELECT payment_type, installments FROM orders WHERE order_id = 3").fetchone()
    assert (row["payment_type"], row["installments"]) == ("credit", 12)


def test_missing_tracking_data_becomes_null(db):
    row = db.execute("SELECT tracking_code, estimated_delivery FROM orders WHERE order_id = 9").fetchone()
    assert row["tracking_code"] is None and row["estimated_delivery"] is None
    assert scalar(db, "SELECT tracking_code FROM orders WHERE order_id = 8") == "BRJL5544332BR"


def test_specs_are_flattened_for_filtering(db):
    row = db.execute("SELECT * FROM products WHERE product_id = 95").fetchone()
    assert row["string_material"] == "steel"
    assert row["has_pickup"] == 0
    electric_guitar = db.execute("SELECT * FROM products WHERE product_id = 131").fetchone()
    assert electric_guitar["string_count"] == 6 and electric_guitar["string_material"] is None


def test_search_text_is_accent_insensitive(db):
    hits = db.execute("SELECT product_id FROM products WHERE search_text LIKE ?", ("%violao%",)).fetchall()
    assert hits  # category name "Violões" is part of the search text


def test_search_text_includes_portuguese_aliases_for_english_specs(db):
    # Takamine GD20 is a steel-string acoustic whose name/description never say "aço".
    assert "aco" in scalar(db, "SELECT search_text FROM products WHERE product_id = 95")
    # Electroacoustic models should be found by "eletroacustico".
    assert "eletroacustico" in scalar(db, "SELECT search_text FROM products WHERE product_id = 100")
    assert "eletroacustico" not in scalar(db, "SELECT search_text FROM products WHERE product_id = 95")


def test_known_source_data_issues_are_recorded(db):
    issues = {(r["issue_type"], r["entity_id"]) for r in db.execute("SELECT * FROM data_issues")}
    assert ("total_mismatch", "3") in issues
    assert ("total_mismatch", "20") in issues
    assert ("duplicate_email", "11,43") in issues or ("duplicate_email", "43,11") in issues
    assert ("coming_soon_but_sold", "130") in issues
    assert {("category_without_products", str(c)) for c in (6, 7, 8)} <= issues
    assert not [i for i in issues if i[0] == "invalid_tracking_code"]


def test_get_connection_builds_the_database_when_missing(tmp_path):
    conn = get_connection(tmp_path / "nested" / "store.db", RAW_DATA_DIR)
    try:
        assert scalar(conn, "SELECT COUNT(*) FROM products") == 65
    finally:
        conn.close()


def test_normalize_text_and_digits_only():
    assert normalize_text("  Violão   AÇO ") == "violao aco"
    assert normalize_text(None) == ""
    assert digits_only("(67) 99812-3456") == "67998123456"
