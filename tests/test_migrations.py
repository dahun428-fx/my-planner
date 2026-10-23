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
