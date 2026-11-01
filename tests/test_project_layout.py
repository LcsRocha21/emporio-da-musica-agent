from pathlib import Path

import emporio_agent

RAW_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"

EXPECTED_FILES = [
    "products.csv",
    "categories.csv",
    "customers.csv",
    "orders.csv",
    "order_items.csv",
    "promotions.csv",
    "store_policies.pdf",
]


def test_package_is_importable():
    assert emporio_agent.__version__


def test_raw_data_files_are_present():
    missing = [name for name in EXPECTED_FILES if not (RAW_DIR / name).is_file()]
    assert not missing, f"Missing files in data/raw: {missing}"
