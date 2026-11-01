"""즉시 판단 (SP14 스펙 7장, T8, Review Focus 5): 메이트 대화의 "새로 생긴 것" 블록. `BeEnv` + `FakeBrain`.

내용은 모두 꾸며 낸 것이다(사건에는 종류·ref·영역·날짜만 있다).
"""

from __future__ import annotations

import asyncio
from datetime import date, timedelta

from be_env import BeEnv
from fakes import FakeTurn
from test_dispatcher_messages import kst

from my_planner.store.db import transaction

START = kst(2026, 11, 2, 13, 0)
TODAY = date(2026, 11, 2)
HEAD = "## 새로 생긴 것 (지난 대화 뒤)"

_seq = iter(range(1, 1_000_000))


def ev(env, kind, ref, day=TODAY, area=None, to=("mate", "manager")):
    when = kst(2026, 10, 1, 0, 0) + timedelta(seconds=next(_seq))
    with transaction(env.conn):
        return env.parts.agents.add_event(kind, ref, area, "app", day, to=to, now=when)


def seen(env, agent="mate"):
    return env.conn.execute(
        "SELECT event_id, seen_at FROM agent_inbox WHERE agent = ? ORDER BY event_id", (agent,)
    ).fetchall()


def unseen_count(env):
    return sum(1 for r in seen(env) if r["seen_at"] is None)


async def _until(cond):
    for _ in range(500):
        if cond():
            return
        await asyncio.sleep(0)
    raise AssertionError("기다린 상태가 오지 않았다")


def ok(text="응"):
    return FakeTurn([], text)


async def test_instant_block_prepended_and_marked_seen(tmp_path):
    async with BeEnv.start(tmp_path, start=START, script=[ok(), ok()]) as env:
        ev(env, "habit_checked", "habit:1", area="body")
        ev(env, "task_done", "task:2")
        _, _ = await env.chat("안녕", agent="mate")
        first = env.brain.prompts[0]
        rows = seen(env)
        env.clock.advance(timedelta(minutes=1))
        conv = env.conn.execute("SELECT id FROM conversations WHERE agent = 'mate'").fetchone()["id"]
        await env.chat("또", agent="mate", conversation_id=conv)
        second = env.brain.prompts[1]

    assert HEAD in first and "habit:1" in first and "task:2" in first
    assert first.index(HEAD) < first.index("## 메시지")
    assert len(rows) == 2 and all(r["seen_at"] is not None for r in rows)
    assert HEAD not in second


async def test_event_mid_conversation_attached_next_message(tmp_path):
    async with BeEnv.start(tmp_path, start=START, script=[ok(), ok()]) as env:
        await env.chat("안녕", agent="mate")
        conv = env.conn.execute("SELECT id FROM conversations WHERE agent = 'mate'").fetchone()["id"]
        env.clock.advance(timedelta(minutes=1))
        status, body = await env.action(
            "create_event", {"title": "치과", "date": "2026-11-03", "time": "10:00", "remind_min": 30}
        )
        assert status == 200, body
        await env.chat("또", agent="mate", conversation_id=conv)
        second = env.brain.prompts[1]

    assert HEAD in second
    lines = [ln for ln in second.splitlines() if ln.startswith("- event_added event:")]
    assert len(lines) == 1
    assert "치과" not in second.split("## 메시지")[0].split(HEAD)[1]


async def test_instant_block_not_marked_on_failure(tmp_path):
    script = [FakeTurn([], "", status="error", error="boom") for _ in range(4)]
    async with BeEnv.start(tmp_path, start=START, script=script) as env:
        ev(env, "task_done", "task:1")
        await env.chat("안녕", agent="mate")
        calls = len(env.brain.calls)
        left = unseen_count(env)

    assert calls == 4
    assert left == 1


async def test_instant_block_not_marked_on_stop(tmp_path):
    gate = asyncio.Event()
    async with BeEnv.start(tmp_path, start=START, script=[FakeTurn([], "답", gate=gate)]) as env:
        ev(env, "task_done", "task:1")

        async def go():
            resp = await env.post("/chat", json=env.chat_body("안녕", client_msg_id="cm-s", agent="mate"))
            return await resp.read()

        task = asyncio.create_task(go())
        await _until(lambda: env.brain.calls)
        resp = await env.post("/chat/stop", json={"client_msg_id": "cm-s"})
        assert resp.status == 200
        gate.set()
        await task
        await env.drain()
        left = unseen_count(env)

    assert left == 1


async def test_instant_block_capped_30_newest(tmp_path):
    async with BeEnv.start(tmp_path, start=START, script=[ok()]) as env:
        for i in range(1, 36):
            ev(env, "task_done", f"task:{i}")
        await env.chat("안녕", agent="mate")
        prompt = env.brain.prompts[0]
        left = unseen_count(env)

    lines = [ln for ln in prompt.split(HEAD)[1].split("## 메시지")[0].splitlines() if ln.startswith("- ")]
    assert len(lines) == 30
    assert lines[0].startswith("- task_done task:6 ") and lines[-1].startswith("- task_done task:35 ")
    assert left == 5


async def test_window_is_seven_days_inclusive(tmp_path):
    async with BeEnv.start(tmp_path, start=START, script=[ok()]) as env:
        ev(env, "task_done", "task:1", day=TODAY - timedelta(days=8))
        ev(env, "task_done", "task:2", day=TODAY - timedelta(days=7))
        await env.chat("안녕", agent="mate")
        prompt = env.brain.prompts[0]

    assert "task:2" in prompt and "task:1" not in prompt


async def test_secretary_chat_has_no_inbox_block(tmp_path):
    async with BeEnv.start(tmp_path, start=START, script=[ok()]) as env:
        ev(env, "task_done", "task:1")
        await env.chat("안녕")
        prompt = env.brain.prompts[0]
        left = unseen_count(env)

    assert HEAD not in prompt and "task:1" not in prompt
    assert left == 1
