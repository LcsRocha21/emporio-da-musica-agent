"""Helpers shared by all agent tools: database access, money and date formatting."""

import sqlite3
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from emporio_agent import data_loader

CENT = Decimal("0.01")


def connect() -> sqlite3.Connection:
    """Open the store database (built on first use). Callers close it."""
    return data_loader.get_connection()


def to_decimal(value: object) -> Decimal:
    return Decimal(str(value))


def money(value: object) -> Decimal:
    """Round to cents, half up (how prices are normally rounded in Brazil)."""
    return to_decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


def format_brl(value: object) -> str:
    """Format as Brazilian currency: 1234.5 -> 'R$ 1.234,50'."""
    text = f"{money(value):,.2f}"  # 1,234.50
    return "R$ " + text.replace(",", "_").replace(".", ",").replace("_", ".")


def format_date_br(value: str | date | None) -> str | None:
    """'2026-02-28' -> '28/02/2026'."""
    if value is None:
        return None
    parsed = date.fromisoformat(value) if isinstance(value, str) else value
    return parsed.strftime("%d/%m/%Y")
