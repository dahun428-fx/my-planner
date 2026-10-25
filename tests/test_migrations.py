import sqlite3
from pathlib import Path

import pytest

from my_planner.store import db as dbmod
from my_planner.store.db import migrate, open_db


def _migration_count() -> int:
    folder = Path(dbmod.__file__).parent / "migrations"
    return len(list(folder.glob("[0-9][0-9][0-9]_*.sql")))


def test_migrate_fresh_then_again(tmp_path):
    conn = open_db(tmp_path / "state" / "planner.db")
    latest = _migration_count()
    assert latest >= 1

    assert latest == dbmod.LATEST_VERSION
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
    assert migrate(conn, upto=5) == 5  # 006이 통로 열을 더한다(test_migrate_5_to_10_keeps_sp1_rows)
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


NOW = "2026-10-24T01:00:00.000000+00:00"


def test_migrate_5_to_10_keeps_sp1_rows(tmp_path):
    conn = open_db(tmp_path / "state" / "planner.db")
    assert migrate(conn, upto=5) == 5
    conn.execute(
        "INSERT INTO conversations (kind, logical_date, opened_at, last_message_at) VALUES ('chat', '2026-10-24', ?, ?)",
        (NOW, NOW),
    )
    conn.execute(
        "INSERT INTO inbound_pending (update_id, text_redacted, sent_at, received_at) VALUES (7, '꾸민 글', ?, ?)",
        (NOW, NOW),
    )
    conn.execute(
        "INSERT INTO runs (loop, scheduled_for, status, created_at) VALUES ('morning_brief', ?, 'done', ?)", (NOW, NOW)
    )
    conn.execute("INSERT INTO app_state (key, value) VALUES ('installed_at', ?)", (NOW,))
    conn.commit()

    assert migrate(conn) == dbmod.LATEST_VERSION
    c = conn.execute("SELECT * FROM conversations").fetchone()
    assert (c["kind"], c["channel"], c["forked_from"]) == ("chat", "telegram", None)
    p = conn.execute("SELECT * FROM inbound_pending").fetchone()
    assert (p["text_redacted"], p["channel"], p["client_msg_id"], p["checkin_id"]) == ("꾸민 글", "telegram", None, None)
    r = conn.execute("SELECT * FROM runs").fetchone()
    assert (r["status"], r["answered_at"], r["answered_via"]) == ("done", None, None)
    assert conn.execute("SELECT value FROM app_state WHERE key = 'installed_at'").fetchone()[0] == NOW
    tables = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {
        "run_deliveries", "activity", "api_idempotency", "pending_confirms", "push_subscriptions", "app_cards",
        "curve_chapters", "curve_milestones", "curve_ladder_scores", "curve_area_scores", "curve_area_defaults",
        "curve_questions", "status_xp_ledger", "status_titles",
    } <= tables


def _ins(conn, table, **row):
    cols = ", ".join(row)
    conn.execute(f"INSERT INTO {table} ({cols}) VALUES ({', '.join('?' * len(row))})", tuple(row.values()))


def _run(conn):
    _ins(conn, "runs", loop="evening_checkin", scheduled_for=NOW, status="done", created_at=NOW)
    return conn.execute("SELECT max(id) FROM runs").fetchone()[0]


_CHAPTER = {"title": "꾸민 챕터", "start_month": "2020-01", "status": "draft", "origin": "chat",
            "created_at": NOW, "updated_at": NOW}
_MILESTONE = {"date_text": "2021", "precision": "year", "sort_date": "2021-01-01", "kind": "high",
              "title": "꾸민 사건", "status": "draft", "origin": "chat", "created_at": NOW, "updated_at": NOW}
_DELIVERY = {"channel": "telegram", "mode": "full", "status": "sent", "at": NOW}
_ACTIVITY = {"at": NOW, "actor": "user", "channel": "app", "kind": "task_done", "summary": "완료", "risk": "low"}
_CONFIRM = {"token": "ct_x", "action": "drop_task", "args_json": "{}", "summary": "빼기", "origin": "actions",
            "created_at": NOW, "expires_at": NOW}
_XP = {"at": NOW, "logical_date": "2026-10-24", "source_kind": "task_done", "source_ref": "task:1",
       "amount": 10, "label": "할 일 완료"}

BAD_ROWS = [
    ("runs.answered_via", "runs_answered", {"answered_via": "email"}),
    ("conversations.channel", "conversations", {"channel": "email"}),
    ("inbound_pending.channel", "inbound_pending", {"channel": "sms"}),
    ("run_deliveries.channel", "run_deliveries", {"channel": "email"}),
    ("run_deliveries.mode", "run_deliveries", {"mode": "partial"}),
    ("run_deliveries.status", "run_deliveries", {"status": "queued"}),
    ("activity.actor", "activity", {"actor": "robot"}),
    ("activity.channel", "activity", {"channel": "email"}),
    ("activity.risk", "activity", {"risk": "high"}),
    ("api_idempotency.endpoint", "api_idempotency", {"endpoint": "push"}),
    ("pending_confirms.origin", "pending_confirms", {"origin": "web"}),
    ("pending_confirms.resolution", "pending_confirms", {"resolution": "maybe"}),
    ("chapters.title empty", "curve_chapters", {"title": ""}),
    ("chapters.title long", "curve_chapters", {"title": "가" * 101}),
    ("chapters.start_month", "curve_chapters", {"start_month": "2020-1"}),
    ("chapters.end_month", "curve_chapters", {"end_month": "202001"}),
    ("chapters.end before start", "curve_chapters", {"end_month": "2019-12"}),
    ("chapters.certainty", "curve_chapters", {"certainty": "guess"}),
    ("chapters.status", "curve_chapters", {"status": "final"}),
    ("chapters.origin", "curve_chapters", {"origin": "import"}),
    ("milestones.precision", "curve_milestones", {"precision": "week"}),
    ("milestones.kind", "curve_milestones", {"kind": "peak"}),
    ("milestones.kind_certainty", "curve_milestones", {"kind_certainty": "guess"}),
    ("milestones.title", "curve_milestones", {"title": ""}),
    ("milestones.sensitive", "curve_milestones", {"sensitive": 2}),
    ("milestones.certainty", "curve_milestones", {"certainty": "guess"}),
    ("milestones.status", "curve_milestones", {"status": "final"}),
    ("milestones.origin", "curve_milestones", {"origin": "import"}),
    ("milestones.confirmed without at", "curve_milestones", {"status": "confirmed"}),
    ("milestones.draft with confirmed_at", "curve_milestones", {"confirmed_at": NOW}),
    ("ladder.period", "curve_ladder_scores", {"period": "2026-Q4", "now": 5}),
    ("ladder.now range", "curve_ladder_scores", {"period": "2026-10", "now": 11}),
    ("ladder.now real", "curve_ladder_scores", {"period": "2026-10", "now": 5.5}),
    ("ladder.future range", "curve_ladder_scores", {"period": "2026-10", "future": -1}),
    ("ladder.both null", "curve_ladder_scores", {"period": "2026-10"}),
    ("area.period", "curve_area_scores", {"period": "2026-10", "area": "health", "score": 5}),
    ("area.area", "curve_area_scores", {"period": "2026-Q4", "area": "sports", "score": 5}),
    ("area.score 0", "curve_area_scores", {"period": "2026-Q4", "area": "health", "score": 0}),
    ("area.score 11", "curve_area_scores", {"period": "2026-Q4", "area": "health", "score": 11}),
    ("area.quest long", "curve_area_scores",
     {"period": "2026-Q4", "area": "health", "score": 5, "recovery_quest": "가" * 81}),
    ("area_defaults.quest long", "curve_area_defaults", {"area": "health", "recovery_quest": "가" * 81}),
    ("questions.status", "curve_questions", {"text": "꾸민 질문", "status": "done"}),
    ("xp.amount zero", "status_xp_ledger", {"amount": 0}),
    ("xp.amount negative", "status_xp_ledger", {"amount": -5}),
    ("xp.source_kind", "status_xp_ledger", {"source_kind": "streak"}),
]


_BASE = {
    "runs": {"loop": "morning_brief", "scheduled_for": NOW, "status": "done", "created_at": NOW},
    "conversations": {"kind": "chat", "logical_date": "2026-10-24", "opened_at": NOW, "last_message_at": NOW},
    "inbound_pending": {"update_id": 1, "text_redacted": "꾸민 글", "sent_at": NOW, "received_at": NOW},
    "run_deliveries": _DELIVERY,
    "activity": _ACTIVITY,
    "api_idempotency": {"client_msg_id": "u1", "endpoint": "chat", "status_code": 200, "at": NOW},
    "pending_confirms": _CONFIRM,
    "curve_chapters": _CHAPTER,
    "curve_milestones": _MILESTONE,
    "curve_ladder_scores": {"period": "2026-10", "now": 5, "recorded_at": NOW},
    "curve_area_scores": {"period": "2026-Q4", "area": "health", "score": 5, "recorded_at": NOW},
    "curve_area_defaults": {"area": "health", "recovery_quest": "산책 10분", "updated_at": NOW},
    "curve_questions": {"text": "꾸민 질문"},
    "status_xp_ledger": _XP,
}


@pytest.mark.parametrize(("name", "table", "bad"), BAD_ROWS, ids=[b[0] for b in BAD_ROWS])
def test_curve_and_status_checks(tmp_path, name, table, bad):
    conn = open_db(tmp_path / "state" / "planner.db")
    migrate(conn)
    table = "runs" if table == "runs_answered" else table
    base = dict(_BASE[table])
    if table == "run_deliveries":
        base["run_id"] = _run(conn)
    row = {**base, **bad}
    if table == "curve_ladder_scores" and "future" in bad or name == "ladder.both null":
        row.pop("now")  # 그 열 하나만 틀리게(또는 둘 다 비게)
    _ins(conn, table, **base)  # 기준 행은 들어간다: CHECK가 아니면 막히지 않는다
    conn.execute(f"DELETE FROM {table}")
    with pytest.raises(sqlite3.IntegrityError):
        _ins(conn, table, **row)


def test_curve_valid_rows_and_cascade(tmp_path):
    conn = open_db(tmp_path / "state" / "planner.db")
    migrate(conn)
    _ins(conn, "curve_chapters", **_CHAPTER)
    chapter = conn.execute("SELECT id FROM curve_chapters").fetchone()[0]
    _ins(conn, "curve_milestones", **{**_MILESTONE, "chapter_id": chapter})
    _ins(conn, "curve_milestones", **{**_MILESTONE, "status": "confirmed", "confirmed_at": NOW})
    _ins(conn, "curve_ladder_scores", period="2026-10", future=7, recorded_at=NOW)  # 5년 뒤만 먼저
    _ins(conn, "curve_area_scores", period="2026-Q4", area="health", score=10, recorded_at=NOW)
    _ins(conn, "status_xp_ledger", **_XP)
    with pytest.raises(sqlite3.IntegrityError):  # UNIQUE (source_kind, source_ref): 같은 일로 두 번 오르지 않는다
        _ins(conn, "status_xp_ledger", **_XP)
    conn.execute("DELETE FROM curve_chapters WHERE id = ?", (chapter,))  # 챕터 초안을 지우면 사건은 남고 비워진다
    assert conn.execute("SELECT chapter_id FROM curve_milestones ORDER BY id").fetchall()[0][0] is None
    rid = _run(conn)
    _ins(conn, "run_deliveries", run_id=rid, **_DELIVERY)
    with pytest.raises(sqlite3.IntegrityError):  # PK (run_id, channel)
        _ins(conn, "run_deliveries", run_id=rid, **_DELIVERY)


def test_latest_version_no_chat_migration():
    """`POST /chat`(SP3-4 티켓 06)은 마이그레이션을 더하지 않는다: `inbound_pending.conversation_id`는 005부터 있다."""
    assert dbmod.LATEST_VERSION == 15 == _migration_count()


async def test_resubmitted_app_row_keeps_conversation(tmp_path):
    """다시 넣은 앱 행은 `inbound_pending.conversation_id`(005의 열)의 대화로 간다. 닫혔으면 다시 고른 대화로(7.5 M6)."""
    from be_env import BeEnv
    from fakes import FakeTurn
    from test_dispatcher_app_channel import app_message
    from test_dispatcher_messages import kst

    from my_planner.loop.runner import resubmit_inbound

    script = [FakeTurn([], "이어서요."), FakeTurn([], "새 대화예요.")]
    async with BeEnv.start(tmp_path, start=kst(2026, 10, 24, 13, 0), script=script) as env:
        p = env.parts
        m = app_message(env, "하나", None, "cm-keep")
        row = p.state.get_pending_inbound(m.update_ids[0])
        assert row.channel == "app" and row.client_msg_id == "cm-keep" and row.conversation_id == m.conversation_id
        resubmit_inbound(p.state, p.dispatcher)
        await env.drain()
        kept = env.brain.calls[0]["run_ctx"].conversation_id

        closed = app_message(env, "둘", None, "cm-closed")
        p.convs.close(closed.conversation_id)
        resubmit_inbound(p.state, p.dispatcher)
        await env.drain()
        moved = env.brain.calls[1]["run_ctx"].conversation_id
        moved_conv = p.convs.get(moved)

    assert kept == m.conversation_id
    assert moved != closed.conversation_id
    assert moved_conv.channel == "app" and moved_conv.kind.value == "chat" and moved_conv.closed_at is None


# --- 012: 습관과 체크, 원장 CHECK 넓히기 (SP7 스펙 5.1) ---

_LEDGER_ROWS = [
    (7, "2026-10-20T01:00:00+00:00", "2026-10-20", "task_done", "task:1", 5, "health", "할 일 완료"),
    (9, "2026-10-21T01:00:00+00:00", "2026-10-21", "condition", "date:2026-10-21", 2, None, "컨디션"),
    (12, "2026-10-22T01:00:00+00:00", "2026-10-22", "rest_day", "date:2026-10-22", 4, None, "쉬는 날"),
]
_LEDGER_INS = (
    "INSERT INTO status_xp_ledger (id, at, logical_date, source_kind, source_ref, amount, area, label) "
    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
)


def _at_011(tmp_path):
    conn = open_db(tmp_path / "state" / "planner.db")
    assert migrate(conn, upto=11) == 11
    return conn


def test_012_keeps_ledger_rows_and_ids(tmp_path):
    conn = _at_011(tmp_path)
    for row in _LEDGER_ROWS:
        conn.execute(_LEDGER_INS, row)
    conn.commit()
    assert migrate(conn, upto=12) == 12
    got = conn.execute(
        "SELECT id, at, logical_date, source_kind, source_ref, amount, area, label "
        "FROM status_xp_ledger ORDER BY id"
    ).fetchall()
    assert [tuple(r) for r in got] == _LEDGER_ROWS


def test_012_ledger_accepts_habit_check_only_new_kind(tmp_path):
    conn = _at_011(tmp_path)
    migrate(conn)
    row = (1, "2026-10-24T01:00:00+00:00", "2026-10-24", "habit_check", "habit:1:2026-10-24", 3, "health", "습관 체크")
    conn.execute(_LEDGER_INS, row)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(_LEDGER_INS, (2, *row[1:3], "habit_week", "habit:1:2026-W43", 3, "health", "x"))
    with pytest.raises(sqlite3.IntegrityError):  # amount > 0, UNIQUE는 그대로
        conn.execute(_LEDGER_INS, (3, *row[1:5], 0, "health", "x"))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(_LEDGER_INS, (4, *row[1:]))


def test_012_foreign_key_check_and_index(tmp_path):
    conn = _at_011(tmp_path)
    migrate(conn)
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    idx = {r["name"]: r["tbl_name"] for r in conn.execute("SELECT name, tbl_name FROM sqlite_master WHERE type='index'")}
    assert idx["idx_xp_date"] == "status_xp_ledger"
    assert idx["idx_habit_checks_date"] == "habit_checks"
    tables = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "status_xp_ledger_new" not in tables and {"habits", "habit_checks"} <= tables


def test_habits_daily_target_check(tmp_path):
    conn = _at_011(tmp_path)
    migrate(conn)
    ins = (
        "INSERT INTO habits (title, area, kind, target_per_week, sort_order, created_at, updated_at) "
        "VALUES ('운동', 'health', ?, ?, 1, 'a', 'a')"
    )
    with pytest.raises(sqlite3.IntegrityError):  # daily인데 목표
        conn.execute(ins, ("daily", 3))
    with pytest.raises(sqlite3.IntegrityError):  # weekly인데 목표 없음
        conn.execute(ins, ("weekly", None))
    with pytest.raises(sqlite3.IntegrityError):  # 7회는 매일 습관으로
        conn.execute(ins, ("weekly", 7))
    conn.execute(ins, ("daily", None))
    conn.execute(ins, ("weekly", 3))


def test_schema_version_latest(tmp_path):
    conn = open_db(tmp_path / "state" / "planner.db")
    assert migrate(conn) == 15 == dbmod.LATEST_VERSION
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 15


# --- 013: 이룬 순간 (SP8 스펙 6.1) ---

_MOMENT_INS = (
    "INSERT INTO status_moments (date, slot, text, area, sources_json, created_at) VALUES (?, ?, ?, ?, ?, ?)"
)
_AT = "2026-10-25T19:01:00+00:00"


def test_013_moment_checks(tmp_path):
    conn = open_db(tmp_path / "state" / "planner.db")
    migrate(conn)
    ok = ("2026-10-24", 1, "포트폴리오 사례 하나를 끝까지 다듬었어요", "career", '["task:12"]', _AT)
    conn.execute(_MOMENT_INS, ok)
    conn.execute(_MOMENT_INS, ("2026-10-24", 2, "가" * 60, None, "[]", _AT))  # 60자, 영역 없음
    for bad in (
        ("2026-10-24", 3, "가" * 61, None, "[]", _AT),  # 61자
        ("2026-10-24", 3, "", None, "[]", _AT),  # 0자
        ("2026-10-24", 0, "글", None, "[]", _AT),  # slot 0
        ("2026-10-24", 4, "글", None, "[]", _AT),  # slot 4
        ("2026-10-24", 3, "글", "money", "[]", _AT),  # 틀린 영역
        ("2026-1-1", 1, "글", None, "[]", _AT),  # 날짜 모양
        ("2026-10-24", 1, "글", None, "[]", _AT),  # UNIQUE (date, slot)
    ):
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(_MOMENT_INS, bad)
    assert conn.execute("SELECT COUNT(*) FROM status_moments").fetchone()[0] == 2
    idx = {r["name"]: r["tbl_name"] for r in conn.execute("SELECT name, tbl_name FROM sqlite_master WHERE type='index'")}
    assert idx["idx_moments_date"] == "status_moments"


def test_013_day_state_check(tmp_path):
    conn = open_db(tmp_path / "state" / "planner.db")
    migrate(conn)
    ins = "INSERT INTO status_moment_days (date, state, updated_at) VALUES (?, ?, ?)"
    for i, state in enumerate(("pending", "done", "empty", "failed")):
        conn.execute(ins, (f"2026-10-2{i}", state, _AT))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(ins, ("2026-10-24", "skipped", _AT))
    with pytest.raises(sqlite3.IntegrityError):  # 날짜가 PRIMARY KEY
        conn.execute(ins, ("2026-10-20", "done", _AT))
    row = conn.execute("SELECT saved, attempts FROM status_moment_days WHERE date = '2026-10-20'").fetchone()
    assert (row["saved"], row["attempts"]) == (0, 0)


def test_013_ledger_untouched(tmp_path):
    conn = open_db(tmp_path / "state" / "planner.db")
    assert migrate(conn, upto=12) == 12
    for row in _LEDGER_ROWS:
        conn.execute(_LEDGER_INS, row)
    conn.commit()
    before = conn.execute("SELECT sql FROM sqlite_master WHERE name = 'status_xp_ledger'").fetchone()[0]
    assert migrate(conn) == 15
    got = conn.execute(
        "SELECT id, at, logical_date, source_kind, source_ref, amount, area, label "
        "FROM status_xp_ledger ORDER BY id"
    ).fetchall()
    assert [tuple(r) for r in got] == _LEDGER_ROWS
    assert conn.execute("SELECT sql FROM sqlite_master WHERE name = 'status_xp_ledger'").fetchone()[0] == before



# --- 014: 몸 기록 (SP8 스펙 7.1) ---


def test_014_body_checks(tmp_path):
    conn = open_db(tmp_path / "state" / "planner.db")
    migrate(conn)
    ins = "INSERT INTO body_days (date, steps, sleep_minutes, updated_at) VALUES (?, ?, ?, ?)"
    conn.execute(ins, ("2026-10-24", 0, None, _AT))
    conn.execute(ins, ("2026-10-23", 100000, 1440, _AT))
    conn.execute(ins, ("2026-10-22", None, 420, _AT))
    for bad in (
        ("2026-10-21", -1, None, _AT),  # 걸음 −1
        ("2026-10-21", 100001, None, _AT),  # 걸음 100001
        ("2026-10-21", None, 1441, _AT),  # 잠 1441
        ("2026-10-21", None, None, _AT),  # 둘 다 NULL
        ("2026-10-2", 10, None, _AT),  # 날짜 모양
    ):
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(ins, bad)
    with pytest.raises(sqlite3.IntegrityError):  # 날짜가 PRIMARY KEY
        conn.execute(ins, ("2026-10-24", 5, None, _AT))


# --- 015: 히스토리 칸 (SP8 스펙 8.1) ---

_CHAPTER_INS = (
    "INSERT INTO curve_chapters (title, start_month, status, origin, created_at, updated_at) "
    "VALUES (?, ?, 'confirmed', 'seed', ?, ?)"
)
_MILESTONE_INS = (
    "INSERT INTO curve_milestones (date_text, precision, sort_date, kind, title, status, origin, "
    "created_at, confirmed_at, updated_at) VALUES (?, 'year', ?, 'high', ?, 'confirmed', 'seed', ?, ?, ?)"
)


def test_015_area_and_ladder_checks(tmp_path):
    conn = open_db(tmp_path / "state" / "planner.db")
    migrate(conn)
    conn.execute(_CHAPTER_INS, ("챕터", "2020-01", _AT, _AT))
    conn.execute(_MILESTONE_INS, ("2020", "2020-01-01", "사건", _AT, _AT, _AT))
    conn.execute("UPDATE curve_milestones SET area = 'career'")
    conn.execute("UPDATE curve_chapters SET ladder_remembered = 0")
    conn.execute("UPDATE curve_chapters SET ladder_remembered = 10")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE curve_milestones SET area = 'money'")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE curve_chapters SET ladder_remembered = 11")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE curve_chapters SET ladder_remembered = -1")


def test_015_keeps_curve_rows(tmp_path):
    conn = open_db(tmp_path / "state" / "planner.db")
    assert migrate(conn, upto=14) == 14
    conn.execute(_CHAPTER_INS, ("챕터", "2020-01", _AT, _AT))
    conn.execute(_MILESTONE_INS, ("2020", "2020-01-01", "사건", _AT, _AT, _AT))
    conn.commit()
    before_c = conn.execute("SELECT id, title, start_month FROM curve_chapters").fetchall()
    before_m = conn.execute("SELECT id, date_text, kind, title FROM curve_milestones").fetchall()
    assert migrate(conn) == 15
    assert [tuple(r) for r in conn.execute("SELECT id, title, start_month FROM curve_chapters")] == [
        tuple(r) for r in before_c
    ]
    assert [tuple(r) for r in conn.execute("SELECT id, date_text, kind, title FROM curve_milestones")] == [
        tuple(r) for r in before_m
    ]
    assert conn.execute("SELECT ladder_remembered FROM curve_chapters").fetchone()[0] is None
    assert conn.execute("SELECT area FROM curve_milestones").fetchone()[0] is None

def _fake_dir(tmp_path, numbers):
    folder = tmp_path / "mig"
    folder.mkdir()
    for n in numbers:
        (folder / f"{n:03d}_x.sql").write_text(f"CREATE TABLE t{n} (a INTEGER);", encoding="utf-8")
    return folder


def test_gap_in_migration_numbers_refuses(tmp_path, monkeypatch):
    monkeypatch.setattr(dbmod, "MIGRATIONS_DIR", _fake_dir(tmp_path, [*range(1, 13), 16]))
    conn = open_db(tmp_path / "state" / "planner.db")
    with pytest.raises(dbmod.MigrationGapError, match="missing migration 013"):
        migrate(conn)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 0


def test_contiguous_numbers_apply(tmp_path, monkeypatch):
    monkeypatch.setattr(dbmod, "MIGRATIONS_DIR", _fake_dir(tmp_path, range(1, 14)))
    conn = open_db(tmp_path / "state" / "planner.db")
    assert migrate(conn) == 13
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 13


def test_duplicate_migration_number_refuses(tmp_path, monkeypatch):
    folder = _fake_dir(tmp_path, range(1, 14))
    (folder / "013_y.sql").write_text("CREATE TABLE dup (a INTEGER);", encoding="utf-8")
    monkeypatch.setattr(dbmod, "MIGRATIONS_DIR", folder)
    conn = open_db(tmp_path / "state" / "planner.db")
    with pytest.raises(dbmod.MigrationGapError, match="duplicate migration 013"):
        migrate(conn)
