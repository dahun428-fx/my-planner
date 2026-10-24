"""`POST /chat` (SP3-4 스펙 6.4.1, 7.5): AI SDK UI message stream, 재생, 끊김, 처리 중 재요청, 명령.

가짜 두뇌 + 가짜 시계(`BeEnv`). 고정 자료는 꾸며 낸 내용만 쓴다.
"""

import asyncio
from datetime import timedelta

import pytest
from be_env import BeEnv
from fakes import FakeTurn, ManualSleep
from test_dispatcher_messages import kst
from ui_stream import parse_sse, types

from my_planner.bot.commands import today_text
from my_planner.bot.telegram_io import NON_TEXT_REPLY
from my_planner.clock import to_iso
from my_planner.harness.dispatcher import (
    DAILY_CAP_REPLY,
    LOGIN_NOTICE,
    rate_limit_notice,
)
from my_planner.harness.stream import PING_INTERVAL_S, UiMessageWriter
from my_planner.store.repos.state import LIMITED_UNTIL_KEY, PAUSE_UNTIL_KEY

START = kst(2026, 10, 24, 13, 0)  # 토요일 오후. "내일"은 10/25
DENTIST = ("add_task", {"title": "치과", "areas": ["health"], "planned_for": "2026-10-25"})
FIVE_HEADERS = {
    "content-type": "text/event-stream",
    "cache-control": "no-cache",
    "x-accel-buffering": "no",
    "x-vercel-ai-ui-message-stream": "v1",
}


def _text(chunks):
    return "".join(c["delta"] for c in chunks if c["type"] == "text-delta")


def _one(chunks, kind):
    (c,) = [c for c in chunks if c["type"] == kind]
    return c


async def test_chat_stream_order_and_headers(tmp_path):
    script = [FakeTurn([DENTIST], "내일 치과를 추가할게요.")]
    async with BeEnv.start(tmp_path, start=START, script=script) as env:
        resp, raw = await env.chat("내일 치과 추가해 줘")
        pending = env.conn.execute("SELECT COUNT(*) FROM inbound_pending").fetchone()[0]
        conv = env.conn.execute("SELECT * FROM conversations").fetchone()

    chunks = parse_sse(raw)
    assert types(chunks) == [
        "start", "data-status", "start-step", "tool-input-available", "tool-output-available",
        "text-start", "text-delta", "text-end", "finish-step", "data-activity", "finish",
    ]
    assert raw.endswith(b"data: [DONE]\n\n")
    assert resp.status == 200
    for name, value in FIVE_HEADERS.items():
        assert resp.headers[name] == value
    assert resp.headers["x-conversation-id"] == str(conv["id"])
    assert conv["channel"] == "app" and conv["kind"] == "chat"
    start = chunks[0]
    assert start["messageId"] == f"m-{conv['id']}-1"  # 첫 앱 메시지의 inbound_id는 −1
    assert start["messageMetadata"] == {
        "conversation_id": conv["id"], "channel": "app", "kind": "chat", "checkin_id": None,
    }
    assert chunks[1] == {"type": "data-status", "data": {"state": "queued"}, "transient": True}
    # 두뇌 글은 text-delta 하나이고, 확인 문구는 글 조각이 아니라 data-activity에
    assert [c["delta"] for c in chunks if c["type"] == "text-delta"] == ["내일 치과를 추가할게요."]
    assert all(c.get("id") != "h-confirm" for c in chunks)
    activity = _one(chunks, "data-activity")["data"]
    assert activity["confirmation"] == "✓ 추가: 치과 → 내일"
    assert len(activity["activity_ids"]) == 1 and activity["undo_ids"] == activity["activity_ids"]
    assert chunks[-1]["messageMetadata"] == {"conversation_id": conv["id"], "channel": "app", "kind": "chat"}
    assert pending == 0


async def test_tool_chunk_name_has_no_prefix_and_output_is_utc(tmp_path):
    timed = ("add_task", {"title": "치과", "areas": ["health"], "planned_for": "2026-10-25",
                          "scheduled_at": "2026-10-25T14:00:00+09:00"})
    async with BeEnv.start(tmp_path, start=START, script=[FakeTurn([timed], "넣었어요.")]) as env:
        _, raw = await env.chat("내일 2시 치과")
        brain_ctx = env.brain.calls[0]["run_ctx"]

    tool_in = _one(parse_sse(raw), "tool-input-available")
    tool_out = _one(parse_sse(raw), "tool-output-available")
    assert tool_in["toolName"] == "add_task"
    assert tool_in["input"] == timed[1]
    assert tool_out["toolCallId"] == tool_in["toolCallId"]
    assert tool_out["output"]["scheduled_at"] == "2026-10-25T05:00:00Z"
    assert brain_ctx.channel == "app"
    # 쓰개는 MCP 이름의 앞머리를 뗀다
    from fakes import ListSink

    sink = ListSink()
    UiMessageWriter(sink, None).tool_input("tc_01", "mcp__planner__add_task", {})
    assert sink.chunks[0]["toolName"] == "add_task"


@pytest.mark.parametrize("case", ["daily_cap", "rate_limit", "login"])
async def test_daily_cap_rate_limit_login_are_text_chunks(tmp_path, case):
    script = [FakeTurn([], "", status="auth_error", error="login")] if case == "login" else []
    async with BeEnv.start(tmp_path, start=START, script=script) as env:
        if case == "daily_cap":
            env.conn.execute("INSERT INTO usage_state (date, brain_calls) VALUES ('2026-10-24', 60)")
            env.conn.commit()
            want = DAILY_CAP_REPLY
        elif case == "rate_limit":
            until = START + timedelta(hours=2)
            env.parts.state.set(LIMITED_UNTIL_KEY, to_iso(until))
            want = rate_limit_notice("15:00")
        else:
            want = LOGIN_NOTICE
        resp, raw = await env.chat("안녕")
        pending = env.conn.execute("SELECT COUNT(*) FROM inbound_pending").fetchone()[0]

    chunks = parse_sse(raw)
    assert resp.status == 200
    assert "error" not in types(chunks)
    assert _text(chunks) == want
    assert types(chunks)[-1] == "finish"
    assert pending == 0


async def test_non_text_parts_get_non_text_reply(tmp_path):
    async with BeEnv.start(tmp_path, start=START) as env:
        parts = [{"type": "file", "mediaType": "image/png", "url": "data:image/png;base64,AAAA"}]
        resp, raw = await env.chat(parts=parts)
        calls = len(env.brain.calls)
        pending = env.conn.execute("SELECT COUNT(*) FROM inbound_pending").fetchone()[0]

    chunks = parse_sse(raw)
    assert resp.status == 200
    assert _text(chunks) == NON_TEXT_REPLY
    assert calls == 0 and pending == 0


async def test_same_client_msg_id_replays_without_brain(tmp_path):
    script = [FakeTurn([DENTIST], "내일 치과를 추가할게요.")]
    async with BeEnv.start(tmp_path, start=START, script=script) as env:
        _, first = await env.chat("내일 치과 추가해 줘", client_msg_id="cm-same")
        env.clock.advance(timedelta(minutes=5))
        resp, again = await env.chat("내일 치과 추가해 줘", client_msg_id="cm-same")
        calls = len(env.brain.calls)
        tasks = env.conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]

    a, b = parse_sse(first), parse_sse(again)
    assert calls == 1 and tasks == 1
    assert b[0]["messageId"] == a[0]["messageId"]
    assert resp.headers["x-conversation-id"] == str(a[0]["messageMetadata"]["conversation_id"])
    assert types(b) == ["start", "start-step", "text-start", "text-delta", "text-end", "finish-step",
                        "data-activity", "finish"]
    assert _text(b) == _text(a) == "내일 치과를 추가할게요."
    assert _one(b, "data-activity")["data"] == _one(a, "data-activity")["data"]


async def test_disconnect_mid_stream_completes(tmp_path):
    gate = asyncio.Event()
    script = [FakeTurn([DENTIST], "내일 치과를 추가할게요.", gate=gate)]
    async with BeEnv.start(tmp_path, start=START, script=script) as env:
        resp = await env.post("/chat", json=env.chat_body("내일 치과 추가해 줘", client_msg_id="cm-gone"))
        while b"tool-output-available" not in await resp.content.readline():
            pass
        resp.close()  # 브라우저가 떠났다(M7)
        gate.set()
        await env.drain()
        titles = [r["title"] for r in env.conn.execute("SELECT title FROM tasks")]
        stored = env.parts.idempotency.get("cm-gone")
        pending = env.conn.execute("SELECT COUNT(*) FROM inbound_pending").fetchone()[0]
        conv_id = stored.conversation_id
        lines = env.parts.transcripts.messages(conv_id)
        _, replay = await env.chat("내일 치과 추가해 줘", client_msg_id="cm-gone")

    assert titles == ["치과"]
    assert stored.endpoint == "chat"
    assert stored.body["reply_text"] == "내일 치과를 추가할게요."
    assert stored.body["confirmation"] == "✓ 추가: 치과 → 내일"
    assert pending == 0
    assert [(m.speaker, m.channel) for m in lines] == [("사용자", "app"), ("비서", "app")]
    assert lines[1].id == f"m-{conv_id}-1" and lines[1].tools == ["add_task"]
    assert _text(parse_sse(replay)) == "내일 치과를 추가할게요."


async def test_inflight_duplicate_attaches_single_brain_call(tmp_path):
    gate = asyncio.Event()
    script = [FakeTurn([DENTIST], "내일 치과를 추가할게요.", gate=gate)]
    async with BeEnv.start(tmp_path, start=START, script=script) as env:
        body = env.chat_body("내일 치과 추가해 줘", client_msg_id="cm-twice")

        async def send():
            resp = await env.post("/chat", json=body)
            return resp, await resp.read()

        first = asyncio.create_task(send())
        while not env.brain.calls:
            await asyncio.sleep(0)
        second = asyncio.create_task(send())
        for _ in range(50):
            await asyncio.sleep(0)
        gate.set()
        (r1, b1), (r2, b2) = await asyncio.gather(first, second)
        await env.drain()
        calls = len(env.brain.calls)

    assert calls == 1
    assert parse_sse(b1) == parse_sse(b2)
    assert r2.headers["x-conversation-id"] == r1.headers["x-conversation-id"]


async def test_ping_every_15s_while_queued(tmp_path):
    sleep = ManualSleep()
    gate = asyncio.Event()
    script = [FakeTurn([], "먼저 온 것", gate=gate), FakeTurn([], "기다린 것")]
    async with BeEnv.start(tmp_path, start=START, script=script, api_sleep=sleep) as env:

        async def send(text):
            resp = await env.post("/chat", json=env.chat_body(text))
            return await resp.read()

        first = asyncio.create_task(send("하나"))
        while not env.brain.calls:
            await asyncio.sleep(0)
        second = asyncio.create_task(send("둘"))

        async def settle():  # 두 연결이 받은 조각을 다 쓰고 기다릴 때까지
            for _ in range(100):
                await asyncio.sleep(0)
            assert sleep.pending == 2

        for _ in range(2):  # 15초가 두 번 지난다
            await settle()
            sleep.fire()
        await settle()
        gate.set()
        _, waited = await asyncio.gather(first, second)
        await env.drain()

    assert set(sleep.seconds) == {PING_INTERVAL_S}
    assert waited.count(b": ping\n\n") >= 2
    head = waited.split(b": ping\n\n")[0]
    assert b'"state":"queued"' in head  # 기다리는 동안이다: queued 뒤, 두뇌 조각 전
    assert b"start-step" not in head
    assert _text(parse_sse(waited)) == "기다린 것"


async def test_commands_in_app(tmp_path):
    script = [FakeTurn([], "어떤 순서로 할지 같이 정해 봐요.")]
    async with BeEnv.start(tmp_path, start=START, script=script) as env:
        _, today = await env.chat("/today")
        p = env.parts
        want_today = today_text(p.tasks, env.clock.now(), env.settings.timezone, env.settings.day_boundary)

        _, paused = await env.chat("/pause 3", client_msg_id="cm-pause")
        until = p.state.get(PAUSE_UNTIL_KEY)
        env.clock.advance(timedelta(hours=1))
        _, paused_again = await env.chat("/pause 3", client_msg_id="cm-pause")
        until_again = p.state.get(PAUSE_UNTIL_KEY)
        calls_before_plan = len(env.brain.calls)

        _, plan = await env.chat("/plan 이사 준비")
        prompt = env.brain.prompts[-1]
        convs = env.conn.execute("SELECT kind, channel FROM conversations").fetchall()
        pending = env.conn.execute("SELECT COUNT(*) FROM inbound_pending").fetchone()[0]

    assert _text(parse_sse(today)) == want_today
    assert calls_before_plan == 0
    assert _text(parse_sse(paused_again)) == _text(parse_sse(paused))
    assert until_again == until  # 같은 client_msg_id: 다시 실행하지 않았다
    plan_chunks = parse_sse(plan)
    assert plan_chunks[0]["messageMetadata"]["kind"] == "plan"
    assert "이사 준비" in prompt
    assert [(r["kind"], r["channel"]) for r in convs] == [("plan", "app")]
    assert _text(plan_chunks) == "어떤 순서로 할지 같이 정해 봐요."
    assert pending == 0


async def test_chat_rejects_bad_body_and_reused_id(tmp_path):
    async with BeEnv.start(tmp_path, start=START) as env:
        bad = await env.post("/chat", json={"message": {"role": "user", "parts": []}})
        status, _ = await env.action("record_condition", {"score": 3}, client_msg_id="cm-used")
        bad_body = await bad.json()
        reused = await env.post("/chat", json=env.chat_body("안녕", client_msg_id="cm-used"))
        reused_body = await reused.json()

    assert status == 200
    assert bad.status == 400 and bad_body["error"]["code"] == "invalid_request"
    assert reused.status == 409 and reused_body["error"]["code"] == "conflict"


async def test_chat_stream_carries_cors_headers(tmp_path):
    origin = "https://ops.example.test"
    script = [FakeTurn([], "안녕하세요.")]
    from my_planner.config import ApiConfig

    async with BeEnv.start(tmp_path, start=START, script=script,
                           overrides={"api": ApiConfig(cors_origins=[origin])}) as env:
        resp = await env.post("/chat", json=env.chat_body("안녕"), headers={"Origin": origin})
        await resp.read()
        await env.drain()

    assert resp.headers["Access-Control-Allow-Origin"] == origin
    assert "x-conversation-id" in resp.headers["Access-Control-Expose-Headers"]

