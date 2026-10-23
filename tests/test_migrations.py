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


def test_migrate_to_3_runs_constraints(tmp_path):
    import sqlite3

    import pytest

    conn = open_db(tmp_path / "state" / "planner.db")
    assert migrate(conn) >= 3
    now = "2026-10-26T00:00:00+00:00"

    def insert(**kw):
        row = {"loop": "morning_brief", "scheduled_for": now, "status": "pending", "created_at": now, **kw}
        cols = ", ".join(row)
        conn.execute(f"INSERT INTO runs ({cols}) VALUES ({', '.join('?' * len(row))})", tuple(row.values()))

    insert()
    r = conn.execute("SELECT * FROM runs").fetchone()
    assert (r["cadence"], r["attempt"], r["resent"], r["merged_run_ids"]) == ("day", 0, 0, "[]")
    with pytest.raises(sqlite3.IntegrityError):  # UNIQUE (loop, cadence, scheduled_for)
        insert()
    insert(loop="review", cadence="week")  # 주기가 다르면 같은 시각이어도 된다
    with pytest.raises(sqlite3.IntegrityError):  # 없는 상태
        insert(scheduled_for="2026-10-27T00:00:00+00:00", status="waiting")
    with pytest.raises(sqlite3.IntegrityError):  # 없는 건너뜀 이유
        insert(scheduled_for="2026-10-27T00:00:00+00:00", status="skipped", skip_reason="bored")
    with pytest.raises(sqlite3.IntegrityError):  # skipped가 아닌데 이유가 있음
        insert(scheduled_for="2026-10-27T00:00:00+00:00", status="done", skip_reason="late")
    insert(scheduled_for="2026-10-27T00:00:00+00:00", status="skipped", skip_reason="late")


def test_migrate_to_4_conditions_constraints(tmp_path):
    import sqlite3

    import pytest

    conn = open_db(tmp_path / "state" / "planner.db")
    assert migrate(conn) >= 4
    now = "2026-10-23T09:00:00+00:00"
    conn.execute("INSERT INTO conditions (date, score, note, recorded_at) VALUES ('2026-10-23', 1, NULL, ?)", (now,))
    conn.execute("INSERT INTO conditions (date, score, note, recorded_at) VALUES ('2026-10-24', 5, '좋음', ?)", (now,))
    for bad in (0, 6, 3.5):
        with pytest.raises(sqlite3.IntegrityError):  # score CHECK 1~5 (정수만)
            conn.execute("INSERT INTO conditions (date, score, recorded_at) VALUES ('2026-10-25', ?, ?)", (bad, now))
    with pytest.raises(sqlite3.IntegrityError):  # date PK
        conn.execute("INSERT INTO conditions (date, score, recorded_at) VALUES ('2026-10-23', 3, ?)", (now,))
    for bad_date in ("bogus", "20261025", "2026-10-25T00:00"):
        with pytest.raises(sqlite3.IntegrityError):  # date는 YYYY-MM-DD
            conn.execute("INSERT INTO conditions (date, score, recorded_at) VALUES (?, 3, ?)", (bad_date, now))
    with pytest.raises(sqlite3.IntegrityError):  # recorded_at NOT NULL
        conn.execute("INSERT INTO conditions (date, score) VALUES ('2026-10-26', 3)")


def test_migrate_to_5_inbound_pending(tmp_path):
    import sqlite3

    import pytest

    conn = open_db(tmp_path / "state" / "planner.db")
    assert migrate(conn) >= 5
    cols = [r["name"] for r in conn.execute("PRAGMA table_info(inbound_pending)")]
    assert cols == [
        "update_id", "text_redacted", "sent_at", "received_at",
        "user_logged", "brain_done", "reply_text", "conversation_id", "attempts",
    ]
    now = "2026-10-23T09:00:00+00:00"
    ins = "INSERT INTO inbound_pending (update_id, text_redacted, sent_at, received_at) VALUES (?, ?, ?, ?)"
    conn.execute(ins, (7, "비번은 [가림]", now, now))
    row = conn.execute("SELECT * FROM inbound_pending").fetchone()
    assert (row["user_logged"], row["brain_done"], row["reply_text"], row["attempts"]) == (0, 0, None, 0)
    with pytest.raises(sqlite3.IntegrityError):  # update_id PK
        conn.execute(ins, (7, "다른 글", now, now))
    # 도구 호출 기록은 받은 메시지(inbound_id)에도 이어지고, 확인 문구를 다시 만들 데이터를 둔다
    log_cols = {r["name"] for r in conn.execute("PRAGMA table_info(tool_events_log)")}
    assert {"inbound_id", "data_json"} <= log_cols
    with pytest.raises(sqlite3.IntegrityError):  # 시각은 NOT NULL
        conn.execute("INSERT INTO inbound_pending (update_id, text_redacted) VALUES (8, '글')")
