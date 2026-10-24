"""앱 전용 화면 도구 `ui_todo_list`, `ui_choice`, `ui_summary_card`와 하네스 `h_` 조각 (SP3-4 스펙 6.4.1, 6.4.7, 10장).

내용은 모두 꾸며 낸 것이다.
"""

import hashlib
import json
from datetime import date

import pytest
from be_env import BeEnv
from fakes import FakeTurn
from test_dispatcher_messages import kst
from test_tools_tasks import ToolEnv
from ui_stream import parse_sse

from my_planner.domain import RunContext
from my_planner.harness.dispatcher import Outbound
from my_planner.harness.stream import AppReplySender, UiMessageWriter
from my_planner.store.repos.cards import CardsRepo
from my_planner.store.views import todo_ref
from my_planner.timefmt import to_api_times
from my_planner.tools.mcp_adapter import (
    APP_ONLY_TOOLS,
    TOOL_NAMES,
    build_planner_tools,
    call_tool,
    tool_names_for,
)

START = kst(2026, 10, 24, 13, 0)  # 토요일 낮: 예정된 회차가 없다
CHOICES = [{"id": f"o{i}", "label": f"보기 {i}"} for i in range(1, 6)]


class ListSink:
    def __init__(self):
        self.chunks = []
        self.closed = False
        self.disconnected = False

    def emit(self, chunk):
        self.chunks.append(chunk)

    def ping(self):
        pass

    def close(self):
        self.closed = True


def _db_hash(conn):
    return hashlib.sha256("\n".join(conn.iterdump()).encode("utf-8")).hexdigest()


def _files(root):
    if not root.exists():
        return {}
    return {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob("*")) if p.is_file()
    }


@pytest.fixture
def uenv(tmp_path, conn):
    env = ToolEnv(tmp_path, conn)
    env.tools.cards = CardsRepo(conn, env.clock)
    return env


def _app_ctx(stream=None):
    return RunContext(conversation_id=1, run_id=None, events=[], channel="app", stream=stream)


def test_ui_tools_do_not_touch_db_or_files(uenv, tmp_path):
    t = uenv.tools.add_task(_app_ctx(), title="꾸민 할 일", areas=["learning"])
    db_before, files_before = _db_hash(uenv.conn), _files(tmp_path / "data")
    ctx = _app_ctx(stream=UiMessageWriter(ListSink(), "m-1-1"))

    outs = [
        uenv.tools.ui_todo_list(ctx, title="이번 주", task_ids=[t["id"]]),
        uenv.tools.ui_choice(ctx, question="어느 쪽?", options=CHOICES[:2]),
        uenv.tools.ui_summary_card(ctx, title="요약", lines=["한 줄", "두 줄"]),
        uenv.tools.ui_choice(ctx, question="어느 쪽?", options=CHOICES),  # 스키마 오류
        uenv.tools.ui_summary_card(ctx, title="요약", lines=["x" * 121]),
        uenv.tools.ui_todo_list(ctx, title="", task_ids=[]),
    ]
    for name, args in [
        ("ui_todo_list", {"title": "이번 주", "task_ids": [t["id"]]}),
        ("ui_choice", {"question": "어느 쪽?", "options": CHOICES[:3]}),
        ("ui_summary_card", {"title": "요약", "lines": ["한 줄"]}),
    ]:
        call_tool(uenv.tools, ctx, name, args)

    assert outs[:3] == [{"ok": True}] * 3
    assert all("error" in o for o in outs[3:])
    assert _db_hash(uenv.conn) == db_before
    assert _files(tmp_path / "data") == files_before
    assert ctx.events == [] and ctx.activity_ids == [] and ctx.undo_ids == []


async def test_ui_schema_error_is_tool_error_and_no_component_chunk(uenv):
    sink = ListSink()
    ctx = _app_ctx(stream=UiMessageWriter(sink, "m-1-1"))
    handlers = {t.name: t.handler for t in build_planner_tools(uenv.tools, ctx)}

    out = await handlers["ui_choice"]({"question": "어느 쪽?", "options": CHOICES})
    assert out["is_error"] is True
    assert "options" in json.loads(out["content"][0]["text"])["error"]
    assert sink.chunks == []  # 입력 조각도 오류 조각도 없다(6.4.7)

    ok = await handlers["ui_choice"]({"question": "어느 쪽?", "options": CHOICES[:4]})
    assert ok["is_error"] is False
    assert [c["type"] for c in sink.chunks] == ["tool-input-available", "tool-output-available"]
    assert sink.chunks[0]["toolName"] == "ui_choice"
    assert sink.chunks[1]["output"] == {"ok": True}


def test_ui_todo_list_stream_output_has_current_todos(uenv):
    """두뇌가 받는 결과는 `{"ok": true}`, 스트림 출력은 `data.todos`(props 순서, 초안·소프트 삭제 뺌, 6.4.1)."""
    tools = uenv.tools
    a = tools.add_task(_app_ctx(), title="꾸민 하나", areas=["health", "career"])["id"]
    b = tools.add_task(_app_ctx(), title="꾸민 둘", areas=["learning"])["id"]
    d = tools.propose_tasks(_app_ctx(), tasks=[{"title": "꾸민 초안", "areas": ["health"]}])["proposed"][0]["id"]
    gone = tools.add_task(_app_ctx(), title="꾸민 삭제", areas=["health"])["id"]
    tools.tasks.restore(gone, status=tools.tasks.get(gone).status, completed_at=None, deleted_at=uenv.clock.now())
    tools.complete_task(_app_ctx(), id=b)
    sink = ListSink()
    ctx = _app_ctx(stream=UiMessageWriter(sink, "m-1-1"))

    result = call_tool(tools, ctx, "ui_todo_list", {"title": "목록", "task_ids": [b, d, gone, a]})

    assert result == {"ok": True}
    assert sink.chunks[0]["input"] == {"title": "목록", "task_ids": [b, d, gone, a]}
    assert sink.chunks[1]["output"] == {"ok": True, "data": {"todos": [
        {"id": b, "title": "꾸민 둘", "cadence": None, "area": "learning", "status": "done", "planned_for": None, "scheduled_at": None},
        {"id": a, "title": "꾸민 하나", "cadence": None, "area": "career", "status": "open", "planned_for": None, "scheduled_at": None},
    ]}}


def test_ui_and_card_tools_absent_from_telegram(uenv):
    assert APP_ONLY_TOOLS == [
        "ui_todo_list", "ui_choice", "ui_summary_card", "pin_card", "unpin_card", "reorder_cards",
    ]
    assert tool_names_for("telegram") == TOOL_NAMES
    assert tool_names_for("app") == TOOL_NAMES + APP_ONLY_TOOLS
    for channel in ("telegram", "app"):
        ctx = RunContext(conversation_id=None, run_id=None, channel=channel)
        names = [t.name for t in build_planner_tools(uenv.tools, ctx)]
        assert names == tool_names_for(channel)
    tg = {t.name for t in build_planner_tools(uenv.tools, RunContext(conversation_id=None, run_id=None))}
    assert not tg & set(APP_ONLY_TOOLS)


def test_app_prompt_includes_channel_app_only_for_app(tmp_path):
    from my_planner.harness import prompts
    from my_planner.harness.brain import ClaudeBrain

    part = prompts.load("channel_app.md")
    assert part and "pin_card" in part and "ui_" in part
    brain = ClaudeBrain(lambda: None, tmp_path / "wd", max_turns=10)
    assert part not in brain.system_prompt_for("telegram")
    assert brain.system_prompt_for("app") == f"{prompts.load('system.md')}\n\n{part}"


async def test_harness_chunks_have_h_prefix(tmp_path):
    propose = ("propose_tasks", {"tasks": [{"title": "꾸민 산책", "areas": ["health"]},
                                           {"title": "꾸민 독서", "areas": ["learning"]}]})
    async with BeEnv.start(tmp_path, start=START, script=[FakeTurn([propose], "두 가지 제안해 볼게요.")]) as env:
        _, raw = await env.chat("이번 주 뭐 하면 좋을까")
    chunks = parse_sse(raw)

    harness = [c for c in chunks if str(c.get("toolCallId", "")).startswith("h_")]
    assert [(c["type"], c["toolCallId"]) for c in harness] == [
        ("tool-input-available", "h_draft_1"), ("tool-output-available", "h_draft_1"),
    ]
    assert harness[0]["toolName"] == "ui_todo_draft" and harness[0]["input"] == {"task_ids": [1, 2]}
    assert harness[1]["output"] == {"ok": True, "data": {"todos": [
        {"id": 1, "title": "꾸민 산책", "cadence": None, "area": "health", "status": "draft", "planned_for": None, "scheduled_at": None},
        {"id": 2, "title": "꾸민 독서", "cadence": None, "area": "learning", "status": "draft", "planned_for": None, "scheduled_at": None},
    ]}}
    # 두뇌 도구 조각은 `tc_`, 순서는 두뇌 글·도구 → 하네스 조각 → data-activity → finish(6.4.1)
    kinds = [c["type"] for c in chunks]
    assert all(c["toolCallId"].startswith("tc_") for c in chunks if "toolCallId" in c and c not in harness)
    assert kinds.index("text-end") < chunks.index(harness[0])
    assert chunks.index(harness[1]) < kinds.index("finish-step") < kinds.index("data-activity")


async def test_app_reply_sender_numbers_harness_chunks_in_reply():
    sink = ListSink()
    w = UiMessageWriter(sink, "m-1-1")
    refs = [{"id": 7, "title": "꾸민", "cadence": None, "area": "health", "status": "draft", "planned_for": None, "scheduled_at": None}]
    out = Outbound(text="답", draft_task_ids=[7], ask_condition_for=date(2026, 10, 24), channel="app",
                   writer=w, draft_todos=refs)
    await AppReplySender().send(out)

    tools = [(c["type"], c["toolCallId"]) for c in sink.chunks if "toolCallId" in c]
    assert tools == [
        ("tool-input-available", "h_draft_1"), ("tool-output-available", "h_draft_1"),
        ("tool-input-available", "h_cond_2"), ("tool-output-available", "h_cond_2"),
    ]
    by_id = {(c["type"], c["toolCallId"]): c for c in sink.chunks if "toolCallId" in c}
    assert by_id[("tool-input-available", "h_cond_2")]["toolName"] == "ui_condition_picker"
    assert by_id[("tool-input-available", "h_cond_2")]["input"] == {"date": "2026-10-24"}
    assert by_id[("tool-output-available", "h_cond_2")]["output"] == {"ok": True}
    assert by_id[("tool-output-available", "h_draft_1")]["output"] == {"ok": True, "data": {"todos": refs}}


async def test_todo_ref_has_dates_in_utc(tmp_path):
    """`TodoRef`의 `planned_for`(논리적 날짜)와 `scheduled_at`: 현지 시각으로 만들고 API·스트림 경계가 UTC로 바꾼다(SP6 10.2)."""
    async with BeEnv.start(tmp_path, start=START) as env:
        tools = env.parts.tools
        ctx = _app_ctx()
        a = tools.add_task(ctx, title="꾸민 치과", areas=["health"], planned_for="2026-10-25",
                           scheduled_at="2026-10-25T14:00")["id"]
        b = tools.add_task(ctx, title="꾸민 날짜 없음", areas=["learning"])["id"]
        tools.pin_card(ctx, component="ui_todo_list", props={"title": "꾸민 목록", "task_ids": [a, b]})
        ref = todo_ref(tools.tasks.get(a), tools.tasks, tools.today())
        today = await (await env.get("/today")).json()

    assert ref["scheduled_at"] == "2026-10-25T05:00:00+00:00"  # `todo_dict`처럼 오프셋 붙은 ISO, 경계에서 `Z`
    assert to_api_times(ref) == {
        "id": a, "title": "꾸민 치과", "cadence": None, "area": "health", "status": "open",
        "planned_for": "2026-10-25", "scheduled_at": "2026-10-25T05:00:00Z",
    }
    assert today["cards"][0]["data"]["todos"] == [
        to_api_times(ref),
        {"id": b, "title": "꾸민 날짜 없음", "cadence": None, "area": "learning", "status": "open",
         "planned_for": None, "scheduled_at": None},
    ]
