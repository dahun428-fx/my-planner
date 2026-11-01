"""라이프 매니저 메시지의 두뇌 호출(SP15 계획 Task 12): 전문가 상한, 전체 진단 상한·한도, 소견 줄.

`BeEnv`(가짜 두뇌)로 앱 `/chat`을 보낸다. 내용과 숫자는 꾸며 낸 것이다.
"""

import json
from datetime import timedelta

from be_env import BeEnv
from fakes import FakeTurn
from test_api_read import get_json
from test_dispatcher_messages import kst
from ui_stream import parse_sse

from my_planner.config import Settings
from my_planner.harness.moments import MOMENTS_RESERVE_CALLS
from my_planner.panel.experts import EXPERTS, ExpertNote
from my_planner.panel.report import (
    FULL_BLOCK_REPLIES,
    FULL_DAYS_KEY,
    FULL_FAILED_REPLY,
    full_diagnosis_block,
    mark_full_diagnosis,
)
from my_planner.store.repos.state import StateRepo
from my_planner.tools.mcp_adapter import tool_names_for

START = kst(2026, 11, 1, 14, 0)  # 일요일 오후(ISO 주 2026-W44: 10-26 ~ 11-01)
LIMITS = Settings.model_fields["limits"].default


def _cid(resp) -> int:
    return int(resp.headers["x-conversation-id"])


def _brain_calls(env) -> int:
    return env.parts.state.usage(env.clock.now().date()).brain_calls


def _spy(env) -> list[dict]:
    """디스패처 `_call_brain`에 넘긴 인자(호출마다). `timeout_s`는 두뇌가 아니라 디스패처가 쓴다."""
    d = env.parts.dispatcher
    real = d._call_brain
    seen: list[dict] = []

    async def wrapped(prompt, **kw):
        seen.append(kw)
        return await real(prompt, **kw)

    d._call_brain = wrapped
    return seen


def _texts(raw: bytes) -> str:
    return "".join(c.get("delta", "") + c.get("text", "") for c in parse_sse(raw) if c["type"].startswith("text"))


def test_limits_defaults():
    assert (LIMITS.full_diagnosis.max_turns, LIMITS.full_diagnosis.brain_timeout_s) == (30, 900)
    assert (LIMITS.manager_message.max_turns, LIMITS.manager_message.brain_timeout_s) == (12, 300)


async def test_manager_passes_six_definitions_cap_two(tmp_path):
    async with BeEnv.start(tmp_path, start=START, script=[FakeTurn([], "이번 주는 하나만 봐요.")]) as env:
        spied = _spy(env)
        await env.chat("요즘 어때 보여?", agent="manager")
        call = env.brain.calls[0]
        used = _brain_calls(env)
    assert list(call["agents"]) == list(EXPERTS)
    assert call["subagent_cap"] == 2
    assert call["max_turns"] == LIMITS.manager_message.max_turns
    assert spied[0]["timeout_s"] == LIMITS.manager_message.brain_timeout_s
    assert call["disallowed_tools"] is None  # 스파이크 S1 disallow_main_ok=False
    assert call["run_ctx"].full_diagnosis is False
    assert used == 1


async def test_secretary_gets_no_agents(tmp_path):
    async with BeEnv.start(tmp_path, start=START, script=[FakeTurn([], "네")]) as env:
        spied = _spy(env)
        await env.chat("안녕")
        call = env.brain.calls[0]
    assert call["agents"] is None and call["subagent_cap"] is None
    assert spied[0].get("timeout_s") is None


async def test_full_diagnosis_cap_six_and_limits(tmp_path):
    async with BeEnv.start(tmp_path, start=START, script=[FakeTurn([], "진단을 정리했어요.")]) as env:
        spied = _spy(env)
        await env.chat("전체 진단", agent="manager", chip="manager_full")
        call = env.brain.calls[0]
    ctx = call["run_ctx"]
    assert list(call["agents"]) == list(EXPERTS)
    assert call["subagent_cap"] == 6
    assert call["max_turns"] == 30 and spied[0]["timeout_s"] == 900
    assert ctx.full_diagnosis is True
    assert "save_life_report" in tool_names_for(ctx)


async def test_full_diagnosis_day_and_week_caps(tmp_path):
    day = START.date()
    async with BeEnv.start(tmp_path, start=START) as env:
        state = env.parts.state
        state.set(FULL_DAYS_KEY, json.dumps([day.isoformat()]))
        _, raw_day = await env.chat("전체 진단", agent="manager", chip="manager_full")
        state.set(FULL_DAYS_KEY, json.dumps(["2026-10-27", "2026-10-29"]))
        _, raw_week = await env.chat("전체 진단", agent="manager", chip="manager_full")
        state.set(FULL_DAYS_KEY, json.dumps([]))
        env.conn.execute(
            "INSERT INTO usage_state (date, brain_calls) VALUES (?, ?) "
            "ON CONFLICT (date) DO UPDATE SET brain_calls = excluded.brain_calls",
            (day.isoformat(), LIMITS.daily_brain_calls - 2),
        )
        env.conn.commit()
        _, raw_calls = await env.chat("전체 진단", agent="manager", chip="manager_full")
        calls = len(env.brain.calls)
    assert calls == 0
    assert _texts(raw_day) == FULL_BLOCK_REPLIES["day"] == "전체 진단은 오늘 이미 했어요. 내일 다시 할 수 있어요."
    assert _texts(raw_week) == FULL_BLOCK_REPLIES["week"] == "전체 진단은 이번 주에 두 번 했어요. 다음 주에 다시 할 수 있어요."
    assert _texts(raw_calls) == FULL_BLOCK_REPLIES["calls"] == (
        "오늘은 두뇌 호출이 얼마 없어 전체 진단을 시작하지 않았어요. 내일 해 볼까요?"
    )


def test_full_diagnosis_block_rules(conn):
    state = StateRepo(conn)
    today = START.date()  # 일요일
    assert full_diagnosis_block(state, today, MOMENTS_RESERVE_CALLS) is None
    assert full_diagnosis_block(state, today, 3) is None
    assert full_diagnosis_block(state, today, 2) == "calls"
    mark_full_diagnosis(state, today - timedelta(days=6))  # 같은 주 월요일
    assert full_diagnosis_block(state, today, 10) is None
    mark_full_diagnosis(state, today - timedelta(days=7))  # 지난 주 일요일: 이번 주에 세지 않는다
    assert full_diagnosis_block(state, today, 10) is None
    mark_full_diagnosis(state, today - timedelta(days=1))
    assert full_diagnosis_block(state, today, 10) == "week"
    mark_full_diagnosis(state, today)
    assert full_diagnosis_block(state, today, 0) == "day"
    # 지난 14일만 남긴다
    mark_full_diagnosis(state, today + timedelta(days=14))
    kept = json.loads(state.get(FULL_DAYS_KEY) or "[]")
    assert kept == [(today + timedelta(days=14)).isoformat()]


def test_full_diagnosis_block_ignores_broken_value(conn):
    state = StateRepo(conn)
    state.set(FULL_DAYS_KEY, "not json")
    assert full_diagnosis_block(state, START.date(), 10) is None
    mark_full_diagnosis(state, START.date())
    assert json.loads(state.get(FULL_DAYS_KEY) or "[]") == [START.date().isoformat()]


async def test_failed_full_diagnosis_not_counted(tmp_path):
    script = [FakeTurn([], "", status="error", error="cli"), FakeTurn([], "다시 정리했어요.")]
    async with BeEnv.start(tmp_path, start=START, script=script) as env:
        _, raw = await env.chat("전체 진단", agent="manager", chip="manager_full")
        first_calls = len(env.brain.calls)
        days = env.parts.state.get(FULL_DAYS_KEY)
        reports = env.conn.execute("SELECT COUNT(*) FROM life_reports").fetchone()[0]
        await env.chat("전체 진단", agent="manager", chip="manager_full")
        calls = len(env.brain.calls)
    assert first_calls == 1
    assert _texts(raw) == FULL_FAILED_REPLY
    assert START.date().isoformat() not in json.loads(days or "[]")
    assert reports == 0
    assert calls == 2


async def test_full_diagnosis_timeout_no_retry(tmp_path):
    timeout = FakeTurn([], "", status="error", error="timeout")
    async with BeEnv.start(tmp_path, start=START, script=[timeout]) as env:
        _, raw = await env.chat("전체 진단", agent="manager", chip="manager_full")
        calls = len(env.brain.calls)
    assert calls == 1
    assert _texts(raw) == FULL_FAILED_REPLY
    async with BeEnv.start(tmp_path / "plain", start=START, script=[timeout] * 4) as env:
        _, raw = await env.chat("요즘 어때?", agent="manager")
        calls = len(env.brain.calls)
    assert calls == 4  # 보통 매니저 메시지는 지금처럼 3회 더
    assert FULL_FAILED_REPLY not in _texts(raw)


async def test_full_diagnosis_resume_fallback_keeps_flag(tmp_path):
    script = [
        FakeTurn([], "안녕하세요", session_id="s-man"),
        FakeTurn([], "", resume_failed=True, session_id=None),
        FakeTurn([], "진단을 정리했어요.", session_id="s-new"),
    ]
    async with BeEnv.start(tmp_path, start=START, script=script) as env:
        spied = _spy(env)
        first, _ = await env.chat("안녕", agent="manager")
        env.clock.advance(timedelta(minutes=5))
        second, _ = await env.chat("전체 진단", agent="manager", chip="manager_full")
        calls = env.brain.calls
    assert _cid(first) == _cid(second)
    assert calls[1]["session_id"] == "s-man" and calls[2]["session_id"] is None
    for call, kw in zip(calls[1:], spied[1:], strict=True):
        assert call["run_ctx"].full_diagnosis is True
        assert "save_life_report" in tool_names_for(call["run_ctx"])
        assert (call["subagent_cap"], call["max_turns"], kw["timeout_s"]) == (6, 30, 900)


async def test_expert_notes_stream_and_history(tmp_path):
    notes = (ExpertNote("career", "가짜 커리어 소견"), ExpertNote("relationship", "가짜 관계 소견"))
    async with BeEnv.start(tmp_path, start=START, script=[FakeTurn([], "두 분 의견을 모았어요.", expert_notes=notes)]) as env:
        resp, raw = await env.chat("일과 사람 쪽 봐 줘", agent="manager")
        cid = _cid(resp)
        messages = await get_json(env, f"/conversations/{cid}/messages")
        text = env.parts.transcripts.path_for(env.clock.now()).read_text(encoding="utf-8")
    chunks = parse_sse(raw)
    kinds = [c["type"] for c in chunks]
    parts = [c for c in chunks if c["type"] == "data-expert-notes"]
    assert len(parts) == 1
    assert parts[0]["data"] == {"notes": [
        {"expert": "career", "text": "가짜 커리어 소견"}, {"expert": "relationship", "text": "가짜 관계 소견"},
    ]}
    at = kinds.index("data-expert-notes")
    assert kinds[at - 1] == "finish-step" and at < kinds.index("finish")
    items = messages["items"]
    assert [m["speaker"] for m in items] == ["user", "manager"]
    assert items[0]["expert_notes"] == []
    assert items[1]["expert_notes"] == parts[0]["data"]["notes"]
    headers = [line for line in text.splitlines() if line.startswith("### ")]
    assert headers[-2:] == [
        f"### 14:00 전문가 [{cid}] (career) @app @manager",
        f"### 14:00 전문가 [{cid}] (relationship) @app @manager",
    ]
    assert " 라이프 매니저 " in headers[-3]


async def test_no_notes_no_part(tmp_path):
    async with BeEnv.start(tmp_path, start=START, script=[FakeTurn([], "그냥 답해요.")]) as env:
        _, raw = await env.chat("안녕", agent="manager")
    assert all(c["type"] != "data-expert-notes" for c in parse_sse(raw))
