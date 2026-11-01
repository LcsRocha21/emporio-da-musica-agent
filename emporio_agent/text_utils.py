"""Small text helpers shared by the data layer and the agent tools."""

import re
import unicodedata


def normalize_text(text: str | None) -> str:
    """Lowercase, strip accents and collapse whitespace.

    Used for accent-insensitive search: "Violão Aço" and "violao aco" match.
    """
    if not text:
        return ""
    decomposed = unicodedata.normalize("NFKD", text)
    without_accents = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", without_accents).strip().lower()


def digits_only(text: str | None) -> str:
    """Keep only the digits of a string (phone numbers, order ids...)."""
    return re.sub(r"\D", "", text or "")
