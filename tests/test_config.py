from datetime import datetime

from emporio_agent.config import STORE_TIMEZONE, get_now


def test_get_now_uses_real_clock_by_default(monkeypatch):
    monkeypatch.delenv("EMPORIO_NOW", raising=False)
    now = get_now()
    assert now.tzinfo is not None
    assert abs((datetime.now(STORE_TIMEZONE) - now).total_seconds()) < 5


def test_get_now_can_be_overridden_with_naive_timestamp(monkeypatch):
    monkeypatch.setenv("EMPORIO_NOW", "2026-02-20T10:30:00")
    now = get_now()
    assert (now.year, now.month, now.day, now.hour) == (2026, 2, 20, 10)
    assert now.utcoffset().total_seconds() == -4 * 3600


def test_get_now_respects_explicit_offset(monkeypatch):
    monkeypatch.setenv("EMPORIO_NOW", "2026-02-20T10:30:00+00:00")
    assert get_now().utcoffset().total_seconds() == 0
