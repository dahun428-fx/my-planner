"""PanelRepo: 내가 한 말, 패널 제안, 예측, 인생 리포트 (SP15 스펙 5.4, 7.1, 9.1, 10)."""

from datetime import UTC, date, datetime, timedelta

import pytest

from my_planner.clock import FakeClock
from my_planner.store.db import transaction
from my_planner.store.migrations.hooks import SEED_DECISION_KEY, SEED_DECISION_TEXT
from my_planner.store.repos.panel import PanelRepo

NOW = datetime(2026, 11, 2, 9, 0, tzinfo=UTC)
TODAY = date(2026, 11, 2)


@pytest.fixture
def p(conn):
    return PanelRepo(conn, FakeClock(NOW))


def _conv(conn):
    at = NOW.isoformat()
    with transaction(conn):
        return conn.execute(
            "INSERT INTO conversations (kind, logical_date, opened_at, last_message_at, agent) "
            "VALUES ('chat', '2026-11-02', ?, ?, 'manager')",
            (at, at),
        ).lastrowid


def _suggest(p, *, kind="task", area="career", week="2026-W45", per_week=None, conversation_id=None, at=NOW):
    with transaction(p.conn):
        return p.add_suggestion(
            conversation_id=conversation_id, kind=kind, title="가짜 제안", area=area, size_min=30, per_week=per_week,
            due_hint=date(2026, 11, 9), experts=["career", "finance"],
            evidence=[{"type": "record", "ref": "task:1", "note": "가짜 근거"}], week=week, now=at,
        )


def test_statements_active_and_retire(p):
    seed = p.decision(SEED_DECISION_KEY)
    assert seed is not None and seed.text == SEED_DECISION_TEXT and seed.kind == "decision" and seed.area == "career"
    with transaction(p.conn):
        b = p.add_statement("preference", "health", "가짜 선호", now=NOW)
        c = p.add_statement("fact", None, "가짜 사실", source_ref="conversation:1", now=NOW + timedelta(minutes=1))
    assert [s.id for s in p.active_statements()] == [seed.id, b, c]
    assert [s.id for s in p.active_statements(["fact"])] == [c]
    assert p.find_active("preference", "health", "가짜 선호").id == b
    assert p.find_active("preference", None, "가짜 선호") is None
    with transaction(p.conn):
        assert p.retire(b, NOW) is True
        assert p.retire(b, NOW) is False
    assert [s.id for s in p.active_statements()] == [seed.id, c]
    assert p.statement(b).retired_at == NOW
    assert p.find_active("preference", "health", "가짜 선호") is None
    with transaction(p.conn):
        assert p.retire(seed.id, NOW) is True
    assert p.decision(SEED_DECISION_KEY) is None
    with transaction(p.conn):
        assert p.unretire(b) is True
        assert p.unretire(b) is False
        assert p.unretire(seed.id) is True
    assert [s.id for s in p.active_statements()] == [seed.id, b, c]
    assert p.statement(c).source_ref == "conversation:1"
    assert p.statement(9999) is None


def test_suggestion_round_trip(p, conn):
    assert p.first_week() is None
    cid = _conv(conn)
    sid = _suggest(p, conversation_id=cid)
    s = p.suggestion(sid)
    assert s.experts == ("career", "finance")
    assert s.evidence[0]["ref"] == "task:1" and s.evidence[0]["note"] == "가짜 근거"
    assert (s.state, s.conversation_id, s.per_week, s.due_hint, s.decided_at) == ("proposed", cid, None, date(2026, 11, 9), None)
    assert s.created_at == NOW
    assert p.count_in_week("2026-W45") == 1 and p.count_in_week("2026-W46") == 0
    assert p.first_week() == "2026-W45"
    later = NOW + timedelta(hours=1)
    with transaction(conn):
        assert p.set_state(sid, "accepted", result_ref="task:9", now=later) is True
    s = p.suggestion(sid)
    assert (s.state, s.result_ref, s.decided_at) == ("accepted", "task:9", later)
    with transaction(conn):
        assert p.set_state(sid, "done", now=later + timedelta(days=1), decided=False) is True
    s = p.suggestion(sid)
    assert (s.state, s.result_ref, s.decided_at) == ("done", "task:9", later)  # 다른 칸은 그대로
    assert p.set_state(9999, "done", now=later) is False


def test_suggestion_queries(p):
    old = _suggest(p, week="2026-W44", at=NOW - timedelta(days=7))
    habit = _suggest(p, kind="habit", per_week=3, area="health", at=NOW - timedelta(days=1))
    new = _suggest(p, at=NOW)
    assert p.suggestion(habit).per_week == 3
    assert p.first_week() == "2026-W44"
    assert [s.id for s in p.suggestions()] == [new, habit, old]
    assert [s.id for s in p.suggestions(since=TODAY - timedelta(days=1))] == [new, habit]
    assert sorted(s.id for s in p.in_weeks(["2026-W44", "2026-W45"])) == [old, habit, new]
    assert p.in_weeks([]) == []
    assert p.latest_in_area("career").id == new
    assert p.latest_in_area("career", exclude_id=new).id == old
    assert p.latest_in_area("finance") is None
    with transaction(p.conn):
        p.set_state(old, "dismissed", dismiss_reason="no_time", now=NOW)
    assert [s.id for s in p.suggestions(state="dismissed")] == [old]
    assert p.suggestion(old).dismiss_reason == "no_time"
    assert [s.id for s in p.dismissed("career", "no_time", NOW - timedelta(days=30))] == [old]
    assert p.dismissed("career", "too_big", NOW - timedelta(days=30)) == []
    assert p.dismissed("career", "no_time", NOW + timedelta(seconds=1)) == []


def test_predictions_due_and_count(p, conn):
    cid = _conv(conn)
    with transaction(conn):
        a = p.add_prediction("weight_kg", 70.5, TODAY - timedelta(days=1), conversation_id=cid, now=NOW)
        b = p.add_prediction("axis:career", 60.0, TODAY + timedelta(days=1), conversation_id=cid,
                             now=NOW + timedelta(minutes=1))
    assert p.count_for_conversation(cid) == 2
    assert p.count_for_conversation(cid + 1) == 0
    due = p.due_unchecked(TODAY)
    assert [x.id for x in due] == [a] and due[0].predicted == 70.5 and due[0].conversation_id == cid
    with transaction(conn):
        p.set_actual(a, 71.0, NOW)
    assert p.due_unchecked(TODAY) == []
    recent = p.recent_predictions()
    assert [x.id for x in recent] == [b, a]
    assert (recent[1].actual, recent[1].checked_at) == (71.0, NOW)
    assert [x.id for x in p.recent_predictions(limit=1)] == [b]


def test_reports(p):
    assert p.reports() == [] and p.report(1) is None
    with transaction(p.conn):
        a = p.add_report('{"summary": "가짜"}', NOW)
        b = p.add_report("{}", NOW + timedelta(days=1))
    assert p.reports() == [(b, NOW + timedelta(days=1)), (a, NOW)]
    assert p.report(a) == (a, NOW, '{"summary": "가짜"}')
