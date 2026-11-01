"""WorkoutRepo와 021 표의 CHECK (SP12 스펙 6.1, 7.1~7.3, 8.1~8.2)."""

import sqlite3
from datetime import UTC, date, datetime

import pytest

from my_planner.clock import FakeClock
from my_planner.store.db import transaction
from my_planner.store.repos.workout import LogItem, PlanItem, WorkoutRepo

NOW = datetime(2026, 10, 31, 9, 0, tzinfo=UTC)
LATER = datetime(2026, 10, 31, 10, 0, tzinfo=UTC)


@pytest.fixture
def w(conn):
    return WorkoutRepo(conn, FakeClock(NOW))


def item(name="스쿼트", **kw):
    return PlanItem(
        name,
        kw.get("sets", 3),
        kw.get("reps", "8-10"),
        kw.get("weight_kg", 16.0),
        kw.get("minutes"),
        kw.get("note"),
    )


def sessions(label="하체", weekdays=(0, 3)):
    return [
        (label, weekdays, [item()]),
        (
            "걷기",
            None,
            [item("걷기", sets=None, reps=None, weight_kg=None, minutes=30)],
        ),
    ]


def test_replace_plan_roundtrip(w):
    with transaction(w.conn):
        prev, new = w.replace_plan("3분할", "무리하지 않기", sessions(), NOW)
    assert prev is None
    p = w.current_plan()
    assert (
        p is not None
        and p.id == new
        and p.title == "3분할"
        and p.note == "무리하지 않기"
    )
    assert [(s.position, s.label, s.weekdays) for s in p.sessions] == [
        (1, "하체", (0, 3)),
        (2, "걷기", None),
    ]
    assert p.sessions[0].items == (item(),) and p.sessions[1].items[0].minutes == 30
    assert w.plan(new) == p and w.plan(999) is None
    raw = w.conn.execute(
        "SELECT weekdays, items FROM workout_plan_sessions WHERE position = 1"
    ).fetchone()
    assert (
        raw["weekdays"] == "[0, 3]" and "스쿼트" in raw["items"]
    )  # ensure_ascii=False


def test_only_one_current_plan(w):
    with transaction(w.conn):
        _, first = w.replace_plan("A", None, sessions(), NOW)
    with transaction(w.conn):
        prev, second = w.replace_plan("B", None, sessions(), LATER)
    assert prev == first and w.current_plan().id == second
    assert (
        w.conn.execute(
            "SELECT replaced_at FROM workout_plans WHERE id = ?", (first,)
        ).fetchone()[0]
        is not None
    )
    with pytest.raises(sqlite3.IntegrityError):
        w.conn.execute(
            "UPDATE workout_plans SET replaced_at = NULL WHERE id = ?", (first,)
        )


def test_undo_replace_restores_previous(w):
    with transaction(w.conn):
        _, a = w.replace_plan("A", None, sessions(), NOW)
        prev, b = w.replace_plan("B", None, sessions(), LATER)
        w.undo_replace(b, prev, LATER)
    assert w.current_plan().id == a
    with transaction(w.conn):  # 앞 플랜이 없던 경우: 플랜 없음으로
        w.undo_replace(a, None, LATER)
    assert w.current_plan() is None


def test_clear_and_undo_clear(w):
    assert w.clear_plan(NOW) is None
    with transaction(w.conn):
        _, a = w.replace_plan("A", None, sessions(), NOW)
        assert w.clear_plan(LATER) == a
    assert w.current_plan() is None
    with transaction(w.conn):
        w.undo_clear(a)
    assert w.current_plan().id == a


def test_body_notes_crud(w):
    with transaction(w.conn):
        a = w.add_note("injury", "왼쪽 무릎 통증", NOW)
        b = w.add_note("equipment", "덤벨 16kg", LATER)
    assert [n.id for n in w.notes()] == [b.id, a.id] and w.count_notes() == 2
    assert (
        w.find_note("injury", "왼쪽 무릎 통증") == a
        and w.find_note("other", "왼쪽 무릎 통증") is None
    )
    with transaction(w.conn):
        w.update_note(a.id, "other", "무릎 괜찮아짐", LATER)
        w.drop_note(b.id, LATER)
    assert (
        [n.id for n in w.notes()] == [a.id]
        and w.note(a.id).kind == "other"
        and w.note(b.id) is None
    )
    assert w.count_notes() == 1
    with transaction(w.conn):
        w.restore_note(b.id)
    assert w.count_notes() == 2 and w.note(b.id).text == "덤벨 16kg"


def li(name, **kw):
    return LogItem(
        name,
        kw.get("sets"),
        kw.get("reps"),
        kw.get("weight_kg"),
        kw.get("minutes"),
        kw.get("distance_km"),
    )


def test_logs_filter_by_name_and_skip_deleted(w):
    with transaction(w.conn):
        a = w.add_log(
            date(2026, 10, 29),
            "하체",
            None,
            4,
            None,
            [li("스쿼트", sets=5, reps=5, weight_kg=60.0)],
            NOW,
        )
        b = w.add_log(
            date(2026, 10, 30),
            "하체2",
            None,
            None,
            "좋음",
            [li("스쿼트", sets=3, reps=8), li("런지")],
            NOW,
        )
        c = w.add_log(
            date(2026, 10, 30),
            "걷기",
            None,
            None,
            None,
            [li("걷기", minutes=30, distance_km=2.5)],
            NOW,
        )
        w.delete_log(a.id, LATER)
    got = w.logs(date(2026, 10, 1), date(2026, 10, 31), name="스쿼")
    assert [x.id for x in got] == [b.id] and got[0].items[1].name == "런지"
    assert [x.id for x in w.logs(date(2026, 10, 1), date(2026, 10, 31))] == [
        c.id,
        b.id,
    ] or {x.id for x in w.logs(date(2026, 10, 1), date(2026, 10, 31))} == {b.id, c.id}
    assert w.log(a.id) is None and w.log(c.id).items[0].distance_km == 2.5
    assert w.has_log_on(date(2026, 10, 30)) and not w.has_log_on(date(2026, 10, 29))
    assert w.log_days(date(2026, 10, 1), date(2026, 10, 31)) == {date(2026, 10, 30)}
    with transaction(w.conn):
        w.restore_log(a.id)
    assert w.has_log_on(date(2026, 10, 29)) and w.log(a.id).items[0].weight_kg == 60.0


def test_logs_date_desc_and_update(w):
    with transaction(w.conn):
        a = w.add_log(date(2026, 10, 28), "A", None, None, None, [], NOW)
        b = w.add_log(date(2026, 10, 30), "B", None, None, None, [li("x")], NOW)
        w.update_log(
            a.id, LATER, title="A2", effort=3, items=[li("y", reps=10), li("z")]
        )
        w.update_log(b.id, LATER, note="메모")
    assert [x.id for x in w.logs(date(2026, 10, 1), date(2026, 10, 31))] == [b.id, a.id]
    a2 = w.log(a.id)
    assert (a2.title, a2.effort, a2.updated_at) == ("A2", 3, LATER)
    assert [i.name for i in a2.items] == ["y", "z"]
    b2 = w.log(b.id)
    assert b2.note == "메모" and [i.name for i in b2.items] == [
        "x"
    ]  # items 없으면 줄은 그대로
    with pytest.raises(ValueError):
        w.update_log(a.id, LATER, bogus=1)


def test_json_checks(w):
    ins = "INSERT INTO workout_plan_sessions (plan_id, position, label, weekdays, items) VALUES (?, 1, 'x', ?, ?)"
    with transaction(w.conn):
        _, pid = w.replace_plan("A", None, sessions(), NOW)
    with pytest.raises(sqlite3.IntegrityError):
        w.conn.execute(ins.replace("1, 'x'", "5, 'x'"), (pid, None, "[]"))
    with pytest.raises(sqlite3.IntegrityError):
        w.conn.execute(ins.replace("1, 'x'", "6, 'x'"), (pid, None, "not json"))
    with pytest.raises(sqlite3.IntegrityError):
        w.conn.execute(
            ins.replace("1, 'x'", "7, 'x'"), (pid, "{bad", '[{"name": "a"}]')
        )
