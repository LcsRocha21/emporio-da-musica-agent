"""Project-wide paths and clock settings."""

import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW_DATA_DIR = PROJECT_ROOT / "data" / "raw"
DB_PATH = PROJECT_ROOT / "data" / "store.db"

# Campo Grande/MS is on Mato Grosso do Sul time (UTC-4).
STORE_TIMEZONE = ZoneInfo("America/Campo_Grande")


def get_now() -> datetime:
    """Return the current time in the store's timezone.

    The sample orders are dated between 2025 and early 2026, so time-based rules
    (return windows, opening hours) can be tested against a fixed moment by setting
    the EMPORIO_NOW environment variable to an ISO 8601 timestamp, e.g.
    ``EMPORIO_NOW=2026-02-20T10:30:00``. Without a timezone, the store's timezone
    is assumed. When the variable is not set, the real clock is used.
    """
    override = os.getenv("EMPORIO_NOW")
    if override:
        parsed = datetime.fromisoformat(override)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=STORE_TIMEZONE)
    return datetime.now(STORE_TIMEZONE)
