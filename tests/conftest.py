import sqlite3

import pytest

from emporio_agent import config, data_loader
from emporio_agent.config import RAW_DATA_DIR


@pytest.fixture(scope="session")
def _db_path(tmp_path_factory):
    return data_loader.build_database(tmp_path_factory.mktemp("store") / "store.db", RAW_DATA_DIR)


@pytest.fixture
def store(monkeypatch, _db_path, tmp_path):
    """Point every tool at a throw-away database and handoff log."""

    def _connect(*args, **kwargs):
        conn = sqlite3.connect(_db_path)
        conn.row_factory = sqlite3.Row
        return conn

    monkeypatch.setattr(data_loader, "get_connection", _connect)
    monkeypatch.setattr(config, "HANDOFF_LOG_PATH", tmp_path / "handoffs.jsonl")
    monkeypatch.delenv("EMPORIO_NOW", raising=False)
    return tmp_path


@pytest.fixture
def at(monkeypatch):
    """Freeze the store clock: at("2026-02-20T10:30:00")."""

    def _set(timestamp: str):
        monkeypatch.setenv("EMPORIO_NOW", timestamp)

    return _set

