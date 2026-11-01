"""하루 끝 작업: 이룬 순간 (SP8 스펙 6.2~6.3, 6.8, 1장 조건 3·4·7). `BeEnv` + `FakeBrain`, tick은 10/26(월) 04:01.

내용은 모두 꾸며 낸 것이다. 세션 파일 시험은 `tmp_path` 아래 가짜 설정 폴더만 쓴다.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
from contextlib import asynccontextmanager
from datetime import date, timedelta

import pytest
from be_env import BeEnv
from fakes import FakeTurn
from test_dispatcher_messages import kst

from my_planner.clock import to_iso
from my_planner.domain import LoopKey
from my_planner.harness.dispatcher import Inbound
from my_planner.harness.moments import (
    MOMENTS_PAUSED_KEY,
    MOMENTS_SINCE_KEY,
    build_moments_input,
    days_to_queue,
    moments_system_prompt,
    remove_session_file,
)
from my_planner.logging_setup import setup_logging
from my_planner.loop.runner import queue_moments_daily
from my_planner.store.repos.state import (
    BRAIN_AUTH_STATE_KEY,
    LIMITED_UNTIL_KEY,
    PAUSE_UNTIL_KEY,
)

START = kst(2026, 10, 26, 4, 0)
TICK = kst(2026, 10, 26, 4, 1)
TODAY = date(2026, 10, 26)
D = {n: date(2026, 10, n) for n in range(18, 28)}
SID = "1b4e28ba-2fa1-11d2-883f-0016d3cca427"
OTHER_SID = "9a7c1f00-0000-4000-8000-000000000001"
SECRET = "꾸며 낸 순간 글"


@asynccontextmanager
async def started(tmp_path, script=(), *, since=None, claude=False):
    async with BeEnv.start(tmp_path, script=list(script), start=START, moments=True) as env:
        # 회차는 끈다: 며칠 건너 tick해도 복귀 인사가 두뇌 시나리오를 쓰지 않게(하루 한 번 작업은 그대로 돈다)
        env.parts.runner.checkins = False
        if since is not None:
            env.parts.state.set(MOMENTS_SINCE_KEY, since)
        if claude:
            env.parts.dispatcher.claude_config_dir = tmp_path / "claude"
        yield env


async def tick_at(env, when=TICK):
    env.clock.set(when)
    await env.tick()


def at(env, when, fn):
    now = env.clock.now()
    env.clock.set(when)
    try:
        return fn()
    finally:
        env.clock.set(now)


def done_task(env, title, when, areas=("career",), note=""):
    tasks = env.parts.tasks

    def go():
        t = tasks.create(title, list(areas), note=note)
        return tasks.set_status(t.id, "done")

    return at(env, when, go)


def check(env, title, day, area="health"):
    h = env.parts.habits.add(title, area, "daily", None, env.clock.now())
    env.parts.habits.check(h.id, day, env.clock.now())
    return h


def say(env, when, text, speaker="사용자", channel="telegram"):
    env.parts.transcripts.append(when, speaker, 1, None, text, channel=channel)


def day_row(env, d):
    return env.parts.moments.day(d)


def save(d, *texts, sources=("chat",)):
    items = [{"text": t, "area": None, "sources": list(sources)} for t in texts]
    return ("save_moments", {"date": d.isoformat(), "moments": items})


def kinds(env):
    return [c["run_ctx"].kind for c in env.brain.calls]


def prompt_days(env):
    return [c["prompt"].splitlines()[1].split()[0] for c in env.brain.calls if c["run_ctx"].kind == "moments"]


def build_input(env, d):
    p = env.parts
    return build_moments_input(
        d, tasks=p.tasks, habits=p.habits, conditions=p.conditions, transcripts=p.transcripts,
        tz=env.settings.timezone, boundary=env.settings.day_boundary,
    )


# --- 고르기 (6.2-2) ---


async def test_picks_yesterday_back_7_days_since_moments_since_oldest_first(tmp_path):
    script = [FakeTurn([], "") for _ in range(4)]
    async with started(tmp_path, script, since="2026-10-01") as env:
        repo = env.parts.moments
        repo.mark(D[20], "done", TICK, saved=1)
        repo.mark(D[21], "pending", TICK)
        repo.mark(D[22], "empty", TICK)
        repo.mark(D[23], "failed", TICK)
        for n in (19, 21, 24, 25):
            say(env, kst(2026, 10, n, 14, 2), f"{n}일의 꾸민 말")
        await tick_at(env)
        assert prompt_days(env) == ["2026-10-19", "2026-10-21", "2026-10-24", "2026-10-25"]
        assert {d: repo.day(d).state for d in (D[20], D[22], D[23])} == {D[20]: "done", D[22]: "empty", D[23]: "failed"}
        assert all(repo.day(D[n]).state == "done" for n in (19, 21, 24, 25))
        # `moments_since`가 앞날을 자른다. 없으면 어제로 적고 어제만 고른다
        env.parts.state.set(MOMENTS_SINCE_KEY, "2026-10-26")
        assert days_to_queue(repo, env.parts.state, date(2026, 10, 28)) == [D[26], D[27]]
        env.parts.state.set(MOMENTS_SINCE_KEY, None)
        assert days_to_queue(repo, env.parts.state, date(2026, 10, 30)) == [date(2026, 10, 29)]
        assert env.parts.state.get(MOMENTS_SINCE_KEY) == "2026-10-29"


async def test_days_older_than_7_not_picked_no_row(tmp_path):
    async with started(tmp_path, [FakeTurn([], "")], since="2026-10-01") as env:
        say(env, kst(2026, 10, 18, 14, 0), "8일 전의 꾸민 말")
        say(env, kst(2026, 10, 19, 14, 0), "7일 전의 꾸민 말")
        await tick_at(env)
        assert prompt_days(env) == ["2026-10-19"]
        assert day_row(env, D[18]) is None
        assert sorted(env.parts.moments.days_since(date(2026, 10, 1))) == [D[n] for n in range(19, 26)]


async def test_first_run_writes_moments_since_yesterday(tmp_path):
    async with started(tmp_path, [FakeTurn([], "")]) as env:
        say(env, kst(2026, 10, 24, 14, 0), "그저께의 꾸민 말")
        say(env, kst(2026, 10, 25, 14, 0), "어제의 꾸민 말")
        await tick_at(env)
        assert env.parts.state.get(MOMENTS_SINCE_KEY) == "2026-10-25"
        assert prompt_days(env) == ["2026-10-25"] and day_row(env, D[24]) is None


async def test_moments_paused_picks_nothing(tmp_path):
    async with started(tmp_path, since="2026-10-01") as env:
        env.parts.state.set(MOMENTS_PAUSED_KEY, "1")
        say(env, kst(2026, 10, 25, 14, 0), "꾸민 말")
        await tick_at(env)
        assert env.brain.calls == [] and env.parts.moments.days_since(date(2026, 10, 1)) == {}


# --- 데이터가 없는 날 (6.2-3) ---


async def test_empty_day_no_brain_call(tmp_path):
    async with started(tmp_path, since="2026-10-24") as env:
        env.parts.conditions.upsert(D[25], 4, None)  # 컨디션만 있는 날
        await tick_at(env)
        assert env.brain.calls == []
        assert day_row(env, D[24]).state == "empty" and day_row(env, D[25]).state == "empty"
        assert build_input(env, D[25]).has_data is False


async def test_empty_day_with_later_check_not_redone(tmp_path):
    async with started(tmp_path) as env:
        await tick_at(env)
        assert day_row(env, D[25]).state == "empty"
        check(env, "물 마시기", D[25])  # 지난 날 체크(SP7은 7일 전까지 받는다)
        await tick_at(env, kst(2026, 10, 27, 4, 1))
        assert env.brain.calls == []
        assert day_row(env, D[25]).state == "empty" and day_row(env, D[26]).state == "empty"


# --- 실행 직전 다시 읽기, 멈추는 경우 (6.2-4·5) ---


async def test_reread_before_call_done_skips_brain(tmp_path):
    async with started(tmp_path, [FakeTurn([save(D[25], "산책을 즐겼어요")], "")]) as env:
        say(env, kst(2026, 10, 25, 14, 0), "꾸민 말")
        d = env.parts.dispatcher
        d.submit_moments(D[25])
        d.submit_moments(D[25])  # 겹친 작업
        await env.drain()
        assert len(env.brain.calls) == 1 and day_row(env, D[25]).state == "done"
        env.parts.moments.mark(D[24], "failed", TICK)
        say(env, kst(2026, 10, 24, 14, 0), "꾸민 말")
        d.submit_moments(D[24])
        await env.drain()
        assert len(env.brain.calls) == 1


async def test_reserve_10_calls_stops_and_keeps_pending(tmp_path):
    async with started(tmp_path) as env:
        say(env, kst(2026, 10, 25, 14, 0), "꾸민 말")
        for _ in range(env.settings.limits.daily_brain_calls - 10):
            env.parts.state.incr_usage(TODAY, "brain_calls")
        await tick_at(env)
        assert env.brain.calls == []
        row = day_row(env, D[25])
        assert (row.state, row.attempts) == ("pending", 0)
        assert env.parts.state.usage(TODAY).brain_calls == env.settings.limits.daily_brain_calls - 10


async def test_reserve_leaves_room_one_below(tmp_path):
    async with started(tmp_path, [FakeTurn([], "")]) as env:
        say(env, kst(2026, 10, 25, 14, 0), "꾸민 말")
        for _ in range(env.settings.limits.daily_brain_calls - 11):
            env.parts.state.incr_usage(TODAY, "brain_calls")
        await tick_at(env)
        assert kinds(env) == ["moments"]


async def test_auth_login_stops(tmp_path):
    async with started(tmp_path, [FakeTurn([], "")]) as env:
        say(env, kst(2026, 10, 25, 14, 0), "꾸민 말")
        for auth in ("login", "billing"):
            env.parts.state.set(BRAIN_AUTH_STATE_KEY, auth)
            env.parts.dispatcher.submit_moments(D[25])
            await env.drain()
        assert env.brain.calls == [] and day_row(env, D[25]) is None
        env.parts.state.set(BRAIN_AUTH_STATE_KEY, None)  # 두뇌를 한 번도 안 부른 설치(결정 5)는 막지 않는다
        await tick_at(env)
        assert kinds(env) == ["moments"]


async def test_limited_until_stops(tmp_path):
    async with started(tmp_path, [FakeTurn([], "")]) as env:
        say(env, kst(2026, 10, 25, 14, 0), "꾸민 말")
        env.parts.state.set(LIMITED_UNTIL_KEY, to_iso(TICK + timedelta(hours=1)))
        await tick_at(env)
        assert env.brain.calls == [] and day_row(env, D[25]).state == "pending"
        env.parts.state.set(LIMITED_UNTIL_KEY, to_iso(TICK - timedelta(minutes=1)))  # 지난 한도는 막지 않는다
        env.parts.dispatcher.submit_moments(D[25])
        await env.drain()
        assert kinds(env) == ["moments"]


# --- 결과 판정 (6.2-6) ---


async def test_rate_limited_sets_limited_and_keeps_attempts(tmp_path):
    retry = TICK + timedelta(hours=2)
    async with started(tmp_path, [FakeTurn([], "", status="rate_limited", retry_at=retry)], since="2026-10-24") as env:
        say(env, kst(2026, 10, 24, 14, 0), "꾸민 말")
        say(env, kst(2026, 10, 25, 14, 0), "꾸민 말")
        await tick_at(env)
        assert prompt_days(env) == ["2026-10-24"]  # 그 패스의 남은 날은 멈춘다
        assert env.parts.state.get(LIMITED_UNTIL_KEY) == to_iso(retry)
        for d in (D[24], D[25]):
            row = day_row(env, d)
            assert (row.state, row.attempts) == ("pending", 0)
        assert env.sender.sent == []  # 알리지 않는다


async def test_auth_error_records_brain_auth(tmp_path):
    async with started(tmp_path, [FakeTurn([], "", status="auth_error", error="login")], since="2026-10-24") as env:
        say(env, kst(2026, 10, 24, 14, 0), "꾸민 말")
        say(env, kst(2026, 10, 25, 14, 0), "꾸민 말")
        await tick_at(env)
        assert env.parts.state.get(BRAIN_AUTH_STATE_KEY) == "login"
        assert prompt_days(env) == ["2026-10-24"]
        assert (day_row(env, D[24]).state, day_row(env, D[24]).attempts) == ("pending", 0)
        assert env.sender.sent == []


async def test_judged_by_state_after_call(tmp_path):
    turn = FakeTurn(
        [save(D[25], "하나", "둘", "셋", "넷"), save(D[25], "산책을 즐겼어요", "책을 읽었어요")], "", status="max_turns",
    )
    async with started(tmp_path, [turn]) as env:
        say(env, kst(2026, 10, 25, 14, 0), "꾸민 말")
        await tick_at(env)
        row = day_row(env, D[25])
        assert (row.state, row.saved, row.attempts) == ("done", 2, 0)


async def test_all_m2_errors_stay_pending_and_count_attempt(tmp_path):
    async with started(tmp_path, [FakeTurn([save(D[25], "하나", sources=("task:999",))], "")]) as env:
        say(env, kst(2026, 10, 25, 14, 0), "꾸민 말")
        await tick_at(env)
        row = day_row(env, D[25])
        assert (row.state, row.attempts) == ("pending", 1)


async def test_two_failures_become_failed(tmp_path):
    script = [FakeTurn([], "", status="error", error="x"), FakeTurn([], "", status="error", error="timeout")]
    async with started(tmp_path, script) as env:
        say(env, kst(2026, 10, 25, 14, 0), "꾸민 말")
        await tick_at(env)
        assert (day_row(env, D[25]).state, day_row(env, D[25]).attempts) == ("pending", 1)
        await tick_at(env, kst(2026, 10, 27, 4, 1))
        assert (day_row(env, D[25]).state, day_row(env, D[25]).attempts) == ("failed", 2)
        assert day_row(env, D[26]).state == "empty"
        await tick_at(env, kst(2026, 10, 28, 4, 1))
        assert len(env.brain.calls) == 2  # `failed`는 다시 하지 않는다


async def test_failed_never_overwrites_done(tmp_path):
    async with started(tmp_path, [FakeTurn([save(D[25], "산책을 즐겼어요")], "", status="error", error="x")]) as env:
        say(env, kst(2026, 10, 25, 14, 0), "꾸민 말")
        await tick_at(env)
        row = day_row(env, D[25])
        assert (row.state, row.saved, row.attempts) == ("done", 1, 0)
        repo = env.parts.moments
        assert repo.bump_attempt(D[25], TICK, 1) == "done"
        assert (repo.day(D[25]).state, repo.day(D[25]).attempts) == ("done", 0)


async def test_ok_without_tool_call_done_zero(tmp_path):
    async with started(tmp_path, [FakeTurn([], "오늘은 남길 게 없어요")]) as env:
        say(env, kst(2026, 10, 25, 14, 0), "꾸민 말")
        await tick_at(env)
        row = day_row(env, D[25])
        assert (row.state, row.saved, row.attempts) == ("done", 0, 0)
        assert env.sender.sent == []  # 두뇌의 글은 어디에도 보내지 않는다


# --- 차례, 멈춤, 호출 모양 (6.2-4·7, 6.3) ---


async def test_user_message_and_run_go_first(tmp_path):
    script = [FakeTurn([], "안녕하세요"), FakeTurn([], "좋은 아침이에요"), FakeTurn([], "")]
    async with started(tmp_path, script) as env:
        say(env, kst(2026, 10, 25, 14, 0), "꾸민 말")
        env.clock.set(TICK)
        p = env.parts
        run = p.runs.ensure(LoopKey.morning_brief, TICK)
        p.runs.mark_queued(run.id)
        d = p.dispatcher
        d.submit_moments(D[25])
        d.submit_run(p.runs.get(run.id), [])
        d.submit_message(Inbound(text="안녕", at=TICK, sent_at=TICK, update_ids=[501]))
        await env.drain()
        assert kinds(env) == ["chat", "run", "moments"]


async def test_runs_while_paused_and_not_counted_as_proactive(tmp_path):
    async with started(tmp_path, [FakeTurn([save(D[25], "산책을 즐겼어요")], "")]) as env:
        say(env, kst(2026, 10, 25, 14, 0), "꾸민 말")
        env.parts.state.set(PAUSE_UNTIL_KEY, to_iso(TICK + timedelta(days=3)))
        await tick_at(env)
        assert kinds(env) == ["moments"] and day_row(env, D[25]).state == "done"
        assert env.parts.state.usage(TODAY).proactive_messages == 0
        assert env.sender.sent == []


async def test_call_shape(tmp_path):
    gate = asyncio.Event()
    async with started(tmp_path, [FakeTurn([], "", gate=gate)]) as env:
        say(env, kst(2026, 10, 25, 14, 0), "꾸민 말")
        before = env.parts.state.usage(TODAY).brain_calls
        env.clock.set(TICK)
        env.parts.runner.tick()
        for _ in range(200):  # 두뇌가 도는 동안: 입력 중 표시를 보내지 않는다
            await asyncio.sleep(0)
        assert len(env.brain.calls) == 1 and env.sender.typing_count == 0
        gate.set()
        await env.drain()
        (call,) = env.brain.calls
        ctx = call["run_ctx"]
        assert call["session_id"] is None and call["fork_session"] is False
        assert call["max_turns"] == 3 and call["persist_session"] is False
        assert call["system_prompt"] == moments_system_prompt()
        assert call["prompt"] == build_input(env, D[25]).text
        assert call["prompt"].startswith("## 날짜\n2026-10-25 (일)\n")
        assert (ctx.kind, ctx.conversation_id, ctx.run_id, ctx.inbound_id) == ("moments", None, None, None)
        assert (ctx.actor, ctx.activity_channel, ctx.moments_date) == ("secretary", "scheduler", D[25])
        assert ctx.moments_refs == frozenset({"chat"})
        assert env.sender.typing_count == 0
        assert env.parts.state.usage(TODAY).brain_calls == before + 1


async def test_sp1_brain_without_new_args_still_runs_chat(tmp_path):
    """채팅 호출은 새 인자를 넘기지 않는다(SP1 두뇌 구현이 그대로 돈다)."""
    async with started(tmp_path, [FakeTurn([], "안녕하세요")]) as env:
        await env.telegram("안녕")
        (call,) = env.brain.calls
        assert (call["system_prompt"], call["max_turns"], call["persist_session"]) == (None, None, True)
        assert call["run_ctx"].kind == "chat"


# --- 입력 (6.3) ---


async def test_moments_input_uses_logical_day_for_0230_completion(tmp_path):
    """Review Focus 5: 10/25 02:30에 끝낸 할 일과 01:40의 메시지는 10/24의 입력이다."""
    async with started(tmp_path, [FakeTurn([], "")], since="2026-10-24") as env:
        t = done_task(env, "포트폴리오 사례 2번 다듬기", kst(2026, 10, 25, 2, 30))
        say(env, kst(2026, 10, 25, 1, 40), "드디어 사례 하나 끝냈다")
        inp = build_input(env, D[24])
        assert f"- [task:{t.id}] 포트폴리오 사례 2번 다듬기 · 커리어" in inp.text
        assert "- 01:40 드디어 사례 하나 끝냈다" in inp.text
        assert inp.refs == frozenset({f"task:{t.id}", "chat"})
        assert build_input(env, D[25]).has_data is False
        await tick_at(env)
        assert prompt_days(env) == ["2026-10-24"]
        assert day_row(env, D[25]).state == "empty"


async def test_input_shape_matches_spec(tmp_path):
    async with started(tmp_path) as env:
        t1 = done_task(env, "포트폴리오 사례 2번 다듬기", kst(2026, 10, 24, 11, 0))
        t2 = done_task(env, "고정비 적기", kst(2026, 10, 24, 12, 0), areas=("finance",))
        h = check(env, "물 마시기", D[24])
        env.parts.conditions.upsert(D[24], 4, None)
        say(env, kst(2026, 10, 24, 14, 2), "드디어 사례 하나 끝냈다")
        inp = build_input(env, D[24])
        assert inp.text == (
            "## 날짜\n2026-10-24 (토)\n\n"
            f"## 끝낸 할 일\n- [task:{t1.id}] 포트폴리오 사례 2번 다듬기 · 커리어\n- [task:{t2.id}] 고정비 적기 · 경제\n\n"
            f"## 체크한 습관\n- [habit:{h.id}] 물 마시기 · 건강\n\n"
            "## 컨디션\n4/5\n\n"
            "## 사용자 메시지 (두 통로, 오래된 것부터)\n- 14:02 드디어 사례 하나 끝냈다"
        )
        assert inp.refs == frozenset({f"task:{t1.id}", f"task:{t2.id}", f"habit:{h.id}", "condition", "chat"})
        assert inp.has_data


async def test_input_tasks_capped_at_20(tmp_path):
    async with started(tmp_path) as env:
        ids = [done_task(env, f"꾸민 할 일 {i}", kst(2026, 10, 24, 10, i)).id for i in range(25)]
        inp = build_input(env, D[24])
        listed = [line for line in inp.text.splitlines() if line.startswith("- [task:")]
        assert len(listed) == 20
        assert inp.refs == frozenset(f"task:{i}" for i in ids[5:])  # 가장 최근 20개(시각 순으로 적는다)


async def test_input_has_user_lines_only_and_6000_chars(tmp_path):
    async with started(tmp_path) as env:
        for i in range(80):
            when = kst(2026, 10, 24, 10, 0) + timedelta(minutes=i)
            say(env, when, f"사용자{i:02d} " + "가" * 90, channel="app" if i % 2 else "telegram")
            say(env, when, f"비서의 꾸민 답 {i}", speaker="비서")
        inp = build_input(env, D[24])
        section = inp.text.split("## 사용자 메시지 (두 통로, 오래된 것부터)\n", 1)[1]
        lines = section.splitlines()
        assert "비서" not in section
        assert sum(len(line) + 1 for line in lines) <= 6000
        assert lines[-1].startswith("- 11:19 사용자79 ")  # 가장 최근 줄은 남고
        assert "사용자00" not in section  # 오래된 줄부터 뺐다
        numbers = [int(line.split()[2][3:]) for line in lines]
        assert numbers == list(range(80 - len(lines), 80))


async def test_input_does_not_read_memos(tmp_path):
    async with started(tmp_path) as env:
        done_task(env, "꾸민 할 일", kst(2026, 10, 24, 11, 0), note="꾸민 할 일 메모")
        env.parts.conditions.upsert(D[24], 3, "꾸민 컨디션 메모")
        inp = build_input(env, D[24])
        assert "메모" not in inp.text
        assert not [p for p in inspect.signature(build_moments_input).parameters if "memo" in p]


# --- 멈출 때 (Review Focus 1) ---


async def test_stop_skips_queued_moments_jobs(tmp_path):
    async with started(tmp_path, since="2026-10-23") as env:
        for n in (23, 24, 25):
            say(env, kst(2026, 10, n, 14, 0), "꾸민 말")
        p = env.parts
        env.clock.set(TICK)
        queue_moments_daily(p.dispatcher, p.moments, p.state)(TODAY)
        await p.dispatcher.stop(timeout=5)
        assert env.brain.calls == []
        assert [day_row(env, D[n]).state for n in (23, 24, 25)] == ["pending"] * 3
        assert [day_row(env, D[n]).attempts for n in (23, 24, 25)] == [0] * 3


# --- 세션 파일 (6.3, 결정 18) ---


def _session_files(tmp_path):
    proj = tmp_path / "claude" / "projects" / "-home-x"
    proj.mkdir(parents=True)
    mine = proj / f"{SID}.jsonl"
    mine.write_text("{}\n", encoding="utf-8")
    sub = proj / SID
    sub.mkdir()
    (sub / "part.jsonl").write_text("{}\n", encoding="utf-8")
    other = proj / f"{OTHER_SID}.jsonl"
    other.write_text("{}\n", encoding="utf-8")
    return mine, sub, other


async def test_session_file_removed_after_moments_call(tmp_path):
    async with started(tmp_path, [FakeTurn([save(D[25], "산책을 즐겼어요")], "", session_id=SID)], claude=True) as env:
        mine, sub, other = _session_files(tmp_path)
        say(env, kst(2026, 10, 25, 14, 0), "꾸민 말")
        await tick_at(env)
        assert not mine.exists() and not sub.exists()
        assert other.exists()


async def test_session_file_removed_even_when_brain_errors(tmp_path):
    script = [FakeTurn([], "", status="error", error="x", session_id=SID)]
    async with started(tmp_path, script, claude=True) as env:
        mine, sub, other = _session_files(tmp_path)
        say(env, kst(2026, 10, 25, 14, 0), "꾸민 말")
        await tick_at(env)
        assert not mine.exists() and not sub.exists() and other.exists()
        assert day_row(env, D[25]).attempts == 1


async def test_session_cleanup_without_any_session_id(tmp_path, caplog):
    caplog.set_level(logging.INFO)
    turn = FakeTurn([], "", session_id=None, raises=RuntimeError("두뇌 구현 오류"))
    async with started(tmp_path, [turn], claude=True) as env:
        mine, _, _ = _session_files(tmp_path)
        say(env, kst(2026, 10, 25, 14, 0), "꾸민 말")
        await tick_at(env)
        assert mine.exists()  # 세션 id를 하나도 못 봤으면 지울 것을 모른다
        cleanup = [r for r in caplog.records if r.getMessage() == "moments_session_cleanup"]
        assert [(r.removed, r.reason) for r in cleanup] == [(False, "no_session_id")]
        assert day_row(env, D[25]).state == "pending"
        assert env.parts.dispatcher.idle  # 작업자는 그대로 돈다


async def test_session_file_removed_when_brain_raises_after_seeing_id(tmp_path):
    turn = FakeTurn([], "", session_id=SID, raises=RuntimeError("두뇌 구현 오류"))
    async with started(tmp_path, [turn], claude=True) as env:
        mine, sub, other = _session_files(tmp_path)
        say(env, kst(2026, 10, 25, 14, 0), "꾸민 말")
        await tick_at(env)
        assert not mine.exists() and not sub.exists() and other.exists()


async def _until(cond, steps=400):
    for _ in range(steps):
        if cond():
            return
        await asyncio.sleep(0.005)
    raise AssertionError("조건이 끝내 서지 않았다")


async def test_session_file_removed_after_timeout(tmp_path):
    """시간 상한에 걸려 결과에 id가 없어도, 두뇌가 호출 중에 본 id로 지운다(리뷰 SHOULD 1)."""
    async with started(tmp_path, [FakeTurn([], "", session_id=SID, hang=True)], claude=True) as env:
        mine, sub, other = _session_files(tmp_path)
        d = env.parts.dispatcher
        d.settings = env.settings.model_copy(
            update={"limits": env.settings.limits.model_copy(update={"brain_timeout_s": 0.05})}
        )
        say(env, kst(2026, 10, 25, 14, 0), "꾸민 말")
        env.clock.set(TICK)
        env.parts.runner.tick()
        await _until(lambda: len(env.brain.calls) == 1 and d.idle)
        assert not mine.exists() and not sub.exists() and other.exists()
        assert (day_row(env, D[25]).state, day_row(env, D[25]).attempts) == ("pending", 1)


async def test_session_file_removed_when_stop_cancels_call(tmp_path):
    """`stop()`이 상한에 걸려 작업자를 취소해도, 본 id의 세션 파일은 지운다."""
    async with started(tmp_path, [FakeTurn([], "", session_id=SID, hang=True)], claude=True) as env:
        mine, sub, other = _session_files(tmp_path)
        say(env, kst(2026, 10, 25, 14, 0), "꾸민 말")
        env.clock.set(TICK)
        env.parts.runner.tick()
        await _until(lambda: len(env.brain.calls) == 1)
        await env.parts.dispatcher.stop(timeout=0.05)
        assert not mine.exists() and not sub.exists() and other.exists()
        row = day_row(env, D[25])
        assert (row.state, row.attempts) == ("pending", 0)


def test_session_cleanup_ignores_bad_id(tmp_path):
    base = tmp_path / "claude"
    (base / "projects" / "p").mkdir(parents=True)
    victims = [base / "x.jsonl", base / "projects" / "x.jsonl", base / "projects" / "p" / "x.jsonl"]
    for v in victims:
        v.write_text("{}\n", encoding="utf-8")
    for bad in ("../x", None, "x", "*", "-" * 36, SID.upper(), SID.replace("-", "0"), f"{SID}/../../x", "", 12):
        assert remove_session_file(bad, config_dir=base) is False
    assert all(v.exists() for v in victims)
    assert remove_session_file(SID, config_dir=tmp_path / "없는 폴더") is False


async def test_chat_calls_never_remove_session_files(tmp_path):
    script = [FakeTurn([], "안녕하세요", session_id=SID), FakeTurn([], "좋은 아침이에요", session_id=SID)]
    async with started(tmp_path, script, claude=True) as env:
        mine, sub, _ = _session_files(tmp_path)
        await env.telegram("안녕")
        env.clock.set(TICK)
        p = env.parts
        run = p.runs.ensure(LoopKey.morning_brief, TICK)
        p.runs.mark_queued(run.id)
        p.dispatcher.submit_run(p.runs.get(run.id), [])
        await env.drain()
        assert kinds(env) == ["chat", "run"]
        assert mine.exists() and sub.exists()


def test_claude_config_dir_from_env(tmp_path):
    from my_planner.harness.moments import claude_config_dir

    assert claude_config_dir({"CLAUDE_CONFIG_DIR": str(tmp_path / "cfg")}) == tmp_path / "cfg"
    assert claude_config_dir({}).name == ".claude"


# --- 따라잡기 (1장 조건 4) ---


async def test_three_days_off_catches_up_in_order(tmp_path):
    script = [FakeTurn([save(D[n], f"{n}일에 산책을 즐겼어요")], "") for n in (23, 24, 25)]
    async with started(tmp_path, script, since="2026-10-20") as env:
        for n in (20, 21, 22):
            env.parts.moments.mark(D[n], "done", TICK, saved=1)
        env.parts.state.set("last_daily_jobs_date", "2026-10-22")
        for n in (23, 24, 25):
            say(env, kst(2026, 10, n, 14, 0), f"{n}일의 꾸민 말")
        await tick_at(env)
        assert prompt_days(env) == ["2026-10-23", "2026-10-24", "2026-10-25"]
        rows = env.conn.execute("SELECT date, slot, text FROM status_moments ORDER BY id").fetchall()
        assert [tuple(r) for r in rows] == [(f"2026-10-{n}", 1, f"{n}일에 산책을 즐겼어요") for n in (23, 24, 25)]
        assert all(day_row(env, D[n]).state == "done" for n in (23, 24, 25))


# --- 로그와 원문 기록 (1장 조건 7, 6.8) ---


async def test_logs_and_transcripts_have_no_moment_text(tmp_path):
    turn = FakeTurn([save(D[25], SECRET, "지난번 실패한 일을 마쳤어요")], "", session_id=SID)
    async with started(tmp_path, [turn], claude=True) as env:
        state_dir = env.settings.paths.state_dir
        setup_logging(state_dir, 30)
        say(env, kst(2026, 10, 25, 14, 0), "꾸민 말")
        await tick_at(env)
        for h in logging.getLogger().handlers:
            h.flush()
        logs = [p for p in (state_dir / "logs").rglob("*") if p.is_file()]
        assert logs
        transcripts = [p for p in (env.settings.paths.data_dir / "transcripts").rglob("*") if p.is_file()]
        exports = [p for p in (env.settings.paths.data_dir / "exports").rglob("*") if p.is_file()]
        for path in (*logs, *transcripts, *exports):
            text = path.read_text(encoding="utf-8")
            assert SECRET not in text and "실패한 일" not in text, path
        entries = [json.loads(line) for p in logs for line in p.read_text(encoding="utf-8").splitlines() if line]
        (job,) = [e for e in entries if e.get("msg") == "moments_job"]
        assert set(job) == {"ts", "level", "logger", "msg", "date", "state", "saved", "rejected", "duration_ms"}
        assert (job["date"], job["state"], job["saved"], job["rejected"]) == ("2026-10-25", "done", 1, 1)
        (call,) = [e for e in entries if e.get("msg") == "brain_call"]
        assert call["tool_names"] == ["save_moments"]
        summaries = [r["summary"] for r in env.conn.execute("SELECT summary FROM activity WHERE kind = 'moments_saved'")]
        assert summaries == ["이룬 순간 1개 정리 (10/25)"]
        assert not [r for r in env.conn.execute("SELECT summary FROM activity") if SECRET in r["summary"]]


# --- 보관 (6.4) ---


async def test_prune_moment_days_60(tmp_path):
    async with started(tmp_path) as env:
        repo = env.parts.moments
        repo.mark(date(2026, 8, 26), "done", TICK, saved=1)
        repo.mark(date(2026, 8, 27), "done", TICK, saved=1)
        env.conn.execute(
            "INSERT INTO status_moments (date, slot, text, sources_json, created_at) VALUES (?, 1, ?, '[]', ?)",
            ("2026-08-26", "꾸민 옛 순간", to_iso(TICK)),
        )
        await tick_at(env)
        assert repo.day(date(2026, 8, 26)) is None and repo.day(date(2026, 8, 27)) is not None
        assert env.conn.execute("SELECT COUNT(*) FROM status_moments").fetchone()[0] == 1  # 순간은 지우지 않는다


@pytest.mark.parametrize("state", ["done", "empty", "failed"])
async def test_settled_days_are_not_picked(tmp_path, state):
    async with started(tmp_path) as env:
        env.parts.moments.mark(D[25], state, TICK)
        say(env, kst(2026, 10, 25, 14, 0), "꾸민 말")
        await tick_at(env)
        assert env.brain.calls == [] and day_row(env, D[25]).state == state


# --- 운동 기록 (SP12 5.6) ---


def workout_log(env, day, title):
    w = env.parts.tools.workout
    return w.add_log(day, title, None, None, None, [], env.clock.now())


def build_input_w(env, d):
    p = env.parts
    return build_moments_input(
        d, tasks=p.tasks, habits=p.habits, conditions=p.conditions, transcripts=p.transcripts,
        tz=env.settings.timezone, boundary=env.settings.day_boundary, workout=p.tools.workout,
    )


async def test_workout_section_and_source(tmp_path):
    turn = FakeTurn([save(D[25], "하체 운동을 했어요", sources=("workout:1",))], "")
    async with started(tmp_path, [turn]) as env:
        mine = workout_log(env, D[25], "하체")
        other = workout_log(env, D[24], "상체")
        assert (mine.id, other.id) == (1, 2)
        inp = build_input_w(env, D[25])
        assert "## 운동 기록\n- [workout:1] 하체" in inp.text and "상체" not in inp.text
        assert inp.refs == frozenset({"workout:1"}) and inp.has_data  # 기록만 있는 날도 돈다
        await tick_at(env)  # 기록만 있는 날도 두뇌를 부른다
        assert prompt_days(env) == ["2026-10-25"]
        row = day_row(env, D[25])
        assert (row.state, row.saved) == ("done", 1)
        (m,) = env.parts.moments.between(D[25], D[25], include_hidden=True)
        assert m.sources == ["workout:1"]


async def test_workout_source_of_other_day_rejected(tmp_path):
    turn = FakeTurn([save(D[25], "상체 운동을 했어요", sources=("workout:2",))], "")
    async with started(tmp_path, [turn]) as env:
        workout_log(env, D[25], "하체")
        workout_log(env, D[24], "상체")
        await tick_at(env)
        row = day_row(env, D[25])
        assert (row.state, row.attempts) == ("pending", 1)  # M2: 입력에 없는 참조
