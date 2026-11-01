"""Load the raw CSV files into a clean, query-friendly SQLite database.

The raw files in ``data/raw`` are never edited. All cleaning happens here and the
result is written to ``data/store.db`` (git-ignored, rebuilt on demand).

Run ``python -m emporio_agent.data_loader`` to rebuild the database manually.
"""

import csv
import json
import re
import sqlite3
from pathlib import Path

from emporio_agent.config import DB_PATH, RAW_DATA_DIR
from emporio_agent.text_utils import digits_only, normalize_text

# Tracking code format from the policy manual: "BR" + 9 alphanumerics + "BR".
TRACKING_CODE_PATTERN = re.compile(r"^BR[A-Z0-9]{9}BR$")

SCHEMA = """
CREATE TABLE categories (
    category_id INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    description TEXT
);

CREATE TABLE products (
    product_id      INTEGER PRIMARY KEY,
    name            TEXT NOT NULL,
    category_id     INTEGER NOT NULL REFERENCES categories(category_id),
    description     TEXT,
    price_brl       REAL NOT NULL,
    stock_quantity  INTEGER NOT NULL,
    status          TEXT NOT NULL,
    availability    TEXT NOT NULL,  -- in_stock | out_of_stock | discontinued | coming_soon
    string_material TEXT,           -- nylon | steel (acoustic guitars and ukuleles)
    string_count    INTEGER,        -- 6, 7, ... (electric guitars and basses)
    has_pickup      INTEGER,        -- 1 = electroacoustic, 0 = acoustic only, NULL = n/a
    color           TEXT,
    specs_json      TEXT NOT NULL,
    created_at      TEXT,
    search_text     TEXT NOT NULL   -- accent-free, lowercase text used for searching
);

CREATE TABLE customers (
    customer_id      INTEGER PRIMARY KEY,
    name             TEXT NOT NULL,
    name_normalized  TEXT NOT NULL,
    phone            TEXT,
    phone_digits     TEXT,
    email            TEXT,
    email_normalized TEXT,
    city             TEXT
);

CREATE TABLE orders (
    order_id           INTEGER PRIMARY KEY,
    customer_id        INTEGER NOT NULL REFERENCES customers(customer_id),
    order_date         TEXT NOT NULL,
    status             TEXT NOT NULL,   -- pending | confirmed | shipped | delivered | cancelled
    total_brl          REAL NOT NULL,
    payment_method     TEXT NOT NULL,   -- raw value, e.g. credit_6x
    payment_type       TEXT NOT NULL,   -- pix | boleto | debit | credit
    installments       INTEGER NOT NULL,
    tracking_code      TEXT,
    estimated_delivery TEXT,
    notes              TEXT,
    items_total_brl    REAL             -- sum of items at current catalog prices
);

CREATE TABLE order_items (
    item_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id   INTEGER NOT NULL REFERENCES orders(order_id),
    product_id INTEGER NOT NULL REFERENCES products(product_id),
    quantity   INTEGER NOT NULL
);

CREATE TABLE promotions (
    promotion_id     INTEGER PRIMARY KEY,
    product_id       INTEGER NOT NULL REFERENCES products(product_id),
    discount_percent REAL NOT NULL,
    description      TEXT,
    is_active        INTEGER NOT NULL
);

-- Only active promotions are valid. If a product ever has more than one active
-- promotion, the largest discount wins (promotions are not cumulative).
CREATE VIEW active_promotions AS
SELECT product_id,
       MAX(discount_percent) AS discount_percent,
       description,
       promotion_id
FROM promotions
WHERE is_active = 1
GROUP BY product_id;

-- Inconsistencies found in the source data, recorded rather than silently fixed.
CREATE TABLE data_issues (
    issue_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    entity     TEXT NOT NULL,
    entity_id  TEXT NOT NULL,
    issue_type TEXT NOT NULL,
    detail     TEXT NOT NULL
);

CREATE INDEX idx_products_category ON products(category_id);
CREATE INDEX idx_orders_customer ON orders(customer_id);
CREATE INDEX idx_order_items_order ON order_items(order_id);
CREATE INDEX idx_promotions_product ON promotions(product_id);
"""


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _blank_to_none(value: str | None) -> str | None:
    value = (value or "").strip()
    return value or None


def compute_availability(status: str, stock_quantity: int) -> str:
    """Single availability label that combines catalog status and stock."""
    if status == "discontinued":
        return "discontinued"
    if status == "coming_soon":
        return "coming_soon"
    if status == "active":
        return "in_stock" if stock_quantity > 0 else "out_of_stock"
    return "unavailable"


def parse_payment_method(raw: str) -> tuple[str, int]:
    """Split values like ``credit_6x`` into (``credit``, 6); others are single payment."""
    match = re.fullmatch(r"credit_(\d+)x", raw.strip())
    if match:
        return "credit", int(match.group(1))
    return raw.strip(), 1


def _flatten_specs(specs: dict[str, str]) -> dict[str, object]:
    """Extract the few spec fields that are useful as search filters."""
    strings = str(specs.get("strings", "")).strip().lower()
    electronics = str(specs.get("electronics", "")).strip().lower()
    return {
        "string_material": strings if strings in ("nylon", "steel") else None,
        "string_count": int(strings) if strings.isdigit() else None,
        "has_pickup": {"yes": 1, "no": 0}.get(electronics),
        "color": _blank_to_none(specs.get("color")),
    }


def _portuguese_aliases(flat: dict[str, object]) -> list[str]:
    """Portuguese search terms for spec values that are stored in English.

    Specs say ``"steel"`` and ``"electronics": "yes"``, but customers ask for
    "violão de aço" or "eletroacústico".
    """
    aliases = []
    if flat["string_material"] == "steel":
        aliases.append("aco corda de aco")
    elif flat["string_material"] == "nylon":
        aliases.append("nylon corda de nylon")
    if flat["has_pickup"] == 1:
        aliases.append("eletroacustico eletrico amplificado")
    return aliases


def _load_categories(conn: sqlite3.Connection, raw_dir: Path) -> dict[int, str]:
    rows = _read_csv(raw_dir / "categories.csv")
    conn.executemany(
        "INSERT INTO categories VALUES (?, ?, ?)",
        [(int(r["category_id"]), r["name"].strip(), _blank_to_none(r["description"])) for r in rows],
    )
    return {int(r["category_id"]): r["name"].strip() for r in rows}


def _load_products(conn: sqlite3.Connection, raw_dir: Path, category_names: dict[int, str]) -> None:
    records = []
    for r in _read_csv(raw_dir / "products.csv"):
        specs = json.loads(r["specs"])
        category_id = int(r["category_id"])
        stock = int(r["stock_quantity"])
        status = r["status"].strip().lower()
        flat = _flatten_specs(specs)
        search_text = normalize_text(
            " ".join(
                [
                    r["name"],
                    category_names.get(category_id, ""),
                    r["description"],
                    *map(str, specs.values()),
                    *_portuguese_aliases(flat),
                ]
            )
        )
        records.append(
            (
                int(r["product_id"]),
                r["name"].strip(),
                category_id,
                _blank_to_none(r["description"]),
                float(r["price_brl"]),
                stock,
                status,
                compute_availability(status, stock),
                flat["string_material"],
                flat["string_count"],
                flat["has_pickup"],
                flat["color"],
                json.dumps(specs, ensure_ascii=False),
                _blank_to_none(r["created_at"]),
                search_text,
            )
        )
    conn.executemany("INSERT INTO products VALUES (" + ",".join("?" * 15) + ")", records)


def _load_customers(conn: sqlite3.Connection, raw_dir: Path) -> None:
    records = [
        (
            int(r["customer_id"]),
            r["name"].strip(),
            normalize_text(r["name"]),
            _blank_to_none(r["phone"]),
            digits_only(r["phone"]) or None,
            _blank_to_none(r["email"]),
            (r["email"] or "").strip().lower() or None,
            _blank_to_none(r["city"]),
        )
        for r in _read_csv(raw_dir / "customers.csv")
    ]
    conn.executemany("INSERT INTO customers VALUES (?,?,?,?,?,?,?,?)", records)


def _load_orders(conn: sqlite3.Connection, raw_dir: Path) -> None:
    records = []
    for r in _read_csv(raw_dir / "orders.csv"):
        payment_type, installments = parse_payment_method(r["payment_method"])
        tracking = _blank_to_none(r["tracking_code"])
        records.append(
            (
                int(r["order_id"]),
                int(r["customer_id"]),
                r["order_date"].strip(),
                r["status"].strip().lower(),
                float(r["total_brl"]),
                r["payment_method"].strip(),
                payment_type,
                installments,
                tracking.upper() if tracking else None,
                _blank_to_none(r["estimated_delivery"]),
                _blank_to_none(r["notes"]),
                None,
            )
        )
    conn.executemany("INSERT INTO orders VALUES (" + ",".join("?" * 12) + ")", records)

    conn.executemany(
        "INSERT INTO order_items (order_id, product_id, quantity) VALUES (?, ?, ?)",
        [
            (int(r["order_id"]), int(r["product_id"]), int(r["quantity"]))
            for r in _read_csv(raw_dir / "order_items.csv")
        ],
    )
    conn.execute(
        """
        UPDATE orders SET items_total_brl = (
            SELECT ROUND(SUM(oi.quantity * p.price_brl), 2)
            FROM order_items oi JOIN products p USING (product_id)
            WHERE oi.order_id = orders.order_id
        )
        """
    )


def _load_promotions(conn: sqlite3.Connection, raw_dir: Path) -> None:
    conn.executemany(
        "INSERT INTO promotions VALUES (?, ?, ?, ?, ?)",
        [
            (
                int(r["promotion_id"]),
                int(r["product_id"]),
                float(r["discount_percent"]),
                _blank_to_none(r["description"]),
                int(r["is_active"]),
            )
            for r in _read_csv(raw_dir / "promotions.csv")
        ],
    )


def _record_issue(conn: sqlite3.Connection, entity: str, entity_id: object, issue_type: str, detail: str) -> None:
    conn.execute(
        "INSERT INTO data_issues (entity, entity_id, issue_type, detail) VALUES (?, ?, ?, ?)",
        (entity, str(entity_id), issue_type, detail),
    )


def _detect_issues(conn: sqlite3.Connection) -> None:
    """Record inconsistencies in the source data so they can be documented and handled."""
    for email, ids in conn.execute(
        """
        SELECT email_normalized, GROUP_CONCAT(customer_id) FROM customers
        WHERE email_normalized IS NOT NULL
        GROUP BY email_normalized HAVING COUNT(*) > 1
        """
    ).fetchall():
        _record_issue(conn, "customer", ids, "duplicate_email", f"Customers {ids} share the e-mail {email}")

    for order_id, total, items_total in conn.execute(
        "SELECT order_id, total_brl, items_total_brl FROM orders WHERE ABS(total_brl - items_total_brl) > 0.01"
    ).fetchall():
        _record_issue(
            conn,
            "order",
            order_id,
            "total_mismatch",
            f"total_brl={total:.2f} but items add up to {items_total:.2f} at current catalog prices",
        )

    for product_id, name, order_ids in conn.execute(
        """
        SELECT p.product_id, p.name, GROUP_CONCAT(DISTINCT o.order_id)
        FROM products p
        JOIN order_items oi USING (product_id)
        JOIN orders o USING (order_id)
        WHERE p.status = 'coming_soon' AND o.status != 'cancelled'
        GROUP BY p.product_id
        """
    ).fetchall():
        _record_issue(
            conn,
            "product",
            product_id,
            "coming_soon_but_sold",
            f"{name} is marked coming_soon but appears in non-cancelled orders {order_ids}",
        )

    for category_id, name in conn.execute(
        "SELECT category_id, name FROM categories WHERE category_id NOT IN (SELECT category_id FROM products)"
    ).fetchall():
        _record_issue(conn, "category", category_id, "category_without_products", f"{name} has no products")

    for order_id, status, tracking in conn.execute(
        "SELECT order_id, status, tracking_code FROM orders WHERE status IN ('shipped', 'delivered')"
    ).fetchall():
        if not tracking or not TRACKING_CODE_PATTERN.match(tracking):
            _record_issue(
                conn, "order", order_id, "invalid_tracking_code", f"{status} order has tracking code {tracking!r}"
            )


def build_database(db_path: Path = DB_PATH, raw_dir: Path = RAW_DATA_DIR) -> Path:
    """(Re)create the SQLite database from the raw CSV files."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()

    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.executescript(SCHEMA)
        category_names = _load_categories(conn, raw_dir)
        _load_products(conn, raw_dir, category_names)
        _load_customers(conn, raw_dir)
        _load_orders(conn, raw_dir)
        _load_promotions(conn, raw_dir)
        _detect_issues(conn)
        conn.commit()
    finally:
        conn.close()
    return db_path


def _is_stale(db_path: Path, raw_dir: Path) -> bool:
    if not db_path.exists():
        return True
    newest_raw = max(path.stat().st_mtime for path in raw_dir.glob("*.csv"))
    return newest_raw > db_path.stat().st_mtime


def get_connection(db_path: Path = DB_PATH, raw_dir: Path = RAW_DATA_DIR) -> sqlite3.Connection:
    """Open the database, building it first if it is missing or older than the CSVs."""
    if _is_stale(db_path, raw_dir):
        build_database(db_path, raw_dir)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


if __name__ == "__main__":
    path = build_database()
    with get_connection(path) as connection:
        counts = {
            table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("categories", "products", "customers", "orders", "order_items", "promotions", "data_issues")
        }
    print(f"Database built at {path}")
    for table, count in counts.items():
        print(f"  {table}: {count}")
