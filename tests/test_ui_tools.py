"""앱 전용 화면 도구 `ui_todo_list`, `ui_choice`, `ui_summary_card`와 하네스 `h_` 조각 (SP3-4 스펙 6.4.1, 6.4.7, 10장),
SP6의 `ui_date_choice`, `ui_result`, `ui_period_list`, `ui_block`(뜻 검사, 지금 값, 한 답 두 개 상한, SP6 스펙 6장, 10장).

내용은 모두 꾸며 낸 것이다.
"""

import hashlib
import json
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from be_env import BeEnv
from fakes import FakeTurn
from test_dispatcher_messages import kst
from test_tools_tasks import ToolEnv
from ui_stream import parse_sse

from my_planner.domain import RunContext
from my_planner.harness.dispatcher import Outbound
from my_planner.harness.stream import AppReplySender, UiMessageWriter
from my_planner.store.repos.activity import ActivityRepo
from my_planner.store.repos.cards import CardsRepo
from my_planner.store.repos.habits import HabitsRepo
from my_planner.store.views import todo_ref
from my_planner.timefmt import to_api_times
from my_planner.tools.core import Tools
from my_planner.tools.mcp_adapter import (
    APP_ONLY_TOOLS,
    TOOL_NAMES,
    build_planner_tools,
    call_tool,
    tool_names_for,
)
from my_planner.tools.ui import (
    BRAIN_COMPONENTS,
    PINNABLE_COMPONENTS,
    UI_CATALOG_VERSION,
    UI_COMPONENTS,
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
    env.tools.activity = ActivityRepo(conn, env.clock)  # `ui_result`·`ui_period_list`의 "이번 답에서 바뀐 것"
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
    assert APP_ONLY_TOOLS == [  # 카탈로그의 두뇌 조각 순서(SP6 G-BE2) + 카드 도구 셋 + SP9(`ui_events`는 맨 끝)
        "ui_todo_list", "ui_choice", "ui_summary_card", "ui_date_choice", "ui_result", "ui_period_list", "ui_block",
        "ui_habit_check", "pin_card", "unpin_card", "reorder_cards",
        "set_checkin_time", "search_memos", "read_memo", "create_memo", "find_conversations",
        "list_events", "create_event", "update_event", "delete_event", "ui_events",
        "propose_measures",  # SP13-05
    ]
    assert tool_names_for(RunContext(None, None, channel="telegram")) == TOOL_NAMES
    assert tool_names_for(RunContext(None, None, channel="app")) == TOOL_NAMES + APP_ONLY_TOOLS
    for channel in ("telegram", "app"):
        ctx = RunContext(conversation_id=None, run_id=None, channel=channel)
        names = [t.name for t in build_planner_tools(uenv.tools, ctx)]
        assert names == tool_names_for(RunContext(None, None, channel=channel))
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
        a = tools.tasks.create("꾸민 치과", ["health"], planned_for=date(2026, 10, 25),
                               scheduled_at=kst(2026, 10, 25, 14, 0)).id  # SP9 전 시각 있는 할 일(도구로는 못 만든다)
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


async def test_harness_card_times_are_utc():
    """하네스 초안 카드의 `data.todos[].scheduled_at`도 스트림에서 UTC `Z`다(6.1)."""
    sink = ListSink()
    refs = [{"id": 7, "title": "꾸민", "cadence": None, "area": "health", "status": "draft",
             "planned_for": "2026-10-25", "scheduled_at": "2026-10-25T14:00:00+09:00"}]
    out = Outbound(text="답", draft_task_ids=[7], channel="app", writer=UiMessageWriter(sink, "m-1-1"),
                   draft_todos=refs)
    await AppReplySender().send(out)

    (output,) = [c["output"] for c in sink.chunks if c["type"] == "tool-output-available"]
    assert output["data"]["todos"][0]["scheduled_at"] == "2026-10-25T05:00:00Z"
    assert output["data"]["todos"][0]["planned_for"] == "2026-10-25"


# --- SP7-06: ui_habit_check ---


def test_catalog_has_ui_habit_check_brain_origin():
    assert UI_COMPONENTS["ui_habit_check"]["origin"] == "brain"
    assert "ui_habit_check" in BRAIN_COMPONENTS
    assert "ui_habit_check" not in PINNABLE_COMPONENTS
    assert UI_CATALOG_VERSION == "2026-11-01.3"
    schema = UI_COMPONENTS["ui_habit_check"]["schema"]
    assert schema["required"] == ["date"] and schema["additionalProperties"] is False


def test_ui_habit_check_validates_date(uenv):
    ctx = _app_ctx()
    assert uenv.tools.ui_habit_check(ctx, date="2026-10-24") == {"ok": True}
    assert uenv.tools.ui_habit_check(ctx) == {"ok": True}  # 기본은 오늘
    for bad in ("24/10/2026", "2026-10-4", 20261024, "2026-13-45"):
        assert "error" in uenv.tools.ui_habit_check(ctx, date=bad), bad
    assert "error" in uenv.tools.ui_habit_check(ctx, date="2026-10-24", habit_ids=[1])


def test_ui_habit_check_no_db_writes(uenv, tmp_path):
    habits = HabitsRepo(uenv.conn, uenv.clock)
    habits.add("꾸민 운동", "health", "daily", None, uenv.clock.now())
    uenv.tools.habits = habits
    db_before, files_before = _db_hash(uenv.conn), _files(tmp_path / "data")
    ctx = _app_ctx(stream=UiMessageWriter(ListSink(), "m-1-1"))
    uenv.tools.ui_habit_check(ctx, date="2026-10-24")
    uenv.tools.ui_habit_check(ctx, date="bad")
    call_tool(uenv.tools, ctx, "ui_habit_check", {"date": "2026-10-24"})
    assert _db_hash(uenv.conn) == db_before and _files(tmp_path / "data") == files_before
    assert ctx.events == [] and ctx.activity_ids == [] and ctx.undo_ids == []


def test_app_tool_count_50():
    assert len(tool_names_for(RunContext(None, None, channel="app"))) == 50 and len(tool_names_for(RunContext(None, None, channel="telegram"))) == 28  # SP6 G-BE2 +4, SP9-02 +1, SP9-03 +3, SP9-05 +5, SP9-09 +1, SP13-05 +1(앱에만)
    assert "ui_habit_check" in APP_ONLY_TOOLS and "ui_habit_check" not in tool_names_for(RunContext(None, None, channel="telegram"))
    names = [t.name for t in build_planner_tools(Tools.__new__(Tools), RunContext(conversation_id=None, run_id=None, channel="app"))]
    assert "ui_habit_check" in names  # 도구 정의(설명, 스키마)가 있다


def test_chat_stream_habit_part_has_data_habits(uenv):
    habits = HabitsRepo(uenv.conn, uenv.clock)
    run = habits.add("꾸민 운동", "health", "daily", None, uenv.clock.now())
    habits.add("꾸민 독서", "learning", "weekly", 3, uenv.clock.now())
    paused = habits.add("쉬는 것", "health", "daily", None, uenv.clock.now())
    habits.set_status(paused.id, "paused", uenv.clock.now())
    habits.check(run.id, date(2026, 10, 24), uenv.clock.now())
    uenv.tools.habits = habits
    sink = ListSink()
    ctx = _app_ctx(stream=UiMessageWriter(sink, "m-1-1"))
    call_tool(uenv.tools, ctx, "ui_habit_check", {"date": "2026-10-24"})
    call_tool(uenv.tools, ctx, "ui_habit_check", {})  # 날짜를 빼면 오늘로 채운다
    kinds = [c["type"] for c in sink.chunks]
    assert kinds[:2] == ["tool-input-available", "tool-output-available"]
    out = sink.chunks[1]["output"]
    assert out["ok"] is True
    assert [(h["title"], h["checked"], h["week_count"], h["status"]) for h in out["data"]["habits"]] == [
        ("꾸민 운동", True, 1, "active"), ("꾸민 독서", False, 0, "active"),
    ]
    assert sink.chunks[2]["input"] == {"date": "2026-10-24"}


def test_pin_card_rejects_ui_habit_check(uenv):
    ctx = _app_ctx()
    res = uenv.tools.pin_card(ctx, component="ui_habit_check", props={"date": "2026-10-24"})
    assert "error" in res
    assert uenv.tools.cards.active() == []


# --- SP6 G-BE2: 두뇌에게 주는 새 화면 도구 넷 (스펙 6.2~6.4, 7장, 9.3, 10.2, 10.4, 부록 B) ---

TODAY = date(2026, 10, 24)  # ToolEnv의 논리적 날짜(토)
NEW_TOOLS = ("ui_date_choice", "ui_result", "ui_period_list", "ui_block")
SCHEDULED_ERR = "시각이 잡힌 할 일은 날짜 고르기로 옮기지 않아요. 대화로 정해 주세요."
NOT_OPEN_ERR = "시각이 없는 열린 할 일만 날짜를 고를 수 있어요."
RANGE_ERR = "후보 날짜는 오늘부터 90일 안이에요."
UNCHANGED_ERR = "이번 답에서 바꾼 할 일만 보여 줄 수 있어요."
HIGHLIGHT_ERR = "바뀐 줄 표시는 이번 답에서 바꾼 할 일만 할 수 있어요."
ALL_GONE_ERR = "보여 줄 바뀐 할 일이 없어요."
PERIOD_ERR = "하루는 2주 전부터 8주 뒤까지, 주는 2주 전부터 8주 뒤까지 보여 줄 수 있어요."
CAP_ERR = "한 답에 화면 조각은 2개까지예요."
BLOCK = {"title": "꾸민 카드", "children": [{"type": "text", "md": "**꾸민** 글"}]}


def _d(days):
    return (TODAY + timedelta(days=days)).isoformat()


def _cands(*days):
    return [{"date": _d(n)} for n in days]


def _add(tools, title="꾸민 할 일", **kw):
    if "scheduled_at" in kw:  # SP9 전 시각 있는 할 일(도구로는 못 만든다, SP9 5.4): 저장소로 바로 만든다
        pf, at = kw.pop("planned_for", None), kw.pop("scheduled_at")
        assert not kw
        return tools.tasks.create(title, ["health"], planned_for=date.fromisoformat(pf) if pf else None,
                                  scheduled_at=datetime.fromisoformat(at).replace(tzinfo=ZoneInfo("Asia/Seoul"))).id
    return tools.add_task(_app_ctx(), title=title, areas=["health"], **kw)["id"]


def _soft_delete(env, tid):
    t = env.tools.tasks.get(tid)
    env.tools.tasks.restore(tid, status=t.status, completed_at=t.completed_at, deleted_at=env.clock.now())


def test_new_ui_tools_do_not_touch_db_files_or_events(uenv, tmp_path):
    tools = uenv.tools
    a, b = _add(tools, "꾸민 하나"), _add(tools, "꾸민 둘", planned_for="2026-10-26")
    changed = _app_ctx()
    tools.move_task(changed, id=b, planned_for="2026-10-27")  # 이번 답에서 바꾼 것(그리기 전에)
    events, acts = list(changed.events), list(changed.activity_ids)
    db_before, files_before = _db_hash(uenv.conn), _files(tmp_path / "data")
    fresh = _app_ctx(stream=UiMessageWriter(ListSink(), "m-1-1"))
    changed.stream = UiMessageWriter(ListSink(), "m-1-2")

    outs = [
        tools.ui_date_choice(fresh, task_id=a, question="언제 할까요?", candidates=_cands(1, 2)),
        tools.ui_period_list(fresh, week="2026-W44"),
        tools.ui_block(fresh, **BLOCK),
        tools.ui_result(changed, task_ids=[b]),
        tools.ui_period_list(changed, week="2026-W44", highlight_task_ids=[b]),
        tools.ui_date_choice(fresh, task_id=a, question="언제 할까요?", candidates=_cands(-1, 2)),  # 뜻 검사 오류
        tools.ui_result(fresh, task_ids=[b]),
        tools.ui_block(fresh, title="꾸민", children=[{"type": "divider"}]),
    ]
    call_tool(tools, fresh, "ui_date_choice", {"task_id": a, "question": "언제?", "candidates": _cands(0, 1)})
    call_tool(tools, fresh, "ui_block", BLOCK)
    call_tool(tools, changed, "ui_result", {"task_ids": [b]})
    call_tool(tools, changed, "ui_period_list", {"week": "2026-W44", "highlight_task_ids": [b]})

    assert outs[:5] == [{"ok": True}] * 5
    assert all("error" in o for o in outs[5:])
    assert _db_hash(uenv.conn) == db_before
    assert _files(tmp_path / "data") == files_before
    assert fresh.events == [] and fresh.activity_ids == [] and fresh.undo_ids == []
    assert changed.events == events and changed.activity_ids == acts


def test_date_choice_rejects_scheduled_task(uenv):
    tid = _add(uenv.tools, planned_for="2026-10-25", scheduled_at="2026-10-25T14:00")
    out = uenv.tools.ui_date_choice(_app_ctx(), task_id=tid, question="언제?", candidates=_cands(1, 2))
    assert out == {"error": SCHEDULED_ERR}


def test_date_choice_rejects_not_open(uenv):
    tools = uenv.tools
    done, dropped, gone = _add(tools, "꾸민 끝"), _add(tools, "꾸민 뺌"), _add(tools, "꾸민 지움")
    tools.complete_task(_app_ctx(), id=done)
    tools.drop_task(_app_ctx(), id=dropped)
    _soft_delete(uenv, gone)
    draft = tools.propose_tasks(_app_ctx(), tasks=[{"title": "꾸민 초안", "areas": ["health"]}])["proposed"][0]["id"]
    dated = _add(tools, "꾸민 날짜 있음", planned_for="2026-10-30")  # 날짜는 있어도 된다

    for tid in (done, dropped, gone, draft, 999):
        out = tools.ui_date_choice(_app_ctx(), task_id=tid, question="언제?", candidates=_cands(1, 2))
        assert out == {"error": NOT_OPEN_ERR}, tid
    assert tools.ui_date_choice(_app_ctx(), task_id=dated, question="언제?", candidates=_cands(1, 2)) == {"ok": True}


@pytest.mark.parametrize(("days", "ok"), [
    ((-1, 2), False), ((1, 91), False), ((0, 90), True), ((0, 1, 2, 90), True),
])
def test_date_choice_candidate_range(uenv, days, ok):
    tid = _add(uenv.tools)
    out = uenv.tools.ui_date_choice(_app_ctx(), task_id=tid, question="언제?", candidates=_cands(*days))
    assert out == ({"ok": True} if ok else {"error": RANGE_ERR})


def test_date_choice_bad_calendar_date_is_tool_error(uenv):
    """스키마는 `YYYY-MM-DD` 모양만 본다. 달력에 없는 날은 뜻 검사가 값 없이 거절한다."""
    tid = _add(uenv.tools)
    cands = [{"date": "2026-13-45"}, {"date": _d(1)}]
    out = uenv.tools.ui_date_choice(_app_ctx(), task_id=tid, question="언제?", candidates=cands)
    assert out == {"error": "화면 조각 형식이 맞지 않아요: candidates.0.date: date_invalid"}


def test_result_rejects_unchanged_task(uenv):
    tools = uenv.tools
    a, b = _add(tools, "꾸민 하나"), _add(tools, "꾸민 둘")
    ctx = _app_ctx()
    tools.complete_task(ctx, id=a)
    tools.list_tasks(ctx)  # 읽기는 바꾼 것이 아니다

    assert tools.ui_result(ctx, task_ids=[b]) == {"error": UNCHANGED_ERR}
    assert tools.ui_result(ctx, task_ids=[a, b]) == {"error": UNCHANGED_ERR}
    assert tools.ui_result(_app_ctx(), task_ids=[a]) == {"error": UNCHANGED_ERR}  # 다른 답에서 바꾼 것
    assert tools.ui_result(ctx, task_ids=[a]) == {"ok": True}


def test_result_all_deleted_is_error(uenv):
    tools = uenv.tools
    ctx = _app_ctx()
    a = tools.add_task(ctx, title="꾸민 하나", areas=["health"])["id"]
    b = tools.add_task(ctx, title="꾸민 둘", areas=["health"])["id"]
    _soft_delete(uenv, a)  # 같은 답에서 추가를 되돌린 것처럼

    assert tools.ui_result(ctx, task_ids=[a, b]) == {"ok": True}
    assert [i["todo"]["id"] for i in tools.ui_result_items(ctx, [a, b])] == [b]
    _soft_delete(uenv, b)
    assert tools.ui_result(ctx, task_ids=[a, b]) == {"error": ALL_GONE_ERR}
    assert tools.ui_result(ctx, task_ids=[a]) == {"error": ALL_GONE_ERR}


def test_period_highlight_must_be_changed(uenv):
    tools = uenv.tools
    a, b = _add(tools, "꾸민 하나", planned_for="2026-10-26"), _add(tools, "꾸민 둘", planned_for="2026-10-27")
    ctx = _app_ctx()
    tools.move_task(ctx, id=a, planned_for="2026-10-28")

    assert tools.ui_period_list(ctx, week="2026-W44", highlight_task_ids=[b]) == {"error": HIGHLIGHT_ERR}
    assert tools.ui_period_list(ctx, week="2026-W44", highlight_task_ids=[a, b]) == {"error": HIGHLIGHT_ERR}
    assert tools.ui_period_list(ctx, week="2026-W44", highlight_task_ids=[a]) == {"ok": True}
    assert tools.ui_period_list(ctx, week="2026-W44") == {"ok": True}  # 보기만 하는 요청


@pytest.mark.parametrize(("props", "ok"), [
    ({"day": _d(-15)}, False), ({"day": _d(-14)}, True), ({"day": _d(56)}, True), ({"day": _d(57)}, False),
    ({"week": "2026-W40"}, False), ({"week": "2026-W41"}, True), ({"week": "2026-W51"}, True),
    ({"week": "2026-W52"}, False),
])
def test_period_range(uenv, props, ok):
    out = uenv.tools.ui_period_list(_app_ctx(), **props)
    assert out == ({"ok": True} if ok else {"error": PERIOD_ERR})


@pytest.mark.parametrize("props", [{"day": "2026-02-30"}, {"week": "2026-W60"}])
def test_period_bad_calendar_value_is_tool_error(uenv, props):
    out = uenv.tools.ui_period_list(_app_ctx(), **props)
    (key,) = props
    assert out == {"error": f"화면 조각 형식이 맞지 않아요: {key}: date_invalid"}


async def test_reply_cap_two(tmp_path):
    """두뇌 화면 조각은 한 답에 둘까지(10.4). 셋째는 도구 오류이고 조각이 없다. 스키마에 걸린 호출, 하네스 조각
    (`h_draft_*`), `pin_card`는 세지 않는다."""
    card = {"title": "꾸민 요약", "lines": ["한 줄"]}
    calls = [
        ("propose_tasks", {"tasks": [{"title": "꾸민 초안", "areas": ["health"]}]}),
        ("pin_card", {"component": "ui_summary_card", "props": card}),
        ("ui_summary_card", {"title": "꾸민 요약", "lines": ["x" * 121]}),  # 스키마 오류: 세지 않는다
        ("ui_summary_card", card),
        ("ui_block", BLOCK),
        ("ui_choice", {"question": "어느 쪽?", "options": CHOICES[:2]}),  # 셋째
    ]
    async with BeEnv.start(tmp_path, start=START, script=[FakeTurn(calls, "꾸민 답")]) as env:
        _, raw = await env.chat("꾸민 질문")
    chunks = parse_sse(raw)

    drawn = [c["toolName"] for c in chunks if c["type"] == "tool-input-available"]
    assert drawn == ["propose_tasks", "pin_card", "ui_summary_card", "ui_block", "ui_todo_draft"]
    assert [c["toolCallId"] for c in chunks if c["type"] == "tool-output-available"][-1] == "h_draft_1"


def test_reply_cap_error_text_and_no_method_call(uenv, monkeypatch):
    from my_planner.tools import mcp_adapter

    sink = ListSink()
    ctx = _app_ctx(stream=UiMessageWriter(sink, "m-1-1"))
    assert mcp_adapter.UI_PARTS_PER_REPLY == 2
    for _ in range(2):
        assert call_tool(uenv.tools, ctx, "ui_block", BLOCK) == {"ok": True}
    called = []
    monkeypatch.setattr(uenv.tools, "ui_block", lambda *a, **k: called.append(1) or {"ok": True})

    assert call_tool(uenv.tools, ctx, "ui_block", BLOCK) == {"error": CAP_ERR}
    assert called == [] and ctx.ui_drawn == 2
    assert len(sink.chunks) == 4  # 조각 둘(입력·출력)만


def test_new_tools_absent_from_telegram(uenv):
    for name in NEW_TOOLS:
        assert name in tool_names_for(RunContext(None, None, channel="app")) and name not in tool_names_for(RunContext(None, None, channel="telegram"))
    app_ctx = RunContext(conversation_id=None, run_id=None, channel="app")
    assert set(NEW_TOOLS) <= {t.name for t in build_planner_tools(uenv.tools, app_ctx)}


def test_app_tool_count_plus_four():
    """도구 수는 절대 수가 아니라 G-BE1 전후 차이로 쓴다(9.3): 앱 전용은 G-BE1 때의 일곱(SP7 `ui_habit_check` 포함)과
    SP9의 열 + 새 넷."""
    before = {"ui_todo_list", "ui_choice", "ui_summary_card", "ui_habit_check", "pin_card", "unpin_card", "reorder_cards",
              "set_checkin_time", "search_memos", "read_memo", "create_memo", "find_conversations",  # SP9
              "list_events", "create_event", "update_event", "delete_event", "ui_events",
              "propose_measures"}  # SP13-05
    app_only = set(tool_names_for(RunContext(None, None, channel="app"))) - set(TOOL_NAMES)
    assert app_only == before | set(NEW_TOOLS)
    assert len(app_only) == len(before) + 4


async def test_ui_props_not_in_logs(tmp_path):
    """시스템 로그에 화면 조각의 글이 없다(SP6 12장, SP3-4 14장): 그린 조각과 거절된 조각 모두."""
    from test_api_logging import _raw

    from my_planner.logging_setup import setup_logging

    secret = "비밀제목XYZ"
    ok = ("ui_block", {"title": secret, "children": [{"type": "text", "md": f"{secret} 글"}]})
    bad = ("ui_block", {"title": secret, "children": [{"type": "divider"}, {"type": "text", "md": secret}]})
    async with BeEnv.start(tmp_path, start=START, script=[FakeTurn([bad, ok], "꾸민 답")]) as env:
        setup_logging(env.settings.paths.state_dir, 30)
        _, stream = await env.chat("꾸민 질문")
        raw = _raw(env.settings.paths.state_dir)

    assert secret.encode() in stream  # 스트림에는 있다
    assert secret not in raw


def _walk(node):
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk(v)


@pytest.mark.parametrize("name", NEW_TOOLS)
def test_new_tool_input_schema_is_plain_json_schema(name):
    """도구 입력 스키마(두뇌에게 주는 것): `$ref`가 모두 그 스키마 안에서 풀리고, OpenAPI `discriminator` 힌트가 없다
    (카탈로그의 바깥 `children` 구분 표는 `group`을 `$ref` 문자열이 아니라 안쪽 스키마로 가리켜 맞는 mapping이 아니다).
    판정은 `oneOf` + `type`·`layout`의 `const`로 같다: 공유 고정 자료의 `ok`는 모두 통과한다."""
    from pathlib import Path

    import jsonschema

    from my_planner.tools.mcp_adapter import _SPECS

    _, schema = _SPECS[name]
    jsonschema.Draft202012Validator.check_schema(schema)
    nodes = list(_walk(schema))
    assert not any("discriminator" in n for n in nodes)
    defs = schema.get("$defs", {})
    for ref in (n["$ref"] for n in nodes if "$ref" in n):
        assert ref.startswith("#/$defs/") and ref.removeprefix("#/$defs/") in defs, ref
    assert "discriminator" in json.dumps(UI_COMPONENTS[name]["schema"]) or name != "ui_block"  # 카탈로그는 그대로
    validator = jsonschema.Draft202012Validator(schema)
    oks = sorted((Path(__file__).parent / "fixtures" / "ui_props" / name / "ok").glob("*.json"))
    assert oks
    for p in oks:
        validator.validate(json.loads(p.read_text(encoding="utf-8")))


# --- G-BE2 지금 값 (스펙 6.3 표, 7.3, 10.2) ---


def _stream(tools, ctx, name, args):
    sink = ListSink()
    ctx.stream = UiMessageWriter(sink, "m-1-1")
    assert call_tool(tools, ctx, name, args) == {"ok": True}
    ctx.stream = None
    (out,) = [c["output"] for c in sink.chunks if c["type"] == "tool-output-available"]
    return out


def _item(tools, ctx, tid):
    (item,) = _stream(tools, ctx, "ui_result", {"task_ids": [tid]})["data"]["items"]
    return item


def _none_but(**kw):
    return {"status": None, "planned_for": None, "scheduled_at": None, "title": None, **kw}


@pytest.mark.parametrize("kind", [
    "task_added", "task_moved", "task_completed", "task_reopened", "task_dropped", "task_updated", "tasks_confirmed",
])
def test_result_before_per_activity_kind(uenv, kind):
    tools = uenv.tools
    ctx = _app_ctx()
    pre = {"planned_for": "2026-10-25", "scheduled_at": "2026-10-25T14:00"}
    if kind == "task_added":
        tid = tools.add_task(ctx, title="꾸민 추가", areas=["health"], planned_for=pre["planned_for"])["id"]  # SP9: 시각 없이
        change, before = "added", None
    elif kind == "tasks_confirmed":
        tid = tools.propose_tasks(_app_ctx(), tasks=[{"title": "꾸민 초안", "areas": ["health"]}])["proposed"][0]["id"]
        tools.confirm_tasks(ctx, ids=[tid])
        change, before = "confirmed", _none_but(status="draft")
    else:
        tid = _add(tools, "꾸민 할 일", **pre)
        if kind == "task_reopened":
            tools.complete_task(_app_ctx(), id=tid)
        if kind == "task_moved":
            tools.move_task(ctx, id=tid, planned_for="2026-10-27")
            change = "moved"
            before = _none_but(planned_for="2026-10-25", scheduled_at="2026-10-25T05:00:00Z")
        elif kind == "task_updated":
            tools.update_task(ctx, id=tid, title="꾸민 새 제목")
            change, before = "updated", _none_but(title="꾸민 할 일")
        else:
            getattr(tools, {"task_completed": "complete_task", "task_reopened": "reopen_task",
                            "task_dropped": "drop_task"}[kind])(ctx, id=tid)
            change = kind.removeprefix("task_")
            status = "done" if kind == "task_reopened" else "open"
            before = _none_but(status=status, planned_for="2026-10-25", scheduled_at="2026-10-25T05:00:00Z")
    t = tools.tasks.get(tid)
    item = _item(tools, ctx, tid)

    assert item["change"] == change
    assert item["before"] == before
    assert item["after"] == {
        "status": t.status.value, "planned_for": t.planned_for.isoformat() if t.planned_for else None,
        "scheduled_at": to_api_times({"scheduled_at": t.scheduled_at.isoformat()})["scheduled_at"]
        if t.scheduled_at else None,
        "title": t.title if kind == "task_updated" else None,
    }
    assert item["todo"] == to_api_times(todo_ref(t, tools.tasks, TODAY))
    assert item["activity_ids"] == ctx.activity_ids
    assert item["undo_id"] == ctx.activity_ids[0]  # 활동 하나, 대상 하나, 지금 되돌릴 수 있음


def test_result_added_then_moved_has_no_undo(uenv):
    tools = uenv.tools
    ctx = _app_ctx()
    tid = tools.add_task(ctx, title="꾸민 추가", areas=["health"])["id"]
    tools.move_task(ctx, id=tid, planned_for="2026-10-27")
    item = _item(tools, ctx, tid)
    assert (item["change"], item["before"], item["undo_id"]) == ("added", None, None)
    assert item["after"]["planned_for"] == "2026-10-27" and len(item["activity_ids"]) == 2


def test_result_single_move_has_undo(uenv):
    tools = uenv.tools
    tid = _add(tools, planned_for="2026-10-25")
    ctx = _app_ctx()
    tools.move_task(ctx, id=tid, planned_for="2026-10-27")
    item = _item(tools, ctx, tid)
    assert item["change"] == "moved" and item["undo_id"] == ctx.activity_ids[0] == ctx.undo_ids[0]
    assert item["before"]["planned_for"] == "2026-10-25" and item["after"]["planned_for"] == "2026-10-27"


def test_result_two_moves_before_is_first(uenv):
    tools = uenv.tools
    tid = _add(tools, planned_for="2026-10-25")  # A
    ctx = _app_ctx()
    tools.move_task(ctx, id=tid, planned_for="2026-10-26")  # B
    tools.move_task(ctx, id=tid, planned_for="2026-10-27")  # C
    item = _item(tools, ctx, tid)
    assert item["before"]["planned_for"] == "2026-10-25" and item["after"]["planned_for"] == "2026-10-27"
    assert item["undo_id"] is None and item["activity_ids"] == ctx.activity_ids


def test_result_tasks_confirmed_two_tasks_no_undo(uenv):
    tools = uenv.tools
    drafts = tools.propose_tasks(_app_ctx(), tasks=[{"title": "꾸민 초안 하나", "areas": ["health"]},
                                                     {"title": "꾸민 초안 둘", "areas": ["health"]}])["proposed"]
    ids = [d["id"] for d in drafts]
    ctx = _app_ctx()
    tools.confirm_tasks(ctx, ids=ids)
    items = _stream(tools, ctx, "ui_result", {"task_ids": ids})["data"]["items"]
    assert [(i["todo"]["id"], i["change"], i["undo_id"]) for i in items] == [(ids[0], "confirmed", None),
                                                                            (ids[1], "confirmed", None)]
    assert all(i["activity_ids"] == ctx.activity_ids for i in items)


def test_result_confirmed_change_no_undo(uenv):
    """확인 토큰으로 적용한 변경(`risk = confirm`)은 되돌릴 수 없다(SP3-4 6.4.2)."""
    tools = uenv.tools
    tid = _add(tools, planned_for="2026-10-25")
    ctx = RunContext(conversation_id=1, run_id=None, channel="app", risk="confirm")
    tools.move_task(ctx, id=tid, planned_for="2026-10-27")
    item = _item(tools, ctx, tid)
    assert item["change"] == "moved" and item["undo_id"] is None and item["activity_ids"] == ctx.activity_ids


def test_result_activity_ids_oldest_first(uenv):
    tools = uenv.tools
    tid, other = _add(tools, planned_for="2026-10-25"), _add(tools, "꾸민 다른 것")
    ctx = _app_ctx()
    tools.move_task(ctx, id=tid, planned_for="2026-10-26")
    tools.complete_task(ctx, id=other)
    tools.complete_task(ctx, id=tid)
    item = _item(tools, ctx, tid)
    assert item["activity_ids"] == [ctx.activity_ids[0], ctx.activity_ids[2]]
    assert item["change"] == "completed"  # 가장 늦은 활동
    assert item["before"] == _none_but(planned_for="2026-10-25")  # 가장 이른 활동(옮김)


def test_block_data_todos_order_and_dedupe(uenv):
    tools = uenv.tools
    a, b, c = _add(tools, "꾸민 하나"), _add(tools, "꾸민 둘"), _add(tools, "꾸민 셋")
    d = tools.propose_tasks(_app_ctx(), tasks=[{"title": "꾸민 초안", "areas": ["health"]}])["proposed"][0]["id"]
    props = {"title": "꾸민 카드", "children": [
        {"type": "todo_rows", "task_ids": [a, b]},
        {"type": "group", "layout": "stack", "children": [
            {"type": "text", "md": "꾸민 글"}, {"type": "todo_rows", "task_ids": [b, c, d]}]},
    ]}
    out = _stream(tools, _app_ctx(), "ui_block", props)
    assert out["data"]["today"] == "2026-10-24"
    assert [t["id"] for t in out["data"]["todos"]] == [a, b, c]
    assert _stream(tools, _app_ctx(), "ui_block", BLOCK)["data"] == {"today": "2026-10-24"}


def test_date_choice_data_todo_null_when_deleted(uenv):
    from my_planner.tools.mcp_adapter import _stream_output

    tools = uenv.tools
    tid = _add(tools, "꾸민 치과")
    args = {"task_id": tid, "question": "언제?", "candidates": _cands(1, 2)}
    out = _stream(tools, _app_ctx(), "ui_date_choice", args)
    assert out == {"ok": True, "data": {"today": "2026-10-24", "todo": to_api_times(
        todo_ref(tools.tasks.get(tid), tools.tasks, TODAY))}}
    _soft_delete(uenv, tid)  # 그린 뒤 지워짐(다시 읽는 쪽이 같은 값을 만든다)
    gone = _stream_output(tools, _app_ctx(), "ui_date_choice", args, {"ok": True})
    assert gone == {"ok": True, "data": {"today": "2026-10-24", "todo": None}}


def test_period_data_shape(uenv):
    tools = uenv.tools
    mon = _add(tools, "꾸민 월요일", planned_for="2026-10-26")
    out_of = _add(tools, "꾸민 밖", planned_for="2026-10-27")
    today_task = _add(tools, "꾸민 오늘", planned_for="2026-10-24")
    ctx = _app_ctx()
    tools.move_task(ctx, id=out_of, planned_for="2026-11-03")  # 주 밖으로
    tools.move_task(ctx, id=mon, planned_for="2026-10-26")  # 같은 날(바뀐 줄 표시만)

    nxt = _stream(tools, ctx, "ui_period_list", {"week": "2026-W44", "highlight_task_ids": [mon, out_of]})["data"]
    assert (nxt["today"], nxt["start"], nxt["end"]) == ("2026-10-24", "2026-10-26", "2026-11-01")
    assert [d["date"] for d in nxt["days"]] == [_d(n) for n in range(2, 9)]
    assert [d["weekday"] for d in nxt["days"]] == list("월화수목금토일")
    assert not any(d["is_today"] for d in nxt["days"])
    assert [t["id"] for t in nxt["days"][0]["todos"]] == [mon]
    assert nxt["outside"] == [{"reason": "moved", "todo": to_api_times(
        todo_ref(tools.tasks.get(out_of), tools.tasks, TODAY))}]

    this = _stream(tools, _app_ctx(), "ui_period_list", {"week": "2026-W43"})["data"]
    assert [d["is_today"] for d in this["days"]] == [False] * 5 + [True, False]
    assert [t["id"] for t in this["days"][5]["todos"]] == [today_task] and this["outside"] == []
    one = _stream(tools, _app_ctx(), "ui_period_list", {"day": "2026-10-24"})["data"]
    assert (one["start"], one["end"], len(one["days"])) == ("2026-10-24", "2026-10-24", 1)
    assert one["days"][0] == {"date": "2026-10-24", "weekday": "토", "is_today": True,
                              "todos": this["days"][5]["todos"]}


async def test_add_task_without_date_streams_the_filled_day(tmp_path):
    # 두뇌가 날짜를 빼면 하네스가 오늘로 채우고, 앱이 받는 도구 입력·결과에도 그 날짜가 있다
    add = ("add_task", {"title": "꾸민 치과", "areas": ["health"]})
    async with BeEnv.start(tmp_path, start=START, script=[FakeTurn([add], "넣었어요.")]) as env:
        _, raw = await env.chat("치과 예약 추가해 줘")
    chunks = parse_sse(raw)
    inputs = [c for c in chunks if c.get("type") == "tool-input-available" and c.get("toolName") == "add_task"]
    outputs = [c for c in chunks if c.get("type") == "tool-output-available" and c["toolCallId"] == inputs[0]["toolCallId"]]
    assert inputs[0]["input"]["planned_for"] == "2026-10-24"
    assert outputs[0]["output"]["planned_for"] == "2026-10-24"
