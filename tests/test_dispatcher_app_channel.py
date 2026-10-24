"""두뇌 갈래의 통로 처리 (SP3-4 스펙 7.5 M1~M8): 섞인 큐, 앱 처리 완료, 다시 넣은 앱 행, 도구 묶음.

가짜 두뇌 + 가짜 시계(`BeEnv`)의 디스패처에 `Inbound`를 바로 넣는다. 앱 싱크는 `ListSink`(HTTP 없이).
"""

import asyncio

from be_env import BeEnv
from fakes import FakeTurn, ListSink
from test_dispatcher_messages import kst
from ui_stream import parse_sse

from my_planner.domain import RunContext
from my_planner.harness.dispatcher import Inbound
from my_planner.harness.stream import QueueSink
from my_planner.loop.runner import resubmit_inbound
from my_planner.tools.mcp_adapter import (
    APP_ONLY_TOOLS,
    TOOL_NAMES,
    build_planner_tools,
    tool_names_for,
)

START = kst(2026, 10, 24, 13, 0)
DENTIST = ("add_task", {"title": "치과", "areas": ["health"], "planned_for": "2026-10-25"})


def app_message(env, text, sink, cmid, *, conversation_id=None):
    """`POST /chat`이 하는 것처럼: 받을 때 대화를 고르고, 가린 글을 먼저 저장한 뒤의 `Inbound`."""
    d = env.parts.dispatcher
    now = env.clock.now()
    conv = d.route_app_message(now, conversation_id=conversation_id, checkin_id=None)
    iid = d.state.next_app_inbound_id()
    d.state.add_pending_inbound(iid, text, now, now, channel="app", client_msg_id=cmid, conversation_id=conv.id)
    return Inbound(
        text=text, at=now, sent_at=now, update_ids=[iid], channel="app", client_msg_id=cmid, sink=sink,
        conversation_id=conv.id,
    )


def telegram_message(env, text, update_id):
    now = env.clock.now()
    env.parts.state.add_pending_inbound(update_id, text, now, now)
    return Inbound(text=text, at=now, sent_at=now, update_ids=[update_id])


async def test_mixed_queue_batches_telegram_only(tmp_path):
    gate = asyncio.Event()
    script = [
        FakeTurn([], "앱 첫 답", gate=gate),
        FakeTurn([], "텔레그램 묶음 답"),
        FakeTurn([], "앱 둘 답"),
        FakeTurn([], "앱 셋 답"),
    ]
    async with BeEnv.start(tmp_path, start=START, script=script) as env:
        d = env.parts.dispatcher
        sinks = [ListSink(), ListSink(), ListSink()]
        d.submit_message(app_message(env, "앱 하나", sinks[0], "cm-a0"))
        while not env.brain.calls:
            await asyncio.sleep(0)
        # 처리 중인 호출 뒤에 텔레그램 둘과 앱 둘이 한꺼번에 쌓인다
        d.submit_message(telegram_message(env, "텔레 하나", 501))
        d.submit_message(app_message(env, "앱 둘", sinks[1], "cm-a1"))
        d.submit_message(telegram_message(env, "텔레 둘", 502))
        d.submit_message(app_message(env, "앱 셋", sinks[2], "cm-a2"))
        gate.set()
        await env.drain()
        calls = env.brain.calls
        convs = {r["id"]: r["channel"] for r in env.conn.execute("SELECT id, channel FROM conversations")}
        sent = [o.text for o in env.sender.sent]

    assert len(calls) == 4  # 처리 중이던 것 + 텔레그램 묶음 1 + 앱 2
    assert "텔레 하나" in calls[1]["prompt"] and "텔레 둘" in calls[1]["prompt"]
    assert all("텔레" not in c["prompt"] for c in (calls[2], calls[3]))
    assert sent == ["텔레그램 묶음 답"]  # 텔레그램 가짜 봇에는 묶음의 답 하나
    assert [s.text for s in sinks] == ["앱 첫 답", "앱 둘 답", "앱 셋 답"]
    assert all(s.closed and s.types[-1] == "finish" for s in sinks)
    channels = [convs[c["run_ctx"].conversation_id] for c in calls]
    assert channels == ["app", "telegram", "app", "app"]  # 대화가 섞이지 않는다
    assert [c["run_ctx"].channel for c in calls] == ["app", "telegram", "app", "app"]


async def test_app_done_writes_no_telegram_updates(tmp_path):
    async with BeEnv.start(tmp_path, start=START, script=[FakeTurn([DENTIST], "넣었어요.")]) as env:
        sink = ListSink()
        env.parts.dispatcher.submit_message(app_message(env, "내일 치과", sink, "cm-done"))
        await env.drain()
        updates = [r[0] for r in env.conn.execute("SELECT update_id FROM telegram_updates")]
        pending = env.conn.execute("SELECT COUNT(*) FROM inbound_pending").fetchone()[0]
        stored = env.parts.idempotency.get("cm-done")

    assert updates == []  # 음수 id를 telegram_updates에 넣지 않는다(M5)
    assert pending == 0
    assert stored.endpoint == "chat" and stored.status_code == 200
    assert stored.body == {
        "conversation_id": stored.conversation_id, "reply_text": "넣었어요.", "confirmation": "✓ 추가: 치과 → 내일",
        "inbound_id": -1, "message_id": f"m-{stored.conversation_id}-1",
    }
    assert sink.text == "넣었어요."


async def test_recovered_app_row_replies_nowhere(tmp_path):
    async with BeEnv.start(tmp_path, start=START, script=[FakeTurn([DENTIST], "넣었어요.")]) as env:
        p = env.parts
        app_message(env, "내일 치과", None, "cm-restart")  # 받아 저장한 뒤 BE가 멈췄다(디스패처에 넣지 않음)
        assert resubmit_inbound(p.state, p.dispatcher) == 1
        await env.drain()
        stored = p.idempotency.get("cm-restart")
        lines = p.transcripts.messages(stored.conversation_id)
        pending = env.conn.execute("SELECT COUNT(*) FROM inbound_pending").fetchone()[0]
        titles = [r["title"] for r in env.conn.execute("SELECT title FROM tasks")]

    assert env.sender.sent == []  # 텔레그램으로 보내지 않는다(M6)
    assert stored.body["reply_text"] == "넣었어요."
    assert [(m.speaker, m.channel, m.text) for m in lines] == [
        ("사용자", "app", "내일 치과"), ("비서", "app", "넣었어요.\n\n✓ 추가: 치과 → 내일"),
    ]
    assert lines[1].id == f"m-{stored.conversation_id}-1"
    assert lines[0].id == f"u-{stored.conversation_id}-1"
    assert pending == 0 and titles == ["치과"]


async def test_recovered_app_row_accepts_new_stream(tmp_path):
    """시작 때 다시 넣어 싱크 없이 처리 중인 행에 같은 `client_msg_id`의 새 요청이 붙는다(M8)."""
    gate = asyncio.Event()
    async with BeEnv.start(tmp_path, start=START, script=[FakeTurn([DENTIST], "넣었어요.", gate=gate)]) as env:
        p = env.parts
        app_message(env, "내일 치과", None, "cm-late")
        resubmit_inbound(p.state, p.dispatcher)
        while not env.brain.calls:
            await asyncio.sleep(0)
        sink = QueueSink()
        q = sink.attach()
        assert p.dispatcher.attach_stream("cm-late", sink)
        assert not p.dispatcher.attach_stream("cm-unknown", QueueSink())
        gate.set()
        await env.drain()
        body = b""
        while (item := q.get_nowait()) is not None:
            body += item

    chunks = parse_sse(body)
    assert chunks[0]["messageId"] == f"m-{chunks[0]['messageMetadata']['conversation_id']}-1"
    assert [c["type"] for c in chunks][:3] == ["start", "data-status", "start-step"]
    assert chunks[1]["data"] == {"state": "thinking"}  # 두뇌가 이미 시작한 뒤에 붙었다
    assert "".join(c["delta"] for c in chunks if c["type"] == "text-delta") == "넣었어요."


def test_app_tool_set_is_channel_specific():
    assert tool_names_for("telegram") == TOOL_NAMES
    assert tool_names_for("app") == TOOL_NAMES + APP_ONLY_TOOLS
    # 화면 도구와 카드 도구는 텔레그램 대화에 주지 않는다(10장, 티켓 09)
    banned = {"pin_card", "unpin_card", "reorder_cards"}
    assert not [n for n in tool_names_for("telegram") if n.startswith("ui_") or n in banned]

    class _Tools:
        def __getattr__(self, name):
            return lambda ctx, **kw: {"ok": True}

    for channel in ("telegram", "app"):
        ctx = RunContext(conversation_id=None, run_id=None, channel=channel)
        assert [t.name for t in build_planner_tools(_Tools(), ctx)] == tool_names_for(channel)


async def test_reply_without_app_sender_is_not_fallback(tmp_path):
    """`app_sender` 없이 만든 디스패처도 앱 답을 쓰개에 쓴다. 끝난 답을 일반 문구로 덮지 않는다."""
    async with BeEnv.start(tmp_path, start=START, script=[FakeTurn([], "진짜 답")]) as env:
        env.parts.dispatcher.app_sender = None
        sink = ListSink()
        env.parts.dispatcher.submit_message(app_message(env, "안녕", sink, "cm-nosender"))
        await env.drain()

    assert sink.text == "진짜 답"
    assert sink.closed and sink.types.count("finish") == 1
