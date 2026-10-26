"""퀵 칩 카드 보장 (SP9c 4.4): 칩 차례가 정상으로 끝나면 하네스가 빠진 결과 카드를 `h_chip`으로 붙인다.

가짜 두뇌 + 가짜 시계(`BeEnv`). 고정 자료는 꾸며 낸 내용만 쓴다.
"""

import logging
from datetime import timedelta

import pytest
from be_env import BeEnv
from fakes import FakeTurn, ListSink
from test_dispatcher_messages import kst
from ui_stream import parse_sse

from my_planner.domain import RunContext
from my_planner.harness import chip_cards as chip_cards_mod
from my_planner.harness.stream import UiMessageWriter
from my_planner.tools.mcp_adapter import call_tool
from my_planner.tools.ui import validate_props

START = kst(2026, 10, 24, 13, 0)  # 토요일 오후. 논리적 오늘은 10/24, "내일"은 10/25
DENTIST_EVENT = ("create_event", {"title": "꾸민 치과", "date": "2026-10-25", "time": "15:00"})
SUMMARY = ("ui_summary_card", {"title": "정리", "lines": ["한 줄"]})


def _ui(chunks):
    """화면 조각(`ui_*`): `[(toolCallId, 컴포넌트, input, output)]`, 나온 순서."""
    outs = {c["toolCallId"]: c["output"] for c in chunks if c["type"] == "tool-output-available"}
    return [
        (c["toolCallId"], c["toolName"], c["input"], outs.get(c["toolCallId"]))
        for c in chunks if c["type"] == "tool-input-available" and c["toolName"].startswith("ui_")
    ]


def _chip(chunks):
    return [u for u in _ui(chunks) if u[0].startswith("h_chip")]


async def _run(tmp_path, chip, script, *, text="꾸민 글", start=START, before=None):
    async with BeEnv.start(tmp_path, start=start, script=script) as env:
        if before is not None:
            before(env)
        _, raw = await env.chat(text, chip=chip)
        return parse_sse(raw), env.brain.calls[0]["run_ctx"] if env.brain.calls else None


# --- 두뇌 쪽 이름 (4.4) ---


def test_call_tool_records_drawn_names():
    class _T:
        def ui_summary_card(self, ctx, **kw):
            return {"ok": True}

        def ui_choice(self, ctx, **kw):
            return {"error": "x"}

    ctx = RunContext(conversation_id=1, run_id=None, channel="app", stream=UiMessageWriter(ListSink(), "m"))
    call_tool(_T(), ctx, "ui_choice", {"question": "q", "options": []})
    call_tool(_T(), ctx, "ui_summary_card", {"title": "t", "lines": ["a"]})
    assert ctx.ui_drawn == 1 and ctx.ui_drawn_names == ["ui_summary_card"]


# --- event ---


async def test_event_chip_adds_ui_events_when_brain_only_created(tmp_path):
    chunks, _ = await _run(tmp_path, "event", [FakeTurn([DENTIST_EVENT], "넣었어요.")], text="내일 오후 3시 치과")

    ((cid, name, props, output),) = _chip(chunks)
    assert cid == "h_chip_1" and name == "ui_events" and output == {"ok": True}
    (item,) = props["items"]
    assert item["date"] == "2026-10-25" and item["start"] == "2026-10-25T06:00:00Z"
    assert item["title"] == "꾸민 치과" and item["all_day"] is False and item["repeat"] == "none"
    assert set(item) == {"event_id", "date", "start", "end", "all_day", "title", "area", "remind_min", "repeat", "origin"}
    assert validate_props("ui_events", props) is None
    # 글 다음, finish-step 앞
    at = next(i for i, c in enumerate(chunks) if c.get("toolCallId") == "h_chip_1")
    types = [c["type"] for c in chunks]
    assert types.index("text-end") < at < types.index("finish-step")


async def test_event_chip_brain_drew_ui_events_no_duplicate(tmp_path):
    items = [{"event_id": 1, "date": "2026-10-25", "start": "2026-10-25T06:00:00Z", "end": None, "all_day": False,
              "title": "꾸민 치과", "area": None, "remind_min": 10, "repeat": "none", "origin": "chat"}]
    script = [FakeTurn([DENTIST_EVENT, ("ui_events", {"items": items})], "넣었어요.")]
    chunks, ctx = await _run(tmp_path, "event", script)

    assert [u[1] for u in _ui(chunks)] == ["ui_events"] and _chip(chunks) == []
    assert ctx.ui_drawn_names == ["ui_events"]


async def test_event_chip_two_brain_parts_no_room(tmp_path):
    script = [FakeTurn([DENTIST_EVENT, SUMMARY, SUMMARY], "넣었어요.")]
    chunks, _ = await _run(tmp_path, "event", script)
    assert [u[1] for u in _ui(chunks)] == ["ui_summary_card", "ui_summary_card"] and _chip(chunks) == []


async def test_event_chip_one_brain_part_leaves_room(tmp_path):
    chunks, _ = await _run(tmp_path, "event", [FakeTurn([DENTIST_EVENT, SUMMARY], "넣었어요.")])
    assert [u[1] for u in _ui(chunks)] == ["ui_summary_card", "ui_events"]


async def test_event_chip_repeat_is_start_date_and_sorted(tmp_path):
    weekly = ("create_event", {"title": "꾸민 수영", "date": "2026-10-27", "time": "07:00", "repeat": "weekly"})
    later = ("create_event", {"title": "꾸민 저녁", "date": "2026-10-25", "time": "19:00"})
    allday = ("create_event", {"title": "꾸민 휴가", "date": "2026-10-25", "all_day": True})
    chunks, _ = await _run(tmp_path, "event", [FakeTurn([weekly, later, allday], "넣었어요.")])

    ((_, _, props, _),) = _chip(chunks)
    assert [(i["date"], i["title"]) for i in props["items"]] == [
        ("2026-10-25", "꾸민 휴가"), ("2026-10-25", "꾸민 저녁"), ("2026-10-27", "꾸민 수영"),
    ]
    assert props["items"][2]["repeat"] == "weekly"


async def test_event_chip_nothing_created_no_card(tmp_path):
    chunks, _ = await _run(tmp_path, "event", [FakeTurn([], "안녕하세요.")], text="안녕")
    assert _ui(chunks) == []


# --- todo ---


def _task(title, day):
    return ("add_task", {"title": title, "areas": ["career"], "planned_for": day})


async def test_todo_chip_one_task_ui_result(tmp_path):
    chunks, _ = await _run(tmp_path, "todo", [FakeTurn([_task("꾸민 보고서", "2026-10-25")], "넣었어요.")])

    ((_, name, props, output),) = _chip(chunks)
    assert name == "ui_result" and len(props["task_ids"]) == 1
    data = output["data"]
    assert data["today"] == "2026-10-24"
    (item,) = data["items"]
    assert item["change"] == "added" and item["todo"]["id"] == props["task_ids"][0]


async def test_todo_chip_three_tasks_period_list(tmp_path):
    script = [FakeTurn([_task(f"꾸민 일 {n}", "2026-10-26") for n in range(3)], "넣었어요.")]
    chunks, _ = await _run(tmp_path, "todo", script)

    ((_, name, props, output),) = _chip(chunks)
    assert name == "ui_period_list" and props["day"] == "2026-10-26" and len(props["highlight_task_ids"]) == 3
    assert output["data"]["start"] == output["data"]["end"] == "2026-10-26"
    assert len(output["data"]["days"][0]["todos"]) == 3


async def test_todo_chip_three_tasks_out_of_range_ui_result_first_two(tmp_path):
    far = (START + timedelta(days=60)).date().isoformat()
    script = [FakeTurn([_task(f"꾸민 일 {n}", far) for n in range(3)], "넣었어요.")]
    async with BeEnv.start(tmp_path, start=START, script=script) as env:
        _, raw = await env.chat("꾸민 글", chip="todo")
        ids = [r[0] for r in env.conn.execute("SELECT id FROM tasks ORDER BY id")]

    ((_, name, props, output),) = _chip(parse_sse(raw))
    assert name == "ui_result" and props["task_ids"] == ids[:2] and len(output["data"]["items"]) == 2


async def test_todo_chip_event_only_ui_events(tmp_path):
    chunks, _ = await _run(tmp_path, "todo", [FakeTurn([DENTIST_EVENT], "일정으로 넣었어요.")])
    ((_, name, props, _),) = _chip(chunks)
    assert name == "ui_events" and props["items"][0]["title"] == "꾸민 치과"


async def test_todo_chip_nothing_created_or_brain_drew(tmp_path):
    chunks, _ = await _run(tmp_path, "todo", [FakeTurn([], "안녕하세요.")], text="안녕")
    assert _ui(chunks) == []


async def test_todo_chip_brain_drew_period_list(tmp_path):
    script = [FakeTurn([_task("꾸민 보고서", "2026-10-24"), ("ui_period_list", {"day": "2026-10-24"})], "넣었어요.")]
    chunks, _ = await _run(tmp_path, "todo", script)
    assert [u[1] for u in _ui(chunks)] == ["ui_period_list"] and _chip(chunks) == []


# --- memo ---


async def test_memo_chip_summary_card(tmp_path):
    body = "# 장보기\n- 우유\n\n- 계란\n- 빵\n- 버터"
    chunks, _ = await _run(tmp_path, "memo", [FakeTurn([("create_memo", {})], "메모해 뒀어요.")], text=body)

    ((_, name, props, output),) = _chip(chunks)
    assert name == "ui_summary_card" and output == {"ok": True}
    assert props == {"title": "장보기", "lines": ["우유", "계란", "빵"]}


async def test_memo_chip_one_line_and_redacted(tmp_path):
    chunks, _ = await _run(tmp_path, "memo", [FakeTurn([("create_memo", {})], "메모해 뒀어요.")], text="꾸민 한 줄 메모")
    ((_, _, props, _),) = _chip(chunks)
    assert props == {"title": "꾸민 한 줄 메모", "lines": ["메모 탭에서 볼 수 있어요."]}

    text = "꾸민 계정\n비밀번호 1234abcd 적어둬"
    chunks, _ = await _run(tmp_path / "b", "memo", [FakeTurn([("create_memo", {})], "메모해 뒀어요.")], text=text)
    ((_, _, props, _),) = _chip(chunks)
    assert props["lines"] == ["비밀번호 [가림] 적어둬"] and "1234abcd" not in str(chunks)


async def test_memo_chip_brain_drew_summary(tmp_path):
    chunks, _ = await _run(tmp_path, "memo", [FakeTurn([("create_memo", {}), SUMMARY], "메모해 뒀어요.")])
    assert [u[1] for u in _ui(chunks)] == ["ui_summary_card"] and _chip(chunks) == []


# --- today ---


@pytest.mark.parametrize(("start", "day"), [(START, "2026-10-24"), (kst(2026, 10, 25, 1, 30), "2026-10-24")])
async def test_today_chip_period_list_logical_day(tmp_path, start, day):
    chunks, _ = await _run(tmp_path, "today", [FakeTurn([], "오늘은 조용해요.")], text="오늘 정리해줘", start=start)

    ((_, name, props, output),) = _chip(chunks)
    assert name == "ui_period_list" and props == {"day": day}
    assert output["data"]["today"] == day and output["data"]["start"] == day


# --- next ---


async def test_next_chip_no_events_no_card(tmp_path):
    chunks, _ = await _run(tmp_path, "next", [FakeTurn([], "다가오는 일정이 없어요.")])
    assert _ui(chunks) == []


async def test_next_chip_upcoming_sorted(tmp_path):
    def seed(env):
        user = RunContext(conversation_id=None, run_id=None, actor="user", channel="app")
        t = env.parts.tools
        t.create_event(user, title="꾸민 휴가", date="2026-10-25", all_day=True)
        t.create_event(user, title="꾸민 오후", date="2026-10-24", time="15:00")
        t.create_event(user, title="꾸민 오전", date="2026-10-24", time="09:00")  # 지났다
        t.create_event(user, title="꾸민 먼 일", date="2026-11-05", time="09:00")  # 7일 밖

    chunks, _ = await _run(tmp_path, "next", [FakeTurn([], "다음은 오후 일정이에요.")], before=seed)

    ((_, name, props, _),) = _chip(chunks)
    assert name == "ui_events" and [i["title"] for i in props["items"]] == ["꾸민 오후", "꾸민 휴가"]


# --- 붙이지 않는 경로 ---


async def test_no_chip_card_after_brain_error(tmp_path):
    script = [FakeTurn([], "", status="error", error="x") for _ in range(4)]
    chunks, _ = await _run(tmp_path, "today", script)
    assert _ui(chunks) == []


async def test_no_chip_card_when_capped(tmp_path):
    async with BeEnv.start(tmp_path, start=START) as env:
        env.conn.execute("INSERT INTO usage_state (date, brain_calls) VALUES ('2026-10-24', 60)")
        env.conn.commit()
        _, raw = await env.chat("오늘 정리해줘", chip="today")
    assert _ui(parse_sse(raw)) == []


async def test_no_chip_card_on_replay(tmp_path):
    async with BeEnv.start(tmp_path, start=START, script=[FakeTurn([], "오늘은 조용해요.")]) as env:
        _, first = await env.chat("오늘 정리해줘", chip="today", client_msg_id="cm-chip")
        _, again = await env.chat("오늘 정리해줘", chip="today", client_msg_id="cm-chip")
    assert len(_chip(parse_sse(first))) == 1 and _ui(parse_sse(again)) == []


async def test_no_chip_card_without_chip(tmp_path):
    async with BeEnv.start(tmp_path, start=START, script=[FakeTurn([DENTIST_EVENT], "넣었어요.")]) as env:
        _, raw = await env.chat("내일 3시 치과")
    assert _chip(parse_sse(raw)) == []


# --- 검사와 로그 ---


async def test_invalid_card_is_skipped_and_logged(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(chip_cards_mod, "memo_title", lambda body: "")  # 일부러 깨진 props(title 빈 글)
    caplog.set_level(logging.INFO)
    chunks, _ = await _run(tmp_path, "memo", [FakeTurn([("create_memo", {})], "메모해 뒀어요.")], text="꾸민 메모")

    assert _ui(chunks) == []
    (rec,) = [r for r in caplog.records if r.getMessage() == "chip_card_invalid"]
    assert (rec.chip, rec.component) == ("memo", "ui_summary_card")
    assert not [r for r in caplog.records if r.getMessage() == "chip_card_added"]


async def test_added_card_is_logged_without_content(tmp_path, caplog):
    caplog.set_level(logging.INFO)
    await _run(tmp_path, "memo", [FakeTurn([("create_memo", {})], "메모해 뒀어요.")], text="꾸민 비밀 메모\n둘째 줄")

    (rec,) = [r for r in caplog.records if r.getMessage() == "chip_card_added"]
    assert (rec.chip, rec.component) == ("memo", "ui_summary_card")
    logged = "\n".join(f"{r.getMessage()} {r.__dict__}" for r in caplog.records if r.name.endswith("chip_cards"))
    assert "꾸민 비밀 메모" not in logged and "둘째 줄" not in logged


def test_harness_card_skips_text_check():
    """하네스가 내는 두뇌 쪽 조각은 글 검사(금지어)를 건너뛴다(4.4, ui.py의 하네스 규칙)."""
    from my_planner.tools.ui import banned_words

    props = {"title": "꾸민 메모", "lines": [f"{banned_words()[0]} 들어간 줄"]}
    assert validate_props("ui_summary_card", props) is not None
    assert validate_props("ui_summary_card", props, harness=True) is None
