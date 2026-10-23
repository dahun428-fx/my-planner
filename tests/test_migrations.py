from pathlib import Path

from my_planner.store import db as dbmod
from my_planner.store.db import migrate, open_db


def _migration_count() -> int:
    folder = Path(dbmod.__file__).parent / "migrations"
    return len(list(folder.glob("[0-9][0-9][0-9]_*.sql")))


def test_migrate_fresh_then_again(tmp_path):
    conn = open_db(tmp_path / "state" / "planner.db")
    latest = _migration_count()
    assert latest >= 1

    assert migrate(conn) == latest
    assert conn.execute("PRAGMA user_version").fetchone()[0] == latest
    assert migrate(conn) == latest
    assert conn.execute("PRAGMA user_version").fetchone()[0] == latest

    assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    tables = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"conversations", "app_state", "usage_state", "telegram_updates"} <= tables


def test_migrate_to_2_with_constraints(tmp_path):
    import sqlite3

    import pytest

    conn = open_db(tmp_path / "state" / "planner.db")
    assert migrate(conn) >= 2
    now = "2026-10-23T00:00:00+00:00"
    conn.execute(
        "INSERT INTO tasks (title, status, created_at, updated_at) VALUES ('가', 'open', ?, ?)",
        (now, now),
    )
    tables = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"tasks", "task_areas", "task_events", "priorities", "tool_events_log"} <= tables

    with pytest.raises(sqlite3.IntegrityError):  # rank 4
        conn.execute("INSERT INTO priorities (cadence, period, rank, task_id) VALUES ('day', '2026-10-23', 4, 1)")
    with pytest.raises(sqlite3.IntegrityError):  # 없는 영역
        conn.execute("INSERT INTO task_areas (task_id, area) VALUES (1, 'sports')")
    with pytest.raises(sqlite3.IntegrityError):  # open인데 completed_at
        conn.execute(
            "INSERT INTO tasks (title, status, completed_at, created_at, updated_at) "
            "VALUES ('나', 'open', ?, ?, ?)",
            (now, now, now),
        )
