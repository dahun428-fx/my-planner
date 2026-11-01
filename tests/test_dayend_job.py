"""하루 끝 판단 (SP14 스펙 1장 3·4, 6.1~6.3, 12장, T2·T5·T12·T13). `BeEnv` + `FakeBrain`, tick은 11/02(월) 04:01.

내용은 모두 꾸며 낸 것이다. 세션 파일 시험은 `tmp_path` 아래 가짜 설정 폴더만 쓴다.
"""

from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from datetime import date, timedelta

from be_env import BeEnv
from fakes import FakePushSender, FakeTurn
from test_dispatcher_messages import kst

from my_planner.harness import dayend
from my_planner.harness import prompts as prompt_files
from my_planner.harness.dayend import (
    DAYEND_ATTEMPTS_KEY,
    DAYEND_DAY_KEY,
    dayend_system_prompt,
)
from my_planner.logging_setup import setup_logging
from my_planner.store.db import transaction
from my_planner.store.repos.state import LIMITED_UNTIL_KEY

START = kst(2026, 11, 2, 4, 0)
TICK = kst(2026, 11, 2, 4, 1)
TODAY = date(2026, 11, 2)
NEXT = kst(2026, 11, 3, 4, 1)
SID = "1b4e28ba-2fa1-11d2-883f-0016d3cca427"
OTHER_SID = "9a7c1f00-0000-4000-8000-000000000001"
NOTE = "토요일 저녁만 비어 있어 운동은 그날이 좋아요"


@asynccontextmanager
async def started(tmp_path, script=(), *, moments=False, claude=False, push=None):
    async with BeEnv.start(tmp_path, script=list(script), start=START, moments=moments, dayend=True,
                           push=push) as env:
        env.parts.runner.checkins = False  # 며칠 건너 tick해도 복귀 인사가 두뇌 시나리오를 쓰지 않게
        if claude:
            env.parts.dispatcher.claude_config_dir = tmp_path / "claude"
        yield env


async def tick_at(env, when=TICK):
    env.clock.set(when)
    await env.tick()


_seq = iter(range(1, 1_000_000))


def ev(env, kind, ref, day, area=None, to=("mate", "manager")):
    """받은편지함 줄 하나(시험 고정 자료: 저장소에 바로). 시각은 1초씩 늘려 순서를 정한다."""
    when = kst(2026, 10, 1, 0, 0) + timedelta(seconds=next(_seq))
    with transaction(env.conn):
        return env.parts.agents.add_event(kind, ref, area, "app", day, to=to, now=when)


def unseen_ids(env, agent="mate"):
    rows = env.conn.execute(
        "SELECT event_id FROM agent_inbox WHERE agent = ? AND seen_at IS NULL ORDER BY event_id", (agent,)
    )
    return [r["event_id"] for r in rows]


def dayend_calls(env):
    return [c for c in env.brain.calls if c["run_ctx"].kind == "dayend"]


def records(caplog, msg):
    return [r for r in caplog.records if r.getMessage() == msg]


def note(text=NOTE, priority=2, refs=("workout:3",)):
    return ("write_note", {"text": text, "priority": priority, "refs": list(refs)})


# --- 하루 한 번 (T5, AC7) ---


async def test_dayend_one_call_per_day_sp14(tmp_path, caplog):
    caplog.set_level(logging.INFO)
    async with started(tmp_path, [FakeTurn([], "")]) as env:
        ev(env, "workout_logged", "workout:1", date(2026, 11, 1), "health")
        ev(env, "task_done", "task:1", date(2026, 11, 1), "career", to=("manager",))
        before = env.parts.state.usage(TODAY).brain_calls
        d = env.parts.dispatcher
        d.submit_dayend(TODAY)
        d.submit_dayend(TODAY)
        await env.drain()
        (call,) = dayend_calls(env)
        assert call["run_ctx"].agent == "mate"
        assert env.parts.state.usage(TODAY).brain_calls == before + 1
        assert [r.result for r in records(caplog, "agent_dayend")] == ["ok", "already"]
        assert unseen_ids(env, "mate") == [] and len(unseen_ids(env, "manager")) == 2
        assert env.parts.state.get(DAYEND_DAY_KEY.format(agent="mate")) == "2026-11-02"


async def test_dayend_skips_when_reserve_short(tmp_path, caplog):
    caplog.set_level(logging.INFO)
    async with started(tmp_path, [FakeTurn([], "")]) as env:
        ev(env, "workout_logged", "workout:1", date(2026, 11, 1), "health")
        for _ in range(env.settings.limits.daily_brain_calls - 10):
            env.parts.state.incr_usage(TODAY, "brain_calls")
        await tick_at(env)
        assert env.brain.calls == []
        assert len(unseen_ids(env)) == 1
        assert env.parts.state.get(DAYEND_DAY_KEY.format(agent="mate")) is None
        assert [r.result for r in records(caplog, "agent_dayend")] == ["waiting"]
        ev(env, "workout_logged", "workout:2", date(2026, 11, 2), "health")
        await tick_at(env, NEXT)
        (call,) = dayend_calls(env)
        assert "workout:1" in call["prompt"] and "workout:2" in call["prompt"]
        assert unseen_ids(env) == []


async def test_catch_up_one_call_older_than_7_seen(tmp_path):
    seen_at_call: list[list[int]] = []
    async with started(tmp_path, [FakeTurn([], "")]) as env:
        ids = [ev(env, "workout_logged", f"workout:{n}", TODAY - timedelta(days=n), "health") for n in (9, 8, 7, 3, 1)]
        orig = env.brain.run

        async def spy(*a, **kw):
            seen_at_call.append(unseen_ids(env))
            return await orig(*a, **kw)

        env.brain.run = spy
        env.parts.dispatcher.submit_dayend(TODAY)
        await env.drain()
        (call,) = dayend_calls(env)
        assert seen_at_call == [ids[2:]]  # 앞 둘은 호출 전에 본 것
        assert "workout:9" not in call["prompt"] and "workout:8" not in call["prompt"]
        assert all(f"workout:{n}" in call["prompt"] for n in (7, 3, 1))
        assert unseen_ids(env) == []


async def test_empty_inbox_no_call(tmp_path, caplog):
    caplog.set_level(logging.INFO)
    async with started(tmp_path) as env:
        ev(env, "task_done", "task:1", date(2026, 11, 1), "career", to=("manager",))
        await tick_at(env)
        assert env.brain.calls == []
        assert [r.result for r in records(caplog, "agent_dayend")] == ["empty"]


async def test_code_steps_run_always(tmp_path, monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    ran: list[date] = []

    def boom(conn, clock, today):
        raise RuntimeError("꾸민 단계 오류")

    def count(conn, clock, today):
        ran.append(today)

    monkeypatch.setattr(dayend, "DAYEND_CODE_STEPS", [boom, count])
    async with started(tmp_path) as env:
        d = env.parts.dispatcher
        d.submit_dayend(TODAY)  # 받은편지함이 비었다
        await env.drain()
        ev(env, "workout_logged", "workout:1", date(2026, 11, 2), "health")
        tomorrow = TODAY + timedelta(days=1)
        env.clock.set(NEXT)
        for _ in range(env.settings.limits.daily_brain_calls - 10):
            env.parts.state.incr_usage(tomorrow, "brain_calls")
        d.submit_dayend(tomorrow)  # 사용자 몫이 모자라다
        await env.drain()
        assert ran == [TODAY, tomorrow]
        assert env.brain.calls == []
        errs = records(caplog, "agent_dayend_step_error")
        assert [(r.step, r.error_type) for r in errs] == [("boom", "RuntimeError")] * 2


# --- 입력 (6.2) ---


async def test_input_shape(tmp_path):
    async with started(tmp_path, [FakeTurn([], "")]) as env:
        ev(env, "workout_logged", "workout:3", date(2026, 11, 1), "health")
        ev(env, "event_added", "event:2", date(2026, 11, 1))
        repo = env.parts.agents
        with transaction(env.conn):
            for n in range(1, 5):
                repo.add_note("mate", date(2026, 10, 25 + n), f"꾸민 관찰 {n}", 2, ["workout:1"], env.clock.now())
            repo.add_note("manager", date(2026, 10, 31), "다른 상대의 관찰", 2, ["task:1"], env.clock.now())
        env.parts.dispatcher.submit_dayend(TODAY)
        await env.drain()
        (call,) = dayend_calls(env)
        assert call["prompt"] == (
            "## 판단하는 날\n"
            "2026-11-01 (일)\n"
            "\n"
            "## 새로 생긴 것\n"
            "- workout_logged workout:3 · health · 2026-11-01\n"
            "- event_added event:2 · 2026-11-01\n"
            "\n"
            "## 지난 관찰\n"
            "- 2026-10-29 꾸민 관찰 4\n"
            "- 2026-10-28 꾸민 관찰 3\n"
            "- 2026-10-27 꾸민 관찰 2"
        )
        assert call["system_prompt"] == dayend_system_prompt("mate")
        assert call["system_prompt"] == prompt_files.load("mate.md") + "\n\n" + prompt_files.load("agent_dayend.md")
        assert call["max_turns"] == 3 and call["persist_session"] is False and call["session_id"] is None
        ctx = call["run_ctx"]
        assert (ctx.kind, ctx.agent, ctx.dayend_day, ctx.channel) == ("dayend", "mate", date(2026, 11, 1), "app")
        assert (ctx.actor, ctx.activity_channel, ctx.conversation_id, ctx.run_id) == ("secretary", "scheduler", None, None)
        assert env.sender.typing_count == 0


async def test_input_empty_sections(tmp_path):
    from my_planner.harness.dayend import build_dayend_input

    text = build_dayend_input(TODAY, [], [])
    assert text == "## 판단하는 날\n2026-11-01 (일)\n\n## 새로 생긴 것\n- 없음\n\n## 지난 관찰\n- 없음"


async def test_events_capped_100_rest_seen(tmp_path):
    async with started(tmp_path, [FakeTurn([], "")]) as env:
        for n in range(1, 106):
            ev(env, "workout_logged", f"workout:{n}", date(2026, 11, 1), "health")
        env.parts.dispatcher.submit_dayend(TODAY)
        await env.drain()
        (call,) = dayend_calls(env)
        lines = [ln for ln in call["prompt"].splitlines() if ln.startswith("- workout_logged")]
        assert len(lines) == 100
        assert lines[0].startswith("- workout_logged workout:6 ") and lines[-1].startswith("- workout_logged workout:105 ")
        assert unseen_ids(env) == []


# --- 판정 (6.2, 12장, T12) ---


async def test_zero_notes_ok(tmp_path, caplog):
    caplog.set_level(logging.INFO)
    async with started(tmp_path, [FakeTurn([], "남길 게 없어요")]) as env:
        ev(env, "workout_logged", "workout:1", date(2026, 11, 1), "health")
        await tick_at(env)
        (rec,) = records(caplog, "agent_dayend")
        assert (rec.result, rec.notes, rec.events) == ("ok", 0, 1)
        assert unseen_ids(env) == []
        assert env.parts.agents.notes("mate", date.min) == []
        assert env.sender.sent == []


async def test_failure_retries_next_day_then_marks_seen(tmp_path, caplog):
    caplog.set_level(logging.INFO)
    retry = kst(2026, 11, 4, 9, 0)
    script = [
        FakeTurn([], "", status="error", error="x"),
        FakeTurn([], "", status="error", error="timeout"),
        FakeTurn([], "", status="rate_limited", retry_at=retry),
    ]
    async with started(tmp_path, script) as env:
        state = env.parts.state
        key = DAYEND_ATTEMPTS_KEY.format(agent="mate")
        ev(env, "workout_logged", "workout:1", date(2026, 11, 1), "health")
        await tick_at(env)
        assert len(unseen_ids(env)) == 1 and state.get(key) == "1"
        assert [r.result for r in records(caplog, "agent_dayend")] == ["retry"]
        await tick_at(env, NEXT)
        assert unseen_ids(env) == [] and state.get(key) == "0"
        (failed,) = records(caplog, "agent_dayend_failed")
        assert (failed.agent, failed.events) == ("mate", 1)
        assert [r.result for r in records(caplog, "agent_dayend")] == ["retry", "failed"]
        # 사용 한도: 시도 수 그대로, 줄 그대로, `limited_until`
        ev(env, "workout_logged", "workout:2", date(2026, 11, 3), "health")
        await tick_at(env, kst(2026, 11, 4, 4, 1))
        assert len(unseen_ids(env)) == 1 and state.get(key) == "0"
        assert records(caplog, "agent_dayend")[-1].result == "limited"
        assert state.get(LIMITED_UNTIL_KEY) is not None
        assert len(dayend_calls(env)) == 3


async def test_brain_exception_counts_as_attempt(tmp_path, caplog):
    caplog.set_level(logging.INFO)
    script = [
        FakeTurn([], "", session_id=SID, raises=RuntimeError("꾸민 두뇌 오류 workout:1")),
        FakeTurn([], "", session_id=None, raises=RuntimeError("꾸민 두뇌 오류 workout:1")),
    ]
    async with started(tmp_path, script, claude=True) as env:
        mine, other = _session_files(tmp_path)
        state = env.parts.state
        key = DAYEND_ATTEMPTS_KEY.format(agent="mate")
        ev(env, "workout_logged", "workout:1", date(2026, 11, 1), "health")
        await tick_at(env)
        assert len(unseen_ids(env)) == 1 and state.get(key) == "1"
        assert not mine.exists() and other.exists()  # 예외 때도 세션 파일을 지운다
        await tick_at(env, NEXT)
        assert unseen_ids(env) == [] and state.get(key) == "0"
        assert [r.result for r in records(caplog, "agent_dayend")] == ["error", "error"]
        assert len(records(caplog, "agent_dayend_failed")) == 1
        errs = records(caplog, "agent_dayend_brain_error")
        assert [(r.agent, r.error_type) for r in errs] == [("mate", "RuntimeError")] * 2
        assert records(caplog, "agent_dayend_error") == []
        for r in records(caplog, "agent_dayend") + errs:
            assert "꾸민 두뇌 오류" not in str(r.__dict__) and "workout:1" not in str(r.__dict__)


async def test_auth_error_limited_keeps_attempts(tmp_path, caplog):
    caplog.set_level(logging.INFO)
    script = [FakeTurn([], "", status="error", error="x"), FakeTurn([], "", status="auth_error", error="login")]
    async with started(tmp_path, script) as env:
        state = env.parts.state
        key = DAYEND_ATTEMPTS_KEY.format(agent="mate")
        ev(env, "workout_logged", "workout:1", date(2026, 11, 1), "health")
        await tick_at(env)
        assert state.get(key) == "1"
        await tick_at(env, NEXT)
        assert state.get(key) == "1" and len(unseen_ids(env)) == 1
        assert [r.result for r in records(caplog, "agent_dayend")] == ["retry", "limited"]
        assert records(caplog, "agent_dayend_failed") == []


async def test_notes_written_counts_even_when_status_not_ok(tmp_path):
    async with started(tmp_path, [FakeTurn([note()], "", status="max_turns")]) as env:
        ev(env, "workout_logged", "workout:3", date(2026, 11, 1), "health")
        await tick_at(env)
        assert unseen_ids(env) == []
        assert [n.text for n in env.parts.agents.notes("mate", date.min)] == [NOTE]


# --- 순서와 정리 (6.1) ---


async def test_dayend_after_moments_then_prune(tmp_path):
    async with started(tmp_path, [FakeTurn([], ""), FakeTurn([], "")], moments=True) as env:
        env.parts.transcripts.append(kst(2026, 11, 1, 14, 0), "사용자", 1, None, "꾸민 말", channel="telegram")
        ev(env, "workout_logged", "workout:1", date(2026, 11, 1), "health")
        old = ev(env, "workout_logged", "workout:2", TODAY - timedelta(days=91), "health")
        await tick_at(env)
        assert [c["run_ctx"].kind for c in env.brain.calls] == ["moments", "dayend"]
        assert env.conn.execute("SELECT 1 FROM agent_events WHERE id = ?", (old,)).fetchone() is None
        assert env.conn.execute("SELECT COUNT(*) FROM agent_events").fetchone()[0] == 1


async def test_queue_dayend_registered_after_moments(tmp_path):
    async with started(tmp_path) as env:
        names = [j.__name__ for j in env.parts.runner._daily]
        i = names.index("queue_moments")
        assert names[i + 1] == "queue_dayend"


# --- 세션 파일 (6.3) ---


def _session_files(tmp_path):
    proj = tmp_path / "claude" / "projects" / "-home-x"
    proj.mkdir(parents=True)
    mine = proj / f"{SID}.jsonl"
    mine.write_text("{}\n", encoding="utf-8")
    other = proj / f"{OTHER_SID}.jsonl"
    other.write_text("{}\n", encoding="utf-8")
    return mine, other


async def test_session_file_removed_after_dayend(tmp_path):
    async with started(tmp_path, [FakeTurn([], "", session_id=SID)], claude=True) as env:
        mine, other = _session_files(tmp_path)
        ev(env, "workout_logged", "workout:1", date(2026, 11, 1), "health")
        await tick_at(env)
        assert not mine.exists() and other.exists()


async def test_session_file_removed_after_dayend_error(tmp_path):
    script = [FakeTurn([], "", status="error", error="x", session_id=SID)]
    async with started(tmp_path, script, claude=True) as env:
        mine, other = _session_files(tmp_path)
        ev(env, "workout_logged", "workout:1", date(2026, 11, 1), "health")
        await tick_at(env)
        assert not mine.exists() and other.exists()


# --- 로그 (T2, 12장) ---


async def test_dayend_log_has_counts_only(tmp_path):
    turn = FakeTurn([
        note(),
        ("hand_off", {"to": "manager", "text": "저녁 일정이 많아 운동 날이 줄었어요", "refs": ["workout:3"]}),
    ], "", session_id=SID)
    async with started(tmp_path, [turn], claude=True) as env:
        state_dir = env.settings.paths.state_dir
        setup_logging(state_dir, 30)
        ev(env, "workout_logged", "workout:3", date(2026, 11, 1), "health")
        await tick_at(env)
        for h in logging.getLogger().handlers:
            h.flush()
        logs = [p for p in (state_dir / "logs").rglob("*") if p.is_file()]
        assert logs
        for path in logs:
            text = path.read_text(encoding="utf-8")
            assert NOTE not in text and "저녁 일정" not in text and "workout:3" not in text, path
        entries = [json.loads(line) for p in logs for line in p.read_text(encoding="utf-8").splitlines() if line]
        (job,) = [e for e in entries if e.get("msg") == "agent_dayend"]
        assert set(job) - {"ts", "level", "logger", "msg"} == {
            "agent", "events", "notes", "handoffs", "result", "duration_ms",
        }
        assert (job["agent"], job["events"], job["notes"], job["handoffs"], job["result"]) == ("mate", 1, 1, 1, "ok")
        # 넘기기는 받는 쪽 받은편지함에
        handoff = env.conn.execute("SELECT e.kind, e.origin FROM agent_inbox i JOIN agent_events e ON e.id = i.event_id "
                                   "WHERE i.agent = 'manager' AND e.kind = 'handoff'").fetchall()
        assert [(r["kind"], r["origin"]) for r in handoff] == [("handoff", "brain")]


# --- 아무것도 보내지 않는다 (T13 실행 쪽, 1장 4) ---


async def test_dayend_sends_nothing(tmp_path):
    push = FakePushSender()
    turn = FakeTurn([note(), note("토요일 오전도 비어 있어요", refs=("event:2",))], "보낼 글이 아니에요")
    async with started(tmp_path, [turn], push=push) as env:
        await env.subscribe("https://push.example.invalid/1")
        ev(env, "workout_logged", "workout:3", date(2026, 11, 1), "health")
        ev(env, "event_added", "event:2", date(2026, 11, 1))
        runs_before = env.conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
        proactive = env.parts.state.usage(TODAY).proactive_messages
        env.parts.dispatcher.submit_dayend(TODAY)
        await env.drain()
        assert len(env.parts.agents.notes("mate", date.min)) == 2
        assert env.sender.sent == [] and push.sent == []
        assert env.parts.state.usage(TODAY).proactive_messages == proactive
        assert env.conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == runs_before
        transcripts = [p for p in (env.settings.paths.data_dir / "transcripts").rglob("*") if p.is_file()]
        assert transcripts == []
