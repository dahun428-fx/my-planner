"""SP14-02: 쓰기 경로마다 사건 한 줄(같은 트랜잭션), 받은편지함, 출처. 제목·본문·값은 사건에 없다(T1~T4, T14)."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

import pytest
from be_env import BeEnv
from test_dispatcher_messages import kst

from my_planner.domain import RunContext
from my_planner.store.repos.agents import AgentsRepo
from my_planner.tools.actions import ActionRequest

MON = kst(2026, 11, 2, 13, 0)  # 월요일 낮, 논리적 오늘 2026-11-02(2026-Q4)
TODAY = "2026-11-02"


def _user() -> RunContext:
    """앱 `/actions`처럼 사용자가 누른 것."""
    return RunContext(conversation_id=None, run_id=None, actor="user", channel="app")


def _events(env) -> list[tuple[str, str, str | None]]:
    return [tuple(r) for r in env.conn.execute("SELECT kind, ref, area FROM agent_events ORDER BY id")]


def _rows(env, table: str) -> list[dict[str, Any]]:
    return [dict(r) for r in env.conn.execute(f"SELECT * FROM {table} ORDER BY rowid")]


def _inbox(env) -> list[tuple[str, str, bool]]:
    return [
        (r["agent"], r["ref"], r["seen_at"] is not None)
        for r in env.conn.execute(
            "SELECT i.agent, e.ref, i.seen_at FROM agent_inbox i JOIN agent_events e ON e.id = i.event_id "
            "ORDER BY i.event_id, i.agent"
        )
    ]


def _ok(out: dict[str, Any]) -> dict[str, Any]:
    assert "error" not in out, out
    return out


# --- 자리마다 준비와 부르기 ---

def _add(t, areas=("career",), **kw):
    return _ok(t.add_task(_user(), title="가짜 할 일", areas=list(areas), **kw))


def _propose(t, areas=("finance",)):
    return _ok(t.propose_tasks(_user(), tasks=[{"title": "가짜 초안", "areas": list(areas)}]))


def _event(t, **kw):
    return _ok(t.create_event(_user(), **{"title": "가짜 일정", "date": "2026-11-05", "time": "14:00", **kw}))


def _memo(t):
    return _ok(t.create_memo(_user(), body="가짜 메모 본문"))


def _habit(t):
    return _ok(t.add_habit(_user(), title="가짜 습관", area="health", kind="daily"))


def _log(t):
    return _ok(t.log_workout(_user(), title="가짜 운동"))


def _moments_ctx() -> RunContext:
    from datetime import date

    return RunContext(None, None, kind="moments", activity_channel="scheduler", moments_date=date(2026, 11, 1),
                      moments_refs=frozenset({"chat"}))


def _none(t):
    return None


CASES: list[tuple[str, Any, Any, list[tuple[str, str, str | None]]]] = [
    ("add_task", _none, lambda t, s: _add(t), [("task_added", "task:1", "career")]),
    ("confirm_tasks", _propose, lambda t, s: _ok(t.confirm_tasks(_user(), ids=[1])),
     [("task_added", "task:1", "finance")]),
    ("complete_task", lambda t: _add(t, ("health",)), lambda t, s: _ok(t.complete_task(_user(), id=1)),
     [("task_done", "task:1", "health")]),
    ("drop_task_open", _add, lambda t, s: _ok(t.drop_task(_user(), id=1)), [("task_dropped", "task:1", "career")]),
    ("move_task_later", lambda t: _add(t, planned_for="2026-11-03"),
     lambda t, s: _ok(t.move_task(_user(), id=1, planned_for="2026-11-05")),
     [("task_postponed", "task:1", "career")]),
    ("record_condition", _none, lambda t, s: _ok(t.record_condition(_user(), score=3)),
     [("condition_logged", f"checkin:{TODAY}", None)]),
    ("record_area_scores", _none, lambda t, s: _ok(t.record_area_scores(_user(), scores={"career": 7, "health": 6})),
     [("review_answered", "review:2026-Q4:career", "career"), ("review_answered", "review:2026-Q4:health", "health")]),
    ("create_event", _none, lambda t, s: _event(t), [("event_added", "event:1", None)]),
    ("update_event", _event, lambda t, s: _ok(t.update_event(_user(), id=1, title="다른 가짜 일정")),
     [("event_changed", "event:1", None)]),
    ("delete_event_all", _event, lambda t, s: _ok(t.delete_event(_user(), id=1, scope="all")),
     [("event_removed", "event:1", None)]),
    ("delete_event_one", lambda t: _event(t, repeat="daily"),
     lambda t, s: _ok(t.delete_event(_user(), id=1, scope="one", date="2026-11-06")),
     [("event_changed", "event:1", None)]),
    ("create_memo", _none, lambda t, s: _memo(t), [("memo_saved", "memo:1", None)]),
    ("update_memo", _memo, lambda t, s: _ok(t.update_memo(_user(), id=1, body="고친 본문", updated_at=s["updated_at"])),
     [("memo_saved", "memo:1", None)]),
    ("check_habit", _habit, lambda t, s: _ok(t.check_habit(_user(), id=1)), [("habit_checked", "habit:1", "health")]),
    ("record_body_days", _none,
     lambda t, s: _ok(t.record_body_days(_user(), days=[{"date": "2026-11-01", "steps": 5000}])),
     [("body_logged", "body_day:2026-11-01", "health")]),
    ("log_workout", _none, lambda t, s: _log(t), [("workout_logged", "workout:1", "health")]),
    ("update_workout_log", _log, lambda t, s: _ok(t.update_workout_log(_user(), id=1, title="고친 운동")),
     [("workout_logged", "workout:1", "health")]),
    ("save_measures", _none, lambda t, s: _ok(t.save_measures(_user(), rows=[
        {"metric": "body_fat_pct", "value": 17.5, "measured_on": "2026-10-20"},
        {"metric": "net_worth_krw", "value": 10_000_000, "measured_on": "2026-10-20"},
    ], source_kind="manual")),
     [("measure_saved", "measure:1", "health"), ("measure_saved", "measure:2", "finance")]),
    ("save_moments", _none, lambda t, s: _ok(t.save_moments(_moments_ctx(), date="2026-11-01", moments=[
        {"text": "가짜 순간", "area": "learning", "sources": ["chat"]},
    ])), [("moment_saved", "moment:1", "learning")]),
]


@pytest.mark.parametrize(("name", "setup", "call", "want"), CASES, ids=[c[0] for c in CASES])
async def test_write_path_leaves_one_event(tmp_path, name, setup, call, want):
    async with BeEnv.start(tmp_path, start=MON) as env:
        t = env.parts.tools
        s = setup(t)
        env.clock.advance(timedelta(seconds=61))  # 준비가 남긴 같은 사건과 겹치지 않게
        before = len(_events(env))
        call(t, s)
        got = _events(env)[before:]
        inbox = _inbox(env)
    assert len(CASES) == 19
    assert sorted(got) == sorted(want)
    if name == "save_measures":
        assert inbox == [("manager", "measure:1", False), ("mate", "measure:1", False), ("manager", "measure:2", False)]


@pytest.mark.parametrize(("name", "setup", "call"), [
    ("move_earlier", lambda t: _add(t, planned_for="2026-11-05"),
     lambda t: _ok(t.move_task(_user(), id=1, planned_for="2026-11-03"))),
    ("move_clear", lambda t: _add(t, planned_for="2026-11-05"),
     lambda t: _ok(t.move_task(_user(), id=1, planned_for=None))),
    ("move_from_none", _add, lambda t: _ok(t.move_task(_user(), id=1, planned_for="2026-11-05"))),
    ("drop_draft", _propose, lambda t: _ok(t.drop_task(_user(), id=1))),
    ("reopen", lambda t: (_add(t), t.complete_task(_user(), id=1)), lambda t: _ok(t.reopen_task(_user(), id=1))),
    ("uncheck_habit", lambda t: (_habit(t), t.check_habit(_user(), id=1)),
     lambda t: _ok(t.uncheck_habit(_user(), id=1))),
    ("pin_memo", _memo, lambda t: _ok(t.pin_memo(_user(), id=1))),
])
async def test_paths_without_event(tmp_path, name, setup, call):
    async with BeEnv.start(tmp_path, start=MON) as env:
        t = env.parts.tools
        setup(t)
        env.clock.advance(timedelta(seconds=61))
        before = len(_events(env))
        call(t)
        assert _events(env)[before:] == []


async def test_body_days_event_only_on_change(tmp_path):
    async with BeEnv.start(tmp_path, start=MON) as env:
        t = env.parts.tools
        day = [{"date": "2026-11-01", "steps": 5000, "sleep_minutes": 420}]
        _ok(t.record_body_days(_user(), days=day))
        env.clock.advance(timedelta(seconds=61))
        _ok(t.record_body_days(_user(), days=day))
        assert len(_events(env)) == 1
        env.clock.advance(timedelta(seconds=61))
        _ok(t.record_body_days(_user(), days=[{"date": "2026-11-01", "steps": 6000}]))
        assert _events(env) == [("body_logged", "body_day:2026-11-01", "health")] * 2


async def test_own_chat_event_seen_for_self(tmp_path):
    async with BeEnv.start(tmp_path, start=MON) as env:
        t = env.parts.tools
        mate = RunContext(conversation_id=7, run_id=None, channel="app", kind="chat", agent="mate", in_brain=True)
        _ok(t.log_workout(mate, title="가짜 운동"))
        sec = RunContext(conversation_id=8, run_id=None, channel="app", kind="chat", in_brain=True)
        _ok(t.add_task(sec, title="가짜 할 일", areas=["career"]))
        assert _inbox(env) == [
            ("manager", "workout:1", False), ("mate", "workout:1", True), ("manager", "task:1", False),
        ]


async def test_events_routed_to_inbox(tmp_path):
    async with BeEnv.start(tmp_path, start=MON) as env:
        t = env.parts.tools
        _log(t)
        assert [a for a, _, _ in _inbox(env)] == ["manager", "mate"]
        _memo(t)
        assert _inbox(env)[2:] == [("manager", "memo:1", False)]


async def test_rollback_leaves_no_event(tmp_path, monkeypatch):
    async with BeEnv.start(tmp_path, start=MON) as env:
        t = env.parts.tools
        _add(t)
        env.clock.advance(timedelta(seconds=61))
        before, inbox = _events(env), _inbox(env)

        def boom(*a, **kw):
            raise RuntimeError("가짜 실패")

        monkeypatch.setattr(t, "_grant", boom)
        with pytest.raises(RuntimeError):
            t.complete_task(_user(), id=1)
        assert env.conn.execute("SELECT status FROM tasks WHERE id = 1").fetchone()[0] == "open"
        assert _events(env) == before == [("task_added", "task:1", "career")]
        assert _inbox(env) == inbox


async def test_event_failure_rolls_back_write(tmp_path, monkeypatch):
    async with BeEnv.start(tmp_path, start=MON) as env:
        t = env.parts.tools

        def boom(*a, **kw):
            raise RuntimeError("가짜 실패")

        monkeypatch.setattr(AgentsRepo, "add_event", boom)
        with pytest.raises(RuntimeError):
            t.add_task(_user(), title="가짜 할 일", areas=["career"])
        assert env.conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 0
        assert env.conn.execute("SELECT COUNT(*) FROM activity").fetchone()[0] == 0


async def test_events_have_ref_only_no_titles(tmp_path, caplog):
    caplog.set_level(logging.DEBUG)
    secrets = ("비밀제목XYZ", "비밀본문XYZ", "비밀일정XYZ")
    async with BeEnv.start(tmp_path, start=MON) as env:
        t = env.parts.tools
        _ok(t.add_task(_user(), title=secrets[0], areas=["career"]))
        _ok(t.create_memo(_user(), body=secrets[1]))
        _ok(t.create_event(_user(), title=secrets[2], date="2026-11-05", time="14:00"))
        cells = [str(v) for table in ("agent_events", "agent_inbox") for r in _rows(env, table) for v in r.values()]
        assert len(_events(env)) == 3
    text = "\n".join(cells) + "\n" + "\n".join(f"{r.getMessage()} {r.__dict__}" for r in caplog.records)
    for s in secrets:
        assert s not in text


async def test_quick_toggle_is_one_event(tmp_path):
    async with BeEnv.start(tmp_path, start=MON) as env:
        t = env.parts.tools
        _habit(t)
        _ok(t.check_habit(_user(), id=1))
        _ok(t.uncheck_habit(_user(), id=1))
        env.clock.advance(timedelta(seconds=10))
        _ok(t.check_habit(_user(), id=1))
        assert _events(env) == [("habit_checked", "habit:1", "health")]
        env.clock.advance(timedelta(seconds=61))
        _ok(t.uncheck_habit(_user(), id=1))
        _ok(t.check_habit(_user(), id=1))
        assert len(_events(env)) == 2
        # 받은 쪽이 원문을 읽으면 지금 상태(체크됨)
        assert env.conn.execute("SELECT COUNT(*) FROM habit_checks WHERE habit_id = 1").fetchone()[0] == 1


def _origins(env) -> list[str]:
    return [r[0] for r in env.conn.execute("SELECT origin FROM agent_events ORDER BY id")]


async def test_origin_by_path(tmp_path):
    async with BeEnv.start(tmp_path, start=MON) as env:
        t = env.parts.tools
        apply = env.parts.dispatcher.apply_action
        status, _ = await env.action("add_task", {"title": "가짜 앱", "areas": ["career"]})
        assert status == 200
        r = apply(ActionRequest("add_task", {"title": "가짜 버튼", "areas": ["career"]}, actor="user",
                                channel="telegram", client_msg_id="tg-1"))
        assert r.status == "applied", r
        _ok(t.add_task(RunContext(conversation_id=7, run_id=None, channel="app", in_brain=True),
                       title="가짜 두뇌", areas=["career"]))
        _ok(t.add_task(RunContext(None, None, actor="secretary", activity_channel="scheduler"),
                       title="가짜 작업", areas=["career"]))
        r = apply(ActionRequest("record_body_days", {"days": [{"date": "2026-11-01", "steps": 4000}]}, actor="user",
                                channel="app", endpoint="body"))
        assert r.status == "applied", r
        assert _origins(env) == ["app", "telegram", "brain", "scheduler", "app"]


async def test_undo_keeps_event(tmp_path):
    async with BeEnv.start(tmp_path, start=MON) as env:
        _add(env.parts.tools)
        env.clock.advance(timedelta(seconds=61))
        status, _ = await env.action("complete_task", {"id": 1})
        assert status == 200
        aid = env.conn.execute("SELECT id FROM activity WHERE kind = 'task_completed'").fetchone()[0]
        n = len(_events(env))
        env.clock.advance(timedelta(seconds=5))
        resp = await env.post(f"/activity/{aid}/undo", json={"client_msg_id": "undo-1"})
        assert resp.status == 200, await resp.text()
        assert env.conn.execute("SELECT status FROM tasks WHERE id = 1").fetchone()[0] == "open"
        assert len(_events(env)) == n
        assert _events(env)[-1] == ("task_done", "task:1", "career")
