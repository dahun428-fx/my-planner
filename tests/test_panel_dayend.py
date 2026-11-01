"""SP15-14: 하루 끝 — 라이프 매니저 판단, 제안·예측 코드 단계, 넘김 글(T6, T9, 스펙 1장 12·13, 7.1, 7.3, 9.1).

`BeEnv` + `FakeBrain`. 글과 값은 모두 꾸며 낸 것이다.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from be_env import BeEnv
from fakes import FakeTurn
from test_dispatcher_messages import kst

from my_planner.domain import RunContext
from my_planner.harness import dayend
from my_planner.harness import prompts as prompt_files
from my_planner.harness.inbox import event_line, inbox_block
from my_planner.harness.manager_context import build_manager_preamble
from my_planner.panel import lifecycle, predictions
from my_planner.panel.budget import BUDGET_KEY
from my_planner.panel.predictions import PREDICTION_WINDOW_DAYS
from my_planner.standing import service as standing_service
from my_planner.store.db import transaction
from my_planner.store.repos.agents import AgentEvent
from my_planner.store.repos.standing import StandingRepo
from my_planner.tools.mcp_adapter import (
    _SPECS,
    DAYEND_READ_TOOLS,
    PANEL_WRITE_TOOLS,
    REPORT_TOOLS,
    tool_names_for,
)

WED = kst(2026, 11, 4, 12, 0)  # 논리적 오늘 2026-11-04(수), 2026-W45
TODAY = date(2026, 11, 4)
EV = [{"type": "external", "ref": "bench:income", "note": "가짜 기준"}]
USER = RunContext(None, None, actor="user", channel="app")
HANDOFF = "가짜 넘김 글이에요."


def _suggest(env, *, kind: str = "task", title: str = "가짜 제안", per_week: int | None = None, week: str = "2026-W45",
             created=None) -> int:
    with transaction(env.conn):
        return env.parts.panel.add_suggestion(
            conversation_id=None, kind=kind, title=title, area="career", size_min=30, per_week=per_week,
            due_hint=None, experts=["career"], evidence=EV, week=week, now=created or env.clock.now(),
        )


def _steps(env, today: date = TODAY) -> None:
    dayend.run_code_steps(env.conn, env.clock, today)


def _state(env, sid: int) -> tuple[str, Any]:
    s = env.parts.panel.suggestion(sid)
    return s.state, s.dismiss_reason


async def _accept(env, sid: int) -> str:
    status, body = await env.action("accept_suggestion", {"id": sid})
    assert status == 200 and body["status"] == "applied", body
    return body["result"]["result_ref"]


def _id(ref: str) -> int:
    return int(ref.split(":")[1])


# --- 제안 상태 (T6, 7.1) ---


async def test_suggestion_lifecycle(tmp_path):
    async with BeEnv.start(tmp_path, start=WED) as env:
        a, b = _suggest(env, title="가짜 하나"), _suggest(env, title="가짜 둘")
        h = _suggest(env, kind="habit", title="가짜 습관", per_week=3)
        old = _suggest(env, title="가짜 오래됨", week="2026-W44", created=WED - timedelta(days=8))
        young = _suggest(env, title="가짜 덜 오래됨", created=WED - timedelta(days=6))
        ta, tb, hb = [await _accept(env, s) for s in (a, b, h)]
        decided = env.parts.panel.suggestion(b).decided_at
        env.clock.advance(minutes=5)
        t = env.parts.tools
        assert "error" not in t.complete_task(USER, id=_id(ta))
        assert "error" not in t.move_task(USER, id=_id(tb), planned_for="2026-11-06")
        assert "error" not in t.check_habit(USER, id=_id(hb))
        _steps(env)
        first = [_state(env, s)[0] for s in (a, b, h, old, young)]
        env.clock.advance(minutes=5)
        assert "error" not in t.complete_task(USER, id=_id(tb))
        _steps(env)
        after = env.parts.panel.suggestion(b)
        expired = env.parts.panel.suggestion(old)
    assert first == ["done", "postponed", "done", "expired", "proposed"]
    assert after.state == "done" and after.decided_at == decided  # 처음 정한 때 그대로
    assert expired.decided_at is not None


async def test_dropped_task_closes_suggestion(tmp_path):
    async with BeEnv.start(tmp_path, start=WED) as env:
        sid = _suggest(env)
        ref = await _accept(env, sid)
        before = env.conn.execute("SELECT COUNT(*) FROM owner_statements").fetchone()[0]
        env.clock.advance(minutes=1)
        assert "error" not in env.parts.tools.drop_task(USER, id=_id(ref))
        _steps(env)
        got = _state(env, sid)
        statements = env.conn.execute("SELECT COUNT(*) FROM owner_statements").fetchone()[0]
    assert got == ("dismissed", "none")
    assert statements == before  # 거절 쪽으로 세도 "내가 한 말"은 생기지 않는다


async def test_lifecycle_log_counts_only(tmp_path, caplog):
    import logging

    caplog.set_level(logging.INFO, logger="my_planner.panel.lifecycle")
    async with BeEnv.start(tmp_path, start=WED) as env:
        _suggest(env, title="가짜 오래됨", created=WED - timedelta(days=8))
        _steps(env)
    (rec,) = [r for r in caplog.records if r.getMessage() == "panel_suggestions_updated"]
    assert rec.expired == 1 and rec.done == 0 and "가짜" not in str(rec.__dict__)


# --- 예측 (T9, 9.1) ---


def _measure(env, metric: str, value: Any, on: date) -> int:
    with transaction(env.conn):
        return StandingRepo(env.conn, env.clock).add(metric, value, on, "import", None, "high", env.clock.now())


def _predict(env, metric: str, predicted: float, due: date) -> int:
    with transaction(env.conn):
        return env.parts.panel.add_prediction(metric, predicted, due, conversation_id=None, now=env.clock.now())


def _pred(env, pid: int):
    (p,) = [p for p in env.parts.panel.recent_predictions(100) if p.id == pid]
    return p


async def test_predictions_check(tmp_path):
    async with BeEnv.start(tmp_path, start=WED) as env:
        y = TODAY - timedelta(days=1)
        _measure(env, "profile_birth_year", 1992, date(2026, 1, 1))
        _measure(env, "profile_sex", "m", date(2026, 1, 1))
        filled = _predict(env, "waist_cm", 80.0, y)
        _measure(env, "waist_cm", 90.0, y - timedelta(days=30))  # 창 밖
        _measure(env, "waist_cm", 82.5, y - timedelta(days=10))
        waiting = _predict(env, "grip_rel_pct", 50.0, y)
        _measure(env, "grip_rel_pct", 40.0, y - timedelta(days=20))
        closed = _predict(env, "ldl", 100.0, TODAY - timedelta(days=PREDICTION_WINDOW_DAYS + 1))
        future = _predict(env, "bp_sys", 120.0, TODAY + timedelta(days=1))
        axis = _predict(env, "axis:health", 60.0, y)
        _measure(env, "body_fat_pct", 21.5, y - timedelta(days=3))
        expect_health = standing_service.current(env.conn, env.clock, TODAY).scores["national"]["health"].score
        _steps(env)
        got = {k: _pred(env, p) for k, p in
               {"filled": filled, "waiting": waiting, "closed": closed, "future": future, "axis": axis}.items()}
        closed_at = got["closed"].checked_at
        env.clock.advance(days=1)
        _steps(env, TODAY + timedelta(days=1))  # 닫힌 줄은 다시 보지 않는다
        again = _pred(env, closed)
        preamble = build_manager_preamble(
            env.conn, env.clock, now=env.clock.now(), tz=env.settings.timezone, boundary=env.settings.day_boundary,
        )
    assert (got["filled"].actual, got["filled"].checked_at is not None) == (82.5, True)
    assert (got["waiting"].actual, got["waiting"].checked_at) == (None, None)
    assert got["closed"].actual is None and closed_at is not None
    assert again.checked_at == closed_at
    assert (got["future"].actual, got["future"].checked_at) == (None, None)
    assert got["axis"].actual == float(expect_health)
    block = preamble.split("## 예측\n", 1)[1].split("\n\n", 1)[0]
    assert "ldl" not in block
    assert "grip_rel_pct 예측 50 · 기한" in block and "측정 필요" in block


async def test_predictions_log_counts_only(tmp_path, caplog):
    import logging

    caplog.set_level(logging.INFO, logger="my_planner.panel.predictions")
    async with BeEnv.start(tmp_path, start=WED) as env:
        _predict(env, "waist_cm", 80.0, TODAY - timedelta(days=1))
        _measure(env, "waist_cm", 82.5, TODAY - timedelta(days=2))
        _predict(env, "ldl", 100.0, TODAY - timedelta(days=30))
        _steps(env)
    (rec,) = [r for r in caplog.records if r.getMessage() == "panel_predictions_checked"]
    assert (rec.filled, rec.closed) == (1, 1)
    assert "82.5" not in str(rec.__dict__) and "waist" not in str(rec.__dict__)


# --- 코드 단계 순서와 주간 제안 수 (T4·T5) ---


async def test_code_steps_order(tmp_path):
    assert [s.__name__ for s in dayend.DAYEND_CODE_STEPS] == ["update_suggestions", "check_predictions", "settle_week"]
    assert dayend.DAYEND_CODE_STEPS[:2] == [lifecycle.update_suggestions, predictions.check_predictions]
    mon = kst(2026, 11, 2, 4, 0)
    async with BeEnv.start(tmp_path, start=mon, dayend=True) as env:
        env.parts.runner.checkins = False
        first = _suggest(env, title="가짜 첫 제안", week="2026-W40", created=kst(2026, 10, 1, 12, 0))
        with transaction(env.conn):
            env.parts.panel.set_state(first, "dismissed", now=kst(2026, 10, 2, 12, 0), dismiss_reason="none")
            env.parts.tools.state.set(BUDGET_KEY.format(week="2026-W44"), "2")
        olds = [_suggest(env, title=f"가짜 {n}", week="2026-W43", created=kst(2026, 10, 25, 12, 0)) for n in "abc"]
        env.clock.set(kst(2026, 11, 2, 4, 1))
        await env.tick()
        states = {_state(env, s)[0] for s in olds}
        budget = env.parts.tools.state.get(BUDGET_KEY.format(week="2026-W45"))
    assert states == {"expired"}
    assert budget == "1"  # 만료 셋이 창에 들어 거절률 1.0 → 2 − 1


# --- 도구와 지시문 ---


def test_manager_dayend_tools_and_prompt():
    names = tool_names_for(RunContext(None, None, kind="dayend", agent="manager"))
    assert DAYEND_READ_TOOLS["manager"] == [
        "list_tasks", "list_events", "list_habits", "read_conditions", "read_body_days", "list_workouts",
        "read_measures_all", "list_statements", "read_panel_results", "find_conversations",
    ]
    assert names == [*DAYEND_READ_TOOLS["manager"], "write_note", "hand_off"]
    assert set(names) <= set(_SPECS)
    assert set(names) & {*PANEL_WRITE_TOOLS, *REPORT_TOOLS} == set()
    assert not {n for n in names if n.startswith(("propose_", "add_", "save_", "record_", "complete_", "ui_"))}
    assert dayend.DAYEND_AGENTS == ("mate", "manager")
    assert dayend.dayend_system_prompt("manager") == (
        f"{prompt_files.load('manager.md')}\n\n{prompt_files.load('agent_dayend.md')}"
    )


# --- 넘김 글 ---


def test_event_line_handoff_text():
    from my_planner.clock import from_iso

    e = AgentEvent(1, from_iso("2026-11-01T00:00:00Z"), date(2026, 11, 1), "handoff", "note:3", None, "brain")
    assert event_line(e) == "- handoff note:3 · 2026-11-01"
    assert event_line(e, HANDOFF) == f'- handoff note:3 · 2026-11-01 · "{HANDOFF}"'
    other = AgentEvent(2, e.occurred_at, e.day, "task_done", "task:1", "career", "app")
    assert event_line(other, HANDOFF) == "- task_done task:1 · career · 2026-11-01"


def _dayend_calls(env, agent: str) -> list[dict[str, Any]]:
    return [c for c in env.brain.calls if c["run_ctx"].kind == "dayend" and c["run_ctx"].agent == agent]


def _ev(env, kind: str, ref: str, day: date, area: str | None, to: tuple[str, ...]) -> None:
    with transaction(env.conn):
        env.parts.agents.add_event(kind, ref, area, "app", day, to=to, now=env.clock.now())


async def test_handoff_text_inlined(tmp_path):
    hand = ("hand_off", {"to": "manager", "text": HANDOFF, "refs": ["workout:3"]})
    async with BeEnv.start(tmp_path, start=kst(2026, 11, 2, 4, 0), script=[FakeTurn([hand], ""), FakeTurn([], "")],
                           dayend=True) as env:
        env.parts.runner.checkins = False
        _ev(env, "workout_logged", "workout:3", date(2026, 11, 1), "health", ("mate",))
        env.clock.set(kst(2026, 11, 2, 4, 1))
        await env.tick()
        (call,) = _dayend_calls(env, "manager")
        (note,) = env.parts.agents.notes("mate", date.min)
        # 즉시 판단 블록: 아직 읽지 않은 넘김 줄(꾸민 자료)
        with transaction(env.conn):
            nid = env.parts.agents.add_note("mate", date(2026, 11, 2), HANDOFF, 3, ["workout:3"], env.clock.now())
        _ev(env, "handoff", f"note:{nid}", date(2026, 11, 2), None, ("manager",))
        block = inbox_block(env.parts.agents, "manager", date(2026, 11, 2))
        env.brain.script.append(FakeTurn([], "네"))
        await env.chat("요즘 어때?", agent="manager")
        chat_prompt = env.brain.calls[-1]["prompt"]
    line = f'- handoff note:{note.id} · 2026-11-02 · "{HANDOFF}"'
    assert line in call["prompt"].splitlines()
    assert f'- handoff note:{nid} · 2026-11-02 · "{HANDOFF}"' in block.text.splitlines()
    assert f'note:{nid} · 2026-11-02 · "{HANDOFF}"' in chat_prompt


async def test_manager_hands_off_routine_to_mate(tmp_path):
    text = "가짜 운동 루틴은 메이트가 맡아요."
    hand = ("hand_off", {"to": "mate", "text": text, "refs": ["task:1"]})
    script = [FakeTurn([hand], ""), FakeTurn([], "")]
    async with BeEnv.start(tmp_path, start=kst(2026, 11, 2, 4, 0), script=script, dayend=True) as env:
        env.parts.runner.checkins = False
        _ev(env, "task_done", "task:1", date(2026, 11, 1), "health", ("manager",))
        env.clock.set(kst(2026, 11, 2, 4, 1))
        await env.tick()
        assert [c["run_ctx"].agent for c in env.brain.calls if c["run_ctx"].kind == "dayend"] == ["manager"]
        inbox = env.conn.execute(
            "SELECT e.kind, e.ref FROM agent_inbox i JOIN agent_events e ON e.id = i.event_id "
            "WHERE i.agent = 'mate' AND i.seen_at IS NULL"
        ).fetchall()
        env.clock.set(kst(2026, 11, 3, 4, 1))
        await env.tick()
        (mate_call,) = _dayend_calls(env, "mate")
    (row,) = inbox
    assert row["kind"] == "handoff"
    assert f'- handoff {row["ref"]} · 2026-11-02 · "{text}"' in mate_call["prompt"].splitlines()
