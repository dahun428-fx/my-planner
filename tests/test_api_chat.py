"""`POST /chat` (SP3-4 스펙 6.4.1, 7.5): AI SDK UI message stream, 재생, 끊김, 처리 중 재요청, 명령.

가짜 두뇌 + 가짜 시계(`BeEnv`). 고정 자료는 꾸며 낸 내용만 쓴다.
"""

import asyncio
import json
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
        "start", "data-status", "data-status", "start-step", "tool-input-available", "tool-output-available",
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
    assert chunks[2] == {"type": "data-status", "data": {"state": "thinking"}, "transient": True}  # 두뇌가 시작했다
    # 두뇌 글은 text-delta 하나이고, 확인 문구는 글 조각이 아니라 data-activity에
    assert [c["delta"] for c in chunks if c["type"] == "text-delta"] == ["내일 치과를 추가할게요."]
    assert all(c.get("id") != "h-confirm" for c in chunks)
    activity = _one(chunks, "data-activity")["data"]
    assert activity["confirmation"] == "✓ 추가: 치과 → 내일"
    assert len(activity["activity_ids"]) == 1 and activity["undo_ids"] == activity["activity_ids"]
    assert chunks[-1]["messageMetadata"] == {"conversation_id": conv["id"], "channel": "app", "kind": "chat"}
    assert pending == 0


async def test_chat_stream_order_with_deltas(tmp_path):
    """06b: `deltas`가 있으면 글이 도구 조각보다 앞서 조각으로 가고, 끝난 뒤 글 블록을 다시 보내지 않는다."""
    script = [FakeTurn([DENTIST], "내일 치과를 추가할게요.", deltas=["내일 치과를 ", "추가할게요."])]
    async with BeEnv.start(tmp_path, start=START, script=script) as env:
        _, raw = await env.chat("내일 치과 추가해 줘")

    chunks = parse_sse(raw)
    assert types(chunks) == [
        "start", "data-status", "data-status", "start-step", "text-start", "text-delta", "text-delta", "text-end",
        "tool-input-available", "tool-output-available", "finish-step", "data-activity", "finish",
    ]
    assert [c["delta"] for c in chunks if c["type"] == "text-delta"] == ["내일 치과를 ", "추가할게요."]
    assert all(c.get("id") != "h-confirm" for c in chunks)  # 확인 문구는 글 조각이 아니다
    assert _one(chunks, "data-activity")["data"]["confirmation"] == "✓ 추가: 치과 → 내일"


async def test_streamed_flag_skips_text_block_and_unflagged_text_is_sent():
    from fakes import ListSink

    from my_planner.harness.dispatcher import Outbound
    from my_planner.harness.stream import AppReplySender

    async def reply(streamed: list[str], text: str, flag: bool) -> list[str]:
        sink = ListSink()
        w = UiMessageWriter(sink, None)
        w.start_step()
        if streamed:
            w.text_start("t1")
            for d in streamed:
                w.text_delta("t1", d)
            w.text_end("t1")
        await AppReplySender().send(Outbound(text=text, channel="app", writer=w, streamed=flag))
        return [c["delta"] for c in sink.chunks if c["type"] == "text-delta"]

    assert await reply(["안녕", "하세요"], "안녕하세요", True) == ["안녕", "하세요"]  # 조각으로 나갔다: 다시 안 보낸다
    assert await reply([], "안녕하세요", False) == ["안녕하세요"]  # 조각이 없으면 06 그대로
    # 같은 글이어도 flag가 없으면(고정 안내) 보낸다: 글 비교로 삼키지 않는다
    assert await reply(["끝 문구"], "끝 문구", False) == ["끝 문구", "끝 문구"]


@pytest.mark.parametrize("case", ["login", "rate_limit", "error_fallback", "max_turns"])
async def test_fixed_notice_is_sent_after_partial_deltas(tmp_path, case):
    from my_planner.harness.dispatcher import FALLBACK_REPLY, MAX_TURNS_REPLY

    part = ["일부 글"]
    if case == "login":
        script, want = [FakeTurn([], "", status="auth_error", error="login", deltas=part)], LOGIN_NOTICE
    elif case == "rate_limit":
        until = START + timedelta(hours=2)
        script = [FakeTurn([], "", status="rate_limited", retry_at=until, deltas=part)]
        want = rate_limit_notice("15:00")
    elif case == "max_turns":
        script, want = [FakeTurn([], "", status="max_turns", deltas=part)], MAX_TURNS_REPLY
    else:
        script = [FakeTurn([], "", status="error", error="x", deltas=part) for _ in range(4)]
        want = FALLBACK_REPLY
    async with BeEnv.start(tmp_path, start=START, script=script) as env:
        _, raw = await env.chat("안녕")

    chunks = parse_sse(raw)
    deltas = [c["delta"] for c in chunks if c["type"] == "text-delta"]
    assert want in deltas and deltas.count(want) == 1  # 고정 안내는 늘 한 번 나간다


async def test_retry_after_partial_deltas_gets_own_step_and_ids(tmp_path):
    """첫 시도가 글 일부를 보낸 뒤 오류 → 재시도는 새 단계와 새 글 id로 정상 스트림, 글 블록을 다시 보내지 않는다."""
    script = [
        FakeTurn([], "", status="error", error="boom", deltas=["부분 "]),
        FakeTurn([], "전체 답", deltas=["전체 ", "답"]),
    ]
    async with BeEnv.start(tmp_path, start=START, script=script) as env:
        _, raw = await env.chat("안녕", client_msg_id="cm-retry")
        _, replay = await env.chat("안녕", client_msg_id="cm-retry")
        stored = env.conn.execute("SELECT response_json FROM api_idempotency").fetchone()[0]

    chunks = parse_sse(raw)  # 파서가 id 짝, 단계 짝을 본다
    assert types(chunks) == [
        "start", "data-status", "data-status", "start-step",
        "text-start", "text-delta", "text-end", "finish-step",
        "start-step", "text-start", "text-delta", "text-delta", "text-end", "finish-step", "finish",
    ]
    starts = [c["id"] for c in chunks if c["type"] == "text-start"]
    assert len(set(starts)) == 2
    second = [c["delta"] for c in chunks if c["type"] == "text-delta" and c["id"] == starts[1]]
    assert "".join(second) == "전체 답"  # 재시도 글이 온전하고
    assert _text(chunks).count("전체 답") == 1  # 마지막에 다시 붙지 않는다
    # 6: 저장·재생의 글은 스트림에서 본 글 블록 전부
    assert json.loads(stored)["reply_text"] == "부분\n\n전체 답"
    assert _text(parse_sse(replay)) == "부분\n\n전체 답"


async def test_tool_chunk_name_has_no_prefix_and_output_is_utc(tmp_path):
    timed = ("create_event", {"title": "치과", "date": "2026-10-25", "time": "14:00"})
    async with BeEnv.start(tmp_path, start=START, script=[FakeTurn([timed], "넣었어요.")]) as env:
        _, raw = await env.chat("내일 2시 치과")
        brain_ctx = env.brain.calls[0]["run_ctx"]

    tool_in = _one(parse_sse(raw), "tool-input-available")
    tool_out = _one(parse_sse(raw), "tool-output-available")
    assert tool_in["toolName"] == "create_event"
    assert tool_in["input"] == timed[1]
    assert tool_out["toolCallId"] == tool_in["toolCallId"]
    assert tool_out["output"]["updated_at"].endswith("Z") and "+" not in tool_out["output"]["updated_at"]
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



async def test_rerouted_plan_message_keeps_message_id(tmp_path):
    """큐에서 기다리던 계획 메시지의 대화가 `/done`으로 닫혀 다른 대화로 가도, 스트림·`/messages`·재생의 id는 같다."""
    gate = asyncio.Event()
    script = [FakeTurn([], "먼저 온 것", gate=gate), FakeTurn([], "계획을 같이 볼게요.")]
    async with BeEnv.start(tmp_path, start=START, script=script) as env:

        async def send(text, cmid):
            resp = await env.post("/chat", json=env.chat_body(text, client_msg_id=cmid))
            return resp, await resp.read()

        first = asyncio.create_task(send("하나", "cm-first"))
        while not env.brain.calls:
            await asyncio.sleep(0)
        planned = asyncio.create_task(send("/plan 이사 준비", "cm-plan"))
        while env.parts.state.pending_by_client_msg_id("cm-plan") is None:
            await asyncio.sleep(0)
        plan_conv = env.parts.state.pending_by_client_msg_id("cm-plan").conversation_id
        done = await (await env.post("/chat", json=env.chat_body("/done"))).read()  # 바로 답한다: 계획 대화를 닫는다
        gate.set()
        (_, _), (resp, raw) = await asyncio.gather(first, planned)
        await env.drain()
        stored = env.parts.idempotency.get("cm-plan")
        landed = stored.conversation_id
        lines = env.parts.transcripts.messages(landed)
        _, replay = await env.chat("/plan 이사 준비", client_msg_id="cm-plan")

    chunks = parse_sse(raw)
    advertised = chunks[0]["messageId"]
    assert advertised == f"m-{plan_conv}-2"
    assert resp.headers["x-conversation-id"] == str(plan_conv)
    assert landed != plan_conv  # 다른 대화로 갔다
    assert _text(parse_sse(done)) != ""
    secretary = [m for m in lines if m.speaker == "비서"]
    assert secretary[-1].id == advertised  # 옮겨 간 대화(먼저 온 앱 chat)의 마지막 비서 줄
    assert secretary[-1].text == "계획을 같이 볼게요."
    assert parse_sse(replay)[0]["messageId"] == advertised


async def test_conversation_id_matches_across_pending_start_and_header(tmp_path):
    """받을 때 고른 대화: `inbound_pending.conversation_id`, `start`(messageMetadata, messageId), 헤더가 같다(16장)."""
    gate = asyncio.Event()
    async with BeEnv.start(tmp_path, start=START, script=[FakeTurn([], "답", gate=gate)]) as env:
        resp = await env.post("/chat", json=env.chat_body("안녕", client_msg_id="cm-match"))
        first_line = await resp.content.readline()
        row = env.parts.state.pending_by_client_msg_id("cm-match")
        gate.set()
        await resp.read()
        await env.drain()

    import json

    start = json.loads(first_line.decode("utf-8")[len("data: "):])
    assert row.channel == "app" and row.update_id == -1
    assert resp.headers["x-conversation-id"] == str(row.conversation_id)
    assert start["messageMetadata"]["conversation_id"] == row.conversation_id
    assert start["messageId"] == f"m-{row.conversation_id}-1"


async def test_resubmit_from_chat_counts_attempts_and_drops(tmp_path):
    """행은 남았는데 처리 자리가 없으면 다시 넣는다. 넣을 때마다 시도 수를 세고 3회 뒤에는 버린다(SP1 5.2-4)."""
    script = [FakeTurn([], "다시 넣은 답")]
    async with BeEnv.start(tmp_path, start=START, script=script) as env:
        p = env.parts
        conv = p.dispatcher.route_app_message(env.clock.now(), conversation_id=None, checkin_id=None)
        iid = p.state.next_app_inbound_id()
        now = env.clock.now()
        p.state.add_pending_inbound(iid, "남은 글", now, now, channel="app", client_msg_id="cm-left",
                                    conversation_id=conv.id)
        _, raw = await env.chat("남은 글", client_msg_id="cm-left", message_id="msg-left")
        lines = p.transcripts.messages(conv.id)

        iid2 = p.state.next_app_inbound_id()
        p.state.add_pending_inbound(iid2, "끝내 안 된 글", now, now, channel="app", client_msg_id="cm-dead",
                                    conversation_id=conv.id)
        for _ in range(3):
            p.state.bump_inbound_attempts(iid2)
        _, dead = await env.chat("끝내 안 된 글", client_msg_id="cm-dead")
        dropped = p.state.get_pending_inbound(iid2)
        calls = len(env.brain.calls)

    chunks = parse_sse(raw)
    assert chunks[0]["messageId"] == f"m-{conv.id}-1"
    assert _text(chunks) == "다시 넣은 답"
    assert [m.id for m in lines] == ["msg-left", f"m-{conv.id}-1"]
    from my_planner.harness.dispatcher import FALLBACK_REPLY

    assert _text(parse_sse(dead)) == FALLBACK_REPLY
    assert dropped is None and calls == 1


async def test_direct_reply_announces_only_open_app_conversation(tmp_path):
    """명령의 답이 알리는 대화: 앱이 보낸 id가 열린 앱 대화일 때만. 아니면 지금 이어질 앱 대화(없으면 null)."""
    async with BeEnv.start(tmp_path, start=START, script=[FakeTurn([], "안녕하세요.")]) as env:
        _, none_yet = await env.chat("/help", conversation_id=999)
        none_headers = (await env.post("/chat", json=env.chat_body("/help", conversation_id=999))).headers
        resp, _ = await env.chat("안녕")
        app_conv = int(resp.headers["x-conversation-id"])
        telegram_conv = env.parts.convs.open("chat", START.date())
        r_valid, valid = await env.chat("/help", conversation_id=app_conv)
        r_bogus, bogus = await env.chat("/help", conversation_id=telegram_conv.id)

    assert parse_sse(none_yet)[0]["messageMetadata"]["conversation_id"] is None
    assert "x-conversation-id" not in none_headers
    for r, raw in ((r_valid, valid), (r_bogus, bogus)):
        assert parse_sse(raw)[0]["messageMetadata"]["conversation_id"] == app_conv
        assert r.headers["x-conversation-id"] == str(app_conv)
        for name, value in FIVE_HEADERS.items():
            assert r.headers[name] == value


async def test_inflight_unattachable_stream_is_conflict_not_resubmit(tmp_path):
    from fakes import ListSink
    from test_dispatcher_app_channel import app_message

    gate = asyncio.Event()
    async with BeEnv.start(tmp_path, start=START, script=[FakeTurn([], "답", gate=gate)]) as env:
        env.parts.dispatcher.submit_message(app_message(env, "하나", ListSink(), "cm-list"))
        while not env.brain.calls:
            await asyncio.sleep(0)
        resp = await env.post("/chat", json=env.chat_body("하나", client_msg_id="cm-list"))
        body = await resp.json()
        gate.set()
        await env.drain()
        calls = len(env.brain.calls)

    assert resp.status == 409 and body["error"]["code"] == "conflict"
    assert calls == 1


async def test_direct_reply_ignores_idle_client_conversation(tmp_path):
    """명령·글 아닌 답이 알리는 대화도 라우팅과 같은 30분 규칙을 따른다(06 리뷰 N1)."""
    async with BeEnv.start(tmp_path, start=START, script=[FakeTurn([], "꾸민 답")]) as env:
        _, first = await env.chat("꾸민 인사")
        cid = parse_sse(first)[0]["messageMetadata"]["conversation_id"]
        env.clock.advance(timedelta(minutes=29))
        resp_in, fresh = await env.chat("/today", conversation_id=cid)
        env.clock.advance(timedelta(minutes=31))  # 마지막 메시지 뒤 31분(명령은 대화를 잇지 않는다)
        resp_cmd, idle_cmd = await env.chat("/today", conversation_id=cid)
        resp_img, idle_img = await env.chat(conversation_id=cid, parts=[{"type": "file", "url": "x"}])
        count = env.conn.execute("SELECT COUNT(*) FROM conversations").fetchone()[0]

    assert parse_sse(fresh)[0]["messageMetadata"]["conversation_id"] == cid
    assert resp_in.headers["x-conversation-id"] == str(cid)
    for resp, raw in ((resp_cmd, idle_cmd), (resp_img, idle_img)):
        assert parse_sse(raw)[0]["messageMetadata"]["conversation_id"] is None
        assert "x-conversation-id" not in resp.headers
    assert count == 1  # 새 대화를 열지 않는다


# --- SP9 7.3, 7.7: 새 대화, 대화 지우기 ---


async def test_delete_open_conversation_closes_it_first(tmp_path):
    async with BeEnv.start(tmp_path, start=START, script=[FakeTurn([], "네"), FakeTurn([], "새로")]) as env:
        resp, _ = await env.chat("열린 대화")
        a = int(resp.headers["x-conversation-id"])
        assert (await env.delete(f"/conversations/{a}")).status == 204
        c = env.parts.convs.get(a)
        resp, _ = await env.chat("다음 말", conversation_id=a)
        b = int(resp.headers["x-conversation-id"])
        bad = [(await env.delete(p)).status for p in ("/conversations/abc", "/conversations/999")]
    assert c.closed_at is not None and c.deleted_at is not None and b != a
    assert bad == [404, 404]


async def test_new_conversation_endpoint(tmp_path):
    async with BeEnv.start(tmp_path, start=START, script=[FakeTurn([], "네"), FakeTurn([], "새로")]) as env:
        resp, _ = await env.chat("열린 대화")
        a = int(resp.headers["x-conversation-id"])
        first = await env.post("/conversations/new")
        body = await first.json()
        empty = await (await env.post("/conversations/new")).json()
        resp, _ = await env.chat("다음 말", conversation_id=a)
        b = int(resp.headers["x-conversation-id"])
    assert first.status == 200 and body == {"closed": [a]} and empty == {"closed": []}
    assert b != a
