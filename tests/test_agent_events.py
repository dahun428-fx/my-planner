"""SP14-01: 사건 기록·받은편지함·관찰 저장소, 라우팅, 지표 영역."""

from datetime import UTC, date, datetime, timedelta

import pytest

from my_planner.clock import FakeClock, to_iso
from my_planner.domain import EVENT_KINDS, EVENT_ORIGINS, INBOX_AGENTS
from my_planner.harness.routing import route
from my_planner.standing.metrics import HEALTH_LOOKS_METRICS, METRICS, metric_area
from my_planner.store.db import transaction
from my_planner.store.repos.agents import AgentsRepo

NOW = datetime(2026, 11, 1, 12, 0, 0, tzinfo=UTC)
TODAY = date(2026, 11, 1)
BOTH = ("mate", "manager")


@pytest.fixture
def repo(conn):
    return AgentsRepo(conn, FakeClock(NOW))


def _count(conn, table):
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def test_domain_names():
    assert len(EVENT_KINDS) == 18 and EVENT_KINDS[0] == "task_done" and EVENT_KINDS[-1] == "handoff"
    assert EVENT_ORIGINS == ("app", "telegram", "scheduler", "brain", "import")
    assert INBOX_AGENTS == ("mate", "manager")


def test_route_table():
    health_both = ("condition_logged", "body_logged", "workout_logged", "event_added", "event_changed", "event_removed")
    manager_only = (
        "task_done", "task_postponed", "task_added", "task_dropped", "habit_checked", "memo_saved",
        "moment_saved", "review_answered", "suggestion_accepted", "suggestion_dismissed",
    )
    seen = set()
    for k in health_both:
        for area in (None, "health", "finance"):
            assert route(k, area) == BOTH
        seen.add(k)
    for k in manager_only:
        for area in (None, "health"):
            assert route(k, area) == ("manager",)
        seen.add(k)
    assert route("measure_saved", "health") == BOTH
    assert route("measure_saved", "finance") == ("manager",)
    assert route("measure_saved", None) == ("manager",)
    seen.add("measure_saved")
    assert route("handoff", None, handoff_to="mate") == ("mate",)
    assert route("handoff", None, handoff_to="manager") == ("manager",)
    seen.add("handoff")
    assert seen == set(EVENT_KINDS)
    with pytest.raises(ValueError):
        route("handoff", None)
    with pytest.raises(ValueError):
        route("task_done", None, handoff_to="mate")


def test_add_event_validates(conn, repo):
    for kw in (
        {"kind": "bogus", "ref": "task:1", "origin": "app"},
        {"kind": "task_done", "ref": "task:1", "origin": "bogus"},
        {"kind": "task_done", "ref": "task:장보기", "origin": "app"},
    ):
        with pytest.raises(ValueError):
            repo.add_event(kw["kind"], kw["ref"], None, kw["origin"], TODAY, to=BOTH, now=NOW)
    assert _count(conn, "agent_events") == 0 and _count(conn, "agent_inbox") == 0


def test_dedupe_within_60s(conn, repo):
    t = datetime(2026, 11, 1, 12, 0, 0, tzinfo=UTC)
    with transaction(conn):
        first = repo.add_event("habit_checked", "habit:3", None, "app", TODAY, to=("manager",), now=t)
        assert first is not None
        assert repo.add_event("habit_checked", "habit:3", None, "app", TODAY, to=("manager",), now=t + timedelta(seconds=59)) is None
        assert repo.add_event("habit_checked", "habit:4", None, "app", TODAY, to=("manager",), now=t + timedelta(seconds=59))
    assert _count(conn, "agent_events") == 2
    with transaction(conn):
        third = repo.add_event("habit_checked", "habit:3", None, "app", TODAY, to=("manager",), now=t + timedelta(seconds=61))
    assert third is not None and third != first
    assert _count(conn, "agent_events") == 3


def test_seen_by_and_events_since(conn, repo):
    with transaction(conn):
        eid = repo.add_event("workout_logged", "workout:1", "health", "app", TODAY, to=BOTH, now=NOW, seen_by="mate")
        repo.add_event("task_done", "task:1", None, "app", TODAY, to=("manager",), now=NOW)
    assert repo.unseen_count("mate", TODAY) == 0
    assert repo.unseen_count("manager", TODAY) == 2
    with transaction(conn):
        assert repo.mark_seen("manager", [eid], NOW) == 1
    got = repo.events_since(["workout_logged"], TODAY)
    assert [e.id for e in got] == [eid] and got[0].kind == "workout_logged" and got[0].area == "health"
    assert repo.events_since(["task_done"], TODAY + timedelta(days=1)) == []


def test_unseen_window_and_mark(conn, repo):
    with transaction(conn):
        for i, d in enumerate((8, 7, 1)):
            repo.add_event("body_logged", f"body_day:2026-10-{i + 1:02d}", None, "app", TODAY - timedelta(days=d),
                           to=BOTH, now=NOW + timedelta(minutes=i))
    got = repo.unseen("mate", TODAY - timedelta(days=7))
    assert [e.day for e in got] == [TODAY - timedelta(days=1), TODAY - timedelta(days=7)]
    assert len(repo.unseen("mate", TODAY - timedelta(days=7), limit=1)) == 1
    with transaction(conn):
        assert repo.mark_seen_before("mate", TODAY - timedelta(days=7), NOW) == 1
        assert repo.mark_seen("mate", [e.id for e in got], NOW) == 2
    assert repo.unseen_count("mate", TODAY - timedelta(days=30)) == 0
    assert repo.unseen_count("manager", TODAY - timedelta(days=30)) == 3


def test_notes_and_handoffs(conn, repo):
    with transaction(conn):
        a = repo.add_note("mate", TODAY, "관찰 하나", 3, ["workout:1"], NOW)
        repo.add_note("mate", TODAY - timedelta(days=1), "관찰 둘", 2, [], NOW)
        repo.add_note("manager", TODAY, "다른 상대", 3, [], NOW)
    assert repo.handoffs_on("mate", TODAY) == 1 and repo.handoffs_on("mate", TODAY - timedelta(days=1)) == 0
    got = repo.notes("mate", TODAY - timedelta(days=1))
    assert [n.text for n in got] == ["관찰 하나", "관찰 둘"] and got[0].id == a
    assert got[0].refs == ("workout:1",) and got[0].shown_at is None
    assert len(repo.notes(None, TODAY - timedelta(days=1))) == 3
    assert len(repo.notes("mate", TODAY - timedelta(days=1), limit=1)) == 1


def test_brief_candidates_two_day_window(conn, repo):
    d = lambda n: TODAY - timedelta(days=n)
    with transaction(conn):
        repo.add_note("mate", d(1), "p2", 2, [], NOW)
        repo.add_note("mate", d(2), "p1", 1, [], NOW)
        repo.add_note("mate", d(3), "old", 2, [], NOW)
        repo.add_note("mate", d(1), "handoff", 3, [], NOW)
        shown = repo.add_note("mate", d(1), "shown", 2, [], NOW)
        assert repo.mark_shown([shown], NOW) == 1
    assert [n.text for n in repo.brief_candidates(TODAY)] == ["p1", "p2"]


def test_prune_keeps_90_30_365(conn, repo):
    d = lambda n: TODAY - timedelta(days=n)
    with transaction(conn):
        old = repo.add_event("task_done", "task:1", None, "app", d(91), to=("manager",), now=NOW)
        keep = repo.add_event("task_done", "task:2", None, "app", d(90), to=("manager",), now=NOW)
        e31 = repo.add_event("task_done", "task:3", None, "app", d(1), to=("manager",), now=NOW)
        e29 = repo.add_event("task_done", "task:4", None, "app", d(1), to=("manager",), now=NOW)
        unread = repo.add_event("task_done", "task:5", None, "app", d(1), to=("manager",), now=NOW)
        repo.mark_seen("manager", [e31], NOW - timedelta(days=31))
        repo.mark_seen("manager", [e29], NOW - timedelta(days=29))
        repo.add_note("mate", d(366), "old", 2, [], NOW)
        repo.add_note("mate", d(365), "keep", 2, [], NOW)
    with transaction(conn):
        assert repo.prune(TODAY, NOW) == {"events": 1, "inbox": 1, "notes": 1}
    ids = {r[0] for r in conn.execute("SELECT id FROM agent_events")}
    assert old not in ids and {keep, e31, e29, unread} <= ids
    inbox = {r[0] for r in conn.execute("SELECT event_id FROM agent_inbox")}
    assert inbox == {keep, e29, unread}
    assert [n.text for n in repo.notes("mate", d(1000))] == ["keep"]


def test_metric_area():
    assert metric_area("body_fat_pct") == "health"
    assert metric_area("salary_krw") == "career"
    assert metric_area("net_worth_krw") == "finance"
    assert metric_area("support_people") == "relationships"
    assert metric_area("cert") == "learning"
    assert metric_area("height_cm") is None and metric_area("family_support") is None
    assert len(HEALTH_LOOKS_METRICS) == 23 and HEALTH_LOOKS_METRICS <= set(METRICS)
    assert all(metric_area(m) == "health" for m in HEALTH_LOOKS_METRICS)


def test_iso_helper_used():
    assert to_iso(NOW).startswith("2026-11-01T12:00:00")
