"""SP14-03: 관찰 도구 `write_note`·`hand_off`, 측정값 읽기 `get_measures`, 하루 끝 판단 도구 목록(T6, T10~T12).

도구를 직접 부른다. 글과 값은 꾸며 낸 것이다.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest
from be_env import BeEnv
from test_dispatcher_messages import kst

from my_planner.domain import RunContext
from my_planner.store.repos.agents import AgentsRepo
from my_planner.tools.mcp_adapter import (
    _SPECS,
    APP_ONLY_TOOLS,
    MATE_TOOLS,
    TOOL_NAMES,
    build_planner_tools,
    tool_names_for,
)

MON = kst(2026, 11, 2, 13, 0)  # 월요일 낮, 논리적 오늘 2026-11-02
DAY = date(2026, 11, 2)
GOOD = "이번 주 저녁 일정 5개, 운동 가능한 날은 토요일뿐이에요."
HANDOFF = "체지방 목표를 루틴에 반영할 거리가 있어요."

DAYEND = ["get_mate_context", "list_workouts", "get_measures", "list_events", "find_conversations", "write_note",
          "hand_off"]
MATE_WRITES = {"save_body_note", "drop_body_note", "set_workout_plan", "log_workout", "update_workout_log",
               "delete_workout_log", "record_condition"}

TOO_MANY = "관찰은 한 번에 2개까지예요."
BAD_TEXT = "관찰은 120자 안의 한 줄이에요."
BAD_PRIORITY = "priority는 1(꼭 알림) 또는 2예요."
BAD_REFS = "refs는 근거 참조(예: workout:12) 1~5개예요."
BAD_TO = "넘길 상대는 mate 또는 manager이고, 자기 자신에게는 넘기지 않아요."
HANDOFF_CAP = "넘기기는 하루 2번까지예요."


def _dayend(agent: str = "mate") -> RunContext:
    return RunContext(None, None, kind="dayend", agent=agent, activity_channel="scheduler", in_brain=True,  # type: ignore[arg-type]
                      dayend_day=DAY)


def _user() -> RunContext:
    return RunContext(conversation_id=None, run_id=None, actor="user", channel="app")


def _ok(out: dict[str, Any]) -> dict[str, Any]:
    assert "error" not in out, out
    return out


def _notes(env) -> list[dict[str, Any]]:
    return [dict(r) for r in env.conn.execute("SELECT * FROM agent_notes ORDER BY id")]


def _inbox(env, agent: str) -> list[tuple[str, str]]:
    return [
        (r["kind"], r["ref"])
        for r in env.conn.execute(
            "SELECT e.kind, e.ref FROM agent_inbox i JOIN agent_events e ON e.id = i.event_id WHERE i.agent = ? "
            "ORDER BY e.id",
            (agent,),
        )
    ]


# --- 도구 목록 ---


async def test_dayend_tools_are_read_only(tmp_path):
    names = tool_names_for(RunContext(None, None, kind="dayend", agent="mate"))
    assert names == DAYEND
    assert not set(names) & MATE_WRITES
    assert not set(names) & set(TOOL_NAMES)
    assert not set(names) & (set(APP_ONLY_TOOLS) - {"find_conversations", "list_events"})
    for name in names:
        assert name in _SPECS, name
    async with BeEnv.start(tmp_path, start=MON) as env:
        t = env.parts.tools
        ctx = _dayend()
        assert [x.name for x in build_planner_tools(t, ctx)] == DAYEND
        _ok(t.create_event(_user(), title="가짜 시험", date="2026-11-05", time="14:00"))
        out = _ok(t.list_events(ctx, start="2026-11-02", end="2026-11-08"))
    assert [i["id"] for i in out["items"]] == [1]


async def test_note_tools_only_in_dayend(tmp_path):
    for ctx in (
        RunContext(None, None, agent="mate", channel="app"),
        RunContext(None, None, channel="app"),
        RunContext(None, None, channel="telegram"),
        RunContext(None, None, kind="moments"),
    ):
        names = tool_names_for(ctx)
        assert "write_note" not in names and "hand_off" not in names
    for lst in (TOOL_NAMES, APP_ONLY_TOOLS, MATE_TOOLS):
        assert "write_note" not in lst and "hand_off" not in lst
    async with BeEnv.start(tmp_path, start=MON) as env:
        t = env.parts.tools
        chat = RunContext(1, None, kind="chat", agent="mate", channel="app", in_brain=True, dayend_day=DAY)
        assert "error" in t.write_note(chat, text=GOOD, priority=2, refs=["workout:1"])
        assert "error" in t.hand_off(chat, to="manager", text=HANDOFF, refs=["workout:1"])
        assert _notes(env) == []


# --- write_note ---


async def test_write_note_third_call_rejected(tmp_path, caplog):
    async with BeEnv.start(tmp_path, start=MON) as env:
        t = env.parts.tools
        ctx = _dayend()
        first = _ok(t.write_note(ctx, text=GOOD, priority=2, refs=["event:7", "workout:12"]))
        assert first["ok"] is True
        assert t.write_note(ctx, text="가" * 121, priority=2, refs=["workout:1"]) == {"error": BAD_TEXT}
        _ok(t.write_note(ctx, text="  지난주보다 하체 무게가 조금 올랐어요.  ", priority=1, refs=["workout:1"]))
        assert t.write_note(ctx, text=GOOD, priority=2, refs=["workout:1"]) == {"error": TOO_MANY}
        rows = _notes(env)
        assert ctx.notes_written == 2
        assert [e.kind for e in ctx.events] == ["note_written", "note_written"]
        assert all(set(e.data) == {"id"} for e in ctx.events)
    assert [(r["agent"], r["day"], r["priority"]) for r in rows] == [("mate", "2026-11-02", 2), ("mate", "2026-11-02", 1)]
    assert rows[1]["text"] == "지난주보다 하체 무게가 조금 올랐어요."
    assert rows[0]["id"] == first["id"]
    for rec in caplog.records:
        assert GOOD not in rec.getMessage() and GOOD not in str(rec.__dict__)


@pytest.mark.parametrize("kw", [
    {"text": "오늘 운동 실패예요."},
    {"text": "이번 주 연속 3일 했어요."},
    {"text": "걸음이 50% 줄었어요."},
    {"text": "어제 못 했어요."},
    {"text": "가" * 121},
    {"text": "첫 줄이에요.\n둘째 줄이에요."},
    {"text": "   "},
    {"text": None},
    {"priority": 3},
    {"priority": True},
    {"refs": []},
    {"refs": ["장보기"]},
    {"refs": ["workout:1"] * 6},
    {"refs": "workout:1"},
], ids=lambda kw: next(iter(kw)) + ":" + repr(next(iter(kw.values())))[:12])
async def test_note_rejects_banned_and_shape(tmp_path, kw):
    async with BeEnv.start(tmp_path, start=MON) as env:
        t = env.parts.tools
        ctx = _dayend()
        args = {"text": GOOD, "priority": 2, "refs": ["workout:1"], **kw}
        out = t.write_note(ctx, **args)
        assert "error" in out
        if "text" in kw and isinstance(kw["text"], str) and any(w in kw["text"] for w in ("실패", "연속", "%", "못 했")):
            assert out["error"].startswith("관찰에 쓰지 않는 말이 있어요: ")
        assert _notes(env) == []
        assert ctx.notes_written == 0


# --- hand_off ---


async def test_hand_off_cap_and_inbox(tmp_path):
    async with BeEnv.start(tmp_path, start=MON) as env:
        t = env.parts.tools
        ctx = _dayend()
        assert t.hand_off(ctx, to="mate", text=HANDOFF, refs=["workout:1"]) == {"error": BAD_TO}
        assert t.hand_off(ctx, to="secretary", text=HANDOFF, refs=["workout:1"]) == {"error": BAD_TO}
        a = _ok(t.hand_off(ctx, to="manager", text=HANDOFF, refs=["workout:1"]))
        b = _ok(t.hand_off(ctx, to="manager", text=HANDOFF, refs=["workout:1"]))
        assert t.hand_off(ctx, to="manager", text=HANDOFF, refs=["workout:1"]) == {"error": HANDOFF_CAP}
        assert ctx.notes_written == 0
        notes = _notes(env)
        manager = _inbox(env, "manager")
        mate = _inbox(env, "mate")
        candidates = AgentsRepo(env.conn, env.clock).brief_candidates(DAY)
    assert [r["priority"] for r in notes] == [3, 3]
    assert manager == [("handoff", f"note:{a['id']}"), ("handoff", f"note:{b['id']}")]
    assert mate == []
    assert candidates == []


# --- get_measures ---


async def test_get_measures_health_looks_only(tmp_path):
    async with BeEnv.start(tmp_path, start=MON) as env:
        t = env.parts.tools
        _ok(t.save_measures(_user(), source_kind="manual", rows=[
            {"metric": "body_fat_pct", "value": 22.5, "measured_on": "2026-10-01"},
            {"metric": "body_fat_pct", "value": 20.0, "measured_on": "2026-10-20"},
            {"metric": "salary_krw", "value": 50_000_000, "measured_on": "2026-10-20"},
        ]))
        out = _ok(t.get_measures(_dayend()))
    assert out == {"measures": [{
        "metric": "body_fat_pct", "label": "체지방률", "value": 20.0, "unit": "%", "measured_on": "2026-10-20",
        "reliability": "mid",
    }]}
    assert MATE_TOOLS.index("get_measures") == MATE_TOOLS.index("list_workouts") + 1 == 8
