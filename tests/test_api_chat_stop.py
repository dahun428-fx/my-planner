"""`POST /chat/stop`: 기다리는 답, 처리 중인 답, 끝난 답, 모르는 id. 멈춘 뒤 다음 메시지는 보통으로 답한다.

가짜 두뇌 + 가짜 시계(`BeEnv`). 고정 자료는 꾸며 낸 내용만 쓴다.
"""

import asyncio
import logging

from be_env import BeEnv
from fakes import FakeTurn
from test_dispatcher_messages import kst
from ui_stream import parse_sse

from my_planner.harness.dispatcher import STOPPED_REPLY

START = kst(2026, 10, 24, 13, 0)
DENTIST = ("add_task", {"title": "치과", "areas": ["health"], "planned_for": "2026-10-25"})


def _text(chunks):
    return "".join(c["delta"] for c in chunks if c["type"] == "text-delta")


async def _until(cond):
    for _ in range(500):
        if cond():
            return
        await asyncio.sleep(0)
    raise AssertionError("기다린 상태가 오지 않았다")


async def _open_chat(env, text, cmid):
    """`POST /chat`을 보내고 스트림을 끝까지 읽는 작업(멈추기를 그 사이에 보낸다)."""

    async def go():
        resp = await env.post("/chat", json=env.chat_body(text, client_msg_id=cmid))
        return await resp.read()

    return asyncio.create_task(go())


async def _stop(env, cmid):
    resp = await env.post("/chat/stop", json={"client_msg_id": cmid})
    return resp.status, await resp.json()


async def test_stop_queued_message_never_reaches_brain(tmp_path):
    gate = asyncio.Event()
    script = [FakeTurn([], "먼저 온 답", gate=gate)]  # 멈춘 메시지 몫의 차례는 없다: 부르면 FakeBrain이 실패한다
    async with BeEnv.start(tmp_path, start=START, script=script) as env:
        first = await _open_chat(env, "먼저", "cm-first")
        await _until(lambda: env.brain.calls)
        waiting = await _open_chat(env, "기다리는 것", "cm-wait")
        await _until(lambda: env.parts.dispatcher.has_inflight("cm-wait"))
        status, body = await _stop(env, "cm-wait")
        stopped_raw = await waiting
        gate.set()
        first_raw = await first
        await env.drain()
        calls = len(env.brain.calls)
        stored = env.parts.idempotency.get("cm-wait")
        pending = env.conn.execute("SELECT COUNT(*) FROM inbound_pending").fetchone()[0]
        lines = env.parts.transcripts.messages(stored.conversation_id)
        _, replay = await env.chat("기다리는 것", client_msg_id="cm-wait")  # 같은 id로 다시 보내도 두뇌를 부르지 않는다
        again = await _stop(env, "cm-wait")
        calls_after = len(env.brain.calls)

    assert (status, body) == (200, {"state": "stopped"})
    chunks = parse_sse(stopped_raw)
    assert _text(chunks) == STOPPED_REPLY
    assert chunks[-1]["type"] == "finish" and stopped_raw.endswith(b"data: [DONE]\n\n")
    assert _text(parse_sse(first_raw)) == "먼저 온 답"
    assert calls == calls_after == 1
    assert stored.endpoint == "chat" and stored.body["reply_text"] == STOPPED_REPLY
    assert stored.body["message_id"] == chunks[0]["messageId"]
    assert pending == 0
    # 보통 답처럼 그 대화에 사용자 줄과 멈춘 답(재생과 기록이 같은 글)
    said = [(m.speaker, m.text, m.id) for m in lines]
    assert ("비서", STOPPED_REPLY, chunks[0]["messageId"]) in said
    assert [t for s, t, _ in said if s == "사용자"] == ["먼저", "기다리는 것"]
    assert _text(parse_sse(replay)) == STOPPED_REPLY
    assert again == (200, {"state": "done"})


async def test_stop_running_keeps_writes_and_records_stopped_reply(tmp_path, caplog):
    gate = asyncio.Event()
    script = [FakeTurn([DENTIST], "내일 치과를 추가할게요.", deltas=["내일 치과를 "], gate=gate)]
    async with BeEnv.start(tmp_path, start=START, script=script) as env:
        caplog.set_level(logging.INFO)
        task = await _open_chat(env, "내일 치과 추가해 줘", "cm-run")
        await _until(lambda: env.brain.calls)
        status, body = await _stop(env, "cm-run")
        raw = await asyncio.wait_for(task, 5)  # 두뇌는 끝나지 않았다(gate): 멈추기가 끊었다
        await env.drain()
        titles = [r["title"] for r in env.conn.execute("SELECT title FROM tasks")]
        stored = env.parts.idempotency.get("cm-run")
        pending = env.conn.execute("SELECT COUNT(*) FROM inbound_pending").fetchone()[0]
        lines = env.parts.transcripts.messages(stored.conversation_id)
        _, replay = await env.chat("내일 치과 추가해 줘", client_msg_id="cm-run")
        calls = len(env.brain.calls)

    assert (status, body) == (200, {"state": "stopped"})
    chunks = parse_sse(raw)
    assert _text(chunks) == "내일 치과를 " + STOPPED_REPLY  # 이미 나간 글 + 멈춘 문구(새 글 블록)
    assert chunks[-1]["type"] == "finish"
    activity = next(c for c in chunks if c["type"] == "data-activity")["data"]
    assert activity["confirmation"] == "✓ 추가: 치과 → 내일"  # 이미 한 쓰기는 그대로, 확인 문구도 보통 답처럼
    assert len(activity["undo_ids"]) == 1
    assert titles == ["치과"]
    assert calls == 1
    assert stored.body["reply_text"] == f"내일 치과를\n\n{STOPPED_REPLY}"
    assert stored.body["confirmation"] == "✓ 추가: 치과 → 내일"
    assert pending == 0
    assert [(m.speaker, m.channel) for m in lines] == [("사용자", "app"), ("비서", "app")]
    assert lines[1].text == f"내일 치과를\n\n{STOPPED_REPLY}\n\n✓ 추가: 치과 → 내일"
    assert lines[1].tools == ["add_task"] and lines[1].id == chunks[0]["messageId"]
    replayed = parse_sse(replay)
    assert _text(replayed) == f"내일 치과를\n\n{STOPPED_REPLY}"
    assert next(c for c in replayed if c["type"] == "data-activity")["data"]["confirmation"] == "✓ 추가: 치과 → 내일"
    stops = [r for r in caplog.records if r.getMessage() == "chat_stopped"]
    assert [r.state for r in stops] == ["stopped"]
    assert all("치과" not in str(vars(r)) for r in stops)  # 본문과 도구 인자는 남기지 않는다


async def test_next_message_after_stop_is_answered_on_a_fresh_session(tmp_path):
    gate = asyncio.Event()
    script = [
        FakeTurn([], "안녕하세요.", session_id="s1"),
        FakeTurn([], "끝나지 않을 답", session_id="s1", deltas=["길게 "], gate=gate),
        FakeTurn([], "다시 답해요.", session_id="s2"),
    ]
    async with BeEnv.start(tmp_path, start=START, script=script) as env:
        _, first = await env.chat("안녕")
        conv_id = parse_sse(first)[0]["messageMetadata"]["conversation_id"]
        task = await _open_chat(env, "길게 말해 줘", "cm-long")
        await _until(lambda: len(env.brain.calls) == 2)
        assert (await _stop(env, "cm-long"))[1] == {"state": "stopped"}
        await task
        await env.drain()
        session_after_stop = env.conn.execute("SELECT session_id FROM conversations WHERE id = ?", (conv_id,)).fetchone()[0]
        _, third = await env.chat("다시", conversation_id=conv_id)
        sessions = env.brain.session_ids
        prompts = env.brain.prompts
        session_now = env.conn.execute("SELECT session_id FROM conversations WHERE id = ?", (conv_id,)).fetchone()[0]

    assert sessions[:2] == [None, "s1"]
    # 두뇌 호출을 도중에 끊었다: 반쯤 쓴 세션은 잇지 않는다. 다음 메시지는 새 세션 + 이 대화의 최근 원문
    assert session_after_stop is None
    assert sessions[2] is None
    assert "## 최근 대화" in prompts[2] and STOPPED_REPLY in prompts[2]
    assert _text(parse_sse(third)) == "다시 답해요."
    assert parse_sse(third)[0]["messageMetadata"]["conversation_id"] == conv_id
    assert session_now == "s2"


async def test_stop_running_then_queued_one_is_answered(tmp_path):
    """앱 메시지는 묶지 않는다(M2): 멈춘 것은 그 메시지 하나뿐이고, 뒤에 기다리던 메시지는 보통으로 답한다."""
    gate = asyncio.Event()
    script = [FakeTurn([], "멈출 답", gate=gate), FakeTurn([], "두 번째 답")]
    async with BeEnv.start(tmp_path, start=START, script=script) as env:
        running = await _open_chat(env, "하나", "cm-one")
        await _until(lambda: env.brain.calls)
        queued = await _open_chat(env, "둘", "cm-two")
        await _until(lambda: env.parts.dispatcher.has_inflight("cm-two"))
        assert (await _stop(env, "cm-one"))[1] == {"state": "stopped"}
        one, two = await asyncio.gather(running, queued)
        await env.drain()
        replies = {c: env.parts.idempotency.get(c).body["reply_text"] for c in ("cm-one", "cm-two")}
        idle = env.parts.dispatcher.idle

    assert _text(parse_sse(one)) == STOPPED_REPLY
    assert _text(parse_sse(two)) == "두 번째 답"
    assert replies == {"cm-one": STOPPED_REPLY, "cm-two": "두 번째 답"}
    assert idle  # 작업자는 계속 돈다


async def test_stop_during_retry_wait_does_not_call_again(tmp_path):
    script = [FakeTurn([], "", status="error", error="x")]  # 두 번째 호출은 없다(부르면 FakeBrain이 실패한다)
    async with BeEnv.start(tmp_path, start=START, script=script) as env:
        waits: list[asyncio.Event] = []

        async def held_sleep(_seconds):
            e = asyncio.Event()
            waits.append(e)
            await e.wait()

        env.parts.dispatcher._sleep = held_sleep
        task = await _open_chat(env, "안녕", "cm-retry")
        await _until(lambda: waits)
        assert (await _stop(env, "cm-retry"))[1] == {"state": "stopped"}
        raw = await asyncio.wait_for(task, 5)
        await env.drain()
        calls = len(env.brain.calls)

    assert calls == 1
    assert _text(parse_sse(raw)) == STOPPED_REPLY


async def test_stop_attached_stream_gets_stopped_reply(tmp_path):
    """같은 `client_msg_id`로 붙은 두 번째 연결(M8)도 멈춘 답과 `finish`를 받는다."""
    gate = asyncio.Event()
    async with BeEnv.start(tmp_path, start=START, script=[FakeTurn([], "답", gate=gate)]) as env:
        a = await _open_chat(env, "안녕", "cm-both")
        await _until(lambda: env.brain.calls)
        b = await _open_chat(env, "안녕", "cm-both")
        for _ in range(50):
            await asyncio.sleep(0)
        await _stop(env, "cm-both")
        ra, rb = await asyncio.gather(a, b)
        await env.drain()

    assert _text(parse_sse(ra)) == _text(parse_sse(rb)) == STOPPED_REPLY
    assert parse_sse(rb)[-1]["type"] == "finish"


async def test_stop_done_unknown_and_bad_body(tmp_path):
    async with BeEnv.start(tmp_path, start=START, script=[FakeTurn([], "끝난 답")]) as env:
        await env.chat("안녕", client_msg_id="cm-done")
        done = await _stop(env, "cm-done")
        unknown = await _stop(env, "cm-never")
        lines_before = len(env.parts.transcripts.messages(env.parts.idempotency.get("cm-done").conversation_id))
        bad = await env.post("/chat/stop", json={"client_msg_id": ""})
        no_auth = await env.request("POST", "/chat/stop", token=None, json={"client_msg_id": "cm-done"})
        stored = env.parts.idempotency.get("cm-done")

    assert done == (200, {"state": "done"})
    assert unknown == (200, {"state": "unknown"})
    assert bad.status == 400 and no_auth.status == 401
    assert stored.body["reply_text"] == "끝난 답"  # 끝난 답은 그대로 둔다
    assert lines_before == 2


async def test_stop_row_without_slot_finishes_it(tmp_path):
    """행은 있는데 처리 자리가 없다(처리 중 예외 뒤): 다시 넣지 않고 멈춘 답으로 마친다."""
    async with BeEnv.start(tmp_path, start=START, script=[]) as env:
        d = env.parts.dispatcher
        now = env.clock.now()
        conv = d.route_app_message(now, conversation_id=None, checkin_id=None)
        iid = d.state.next_app_inbound_id()
        d.state.add_pending_inbound(iid, "남은 글", now, now, channel="app", client_msg_id="cm-left", conversation_id=conv.id)
        got = await _stop(env, "cm-left")
        stored = env.parts.idempotency.get("cm-left")
        pending = env.conn.execute("SELECT COUNT(*) FROM inbound_pending").fetchone()[0]
        _, replay = await env.chat("남은 글", client_msg_id="cm-left")

    assert got == (200, {"state": "stopped"})
    assert stored.body["reply_text"] == STOPPED_REPLY and pending == 0
    assert _text(parse_sse(replay)) == STOPPED_REPLY
    assert env.brain.calls == []


async def test_stop_finish_error_keeps_the_worker(tmp_path, caplog):
    """마무리(`_finish_stopped`)가 실패해도 작업자는 산다: 스트림은 일반 문구로 닫히고 다음 메시지에 답한다."""
    from my_planner.harness.dispatcher import FALLBACK_REPLY

    gate = asyncio.Event()
    script = [FakeTurn([], "끝나지 않을 답", gate=gate), FakeTurn([], "다음 답")]
    async with BeEnv.start(tmp_path, start=START, script=script) as env:
        caplog.set_level(logging.INFO)
        d = env.parts.dispatcher

        async def broken(slot, stop):
            raise RuntimeError("boom")

        d._finish_stopped = broken
        task = await _open_chat(env, "안녕", "cm-broken")
        await _until(lambda: env.brain.calls)
        await _stop(env, "cm-broken")
        raw = await asyncio.wait_for(task, 5)
        await env.drain()
        _, after = await env.chat("다음")
        worker_alive = d._worker is not None and not d._worker.done()

    assert _text(parse_sse(raw)) == FALLBACK_REPLY
    assert _text(parse_sse(after)) == "다음 답"
    assert worker_alive
    assert any(r.getMessage() == "message_stop_error" for r in caplog.records)


async def test_stop_waiting_db_failure_leaves_the_slot(tmp_path):
    """기다리는 메시지의 DB 마무리가 실패하면 자리를 그대로 두고 올린다: 작업자가 보통처럼 답한다."""
    import sqlite3

    import pytest

    gate = asyncio.Event()
    script = [FakeTurn([], "먼저 온 답", gate=gate), FakeTurn([], "기다린 답")]
    async with BeEnv.start(tmp_path, start=START, script=script) as env:
        d = env.parts.dispatcher
        first = await _open_chat(env, "먼저", "cm-a")
        await _until(lambda: env.brain.calls)
        waiting = await _open_chat(env, "기다리는 것", "cm-b")
        await _until(lambda: d.has_inflight("cm-b"))
        real = d.state.finish_app_inbound

        def fail(*a, **kw):
            raise sqlite3.OperationalError("database is locked")

        d.state.finish_app_inbound = fail
        with pytest.raises(sqlite3.OperationalError):
            d.stop_message("cm-b")
        d.state.finish_app_inbound = real
        still = d.has_inflight("cm-b")
        dropped = set(d._dropped)
        gate.set()
        await first
        raw = await waiting
        await env.drain()
        lines = env.parts.transcripts.messages(env.parts.idempotency.get("cm-b").conversation_id)

    assert still and dropped == set()
    assert _text(parse_sse(raw)) == "기다린 답"
    assert STOPPED_REPLY not in [m.text for m in lines]  # 실패한 멈춤은 원문 기록에 남지 않는다


async def test_stop_after_the_last_brain_call_is_done(tmp_path):
    """마지막 두뇌 호출 뒤(그 답으로 마치는 중)의 멈추기는 `done`이고 답은 그대로 간다."""
    gate = asyncio.Event()
    async with BeEnv.start(tmp_path, start=START, script=[FakeTurn([], "진짜 답", gate=gate)]) as env:
        d = env.parts.dispatcher
        task = await _open_chat(env, "안녕", "cm-late")
        await _until(lambda: env.brain.calls)
        d._cur.past_stop = True  # 마지막 호출이 막 끝난 자리(실제로는 그 사이에 기다림이 없어 시험으로만 만든다)
        got = await _stop(env, "cm-late")
        gate.set()
        raw = await task
        await env.drain()

    assert got == (200, {"state": "done"})
    assert _text(parse_sse(raw)) == "진짜 답"


async def test_stop_keeps_the_rate_limit_of_a_call_that_just_ended(tmp_path):
    """끊기 전에 사용 한도로 끝난 호출: 멈춰도 `limited_until`을 적고, 세션은 비운다."""
    from datetime import timedelta

    from my_planner.harness.brain import BrainResult
    from my_planner.store.repos.state import LIMITED_UNTIL_KEY

    until = START + timedelta(hours=2)
    async with BeEnv.start(tmp_path, start=START, script=[FakeTurn([], "안녕하세요.", session_id="s1")]) as env:
        d = env.parts.dispatcher
        _, first = await env.chat("안녕")
        conv_id = parse_sse(first)[0]["messageMetadata"]["conversation_id"]

        async def limited_run(prompt, *, session_id, run_ctx, **kw):
            d.stop_message("cm-limit")  # 호출이 돌아오기 직전에 멈추기가 왔다
            return BrainResult(text="", session_id=session_id, turns=0, status="rate_limited", retry_at=until)

        env.brain.run = limited_run
        _, raw = await env.chat("다시", client_msg_id="cm-limit", conversation_id=conv_id)
        limited = d.state.get(LIMITED_UNTIL_KEY)
        session = env.conn.execute("SELECT session_id FROM conversations WHERE id = ?", (conv_id,)).fetchone()[0]

    assert _text(parse_sse(raw)) == STOPPED_REPLY
    assert limited is not None
    assert session is None
