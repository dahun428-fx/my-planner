"""곡선·상태 두뇌 도구 (SP3-4 스펙 10장, 11.3). 내용은 꾸며 낸 것이다."""

import json
from datetime import timedelta

from be_env import BeEnv
from fakes import FakeTurn
from test_dispatcher_messages import kst

from my_planner.domain import RunContext
from my_planner.status.snapshot import status_snapshot
from my_planner.tools.mcp_adapter import (
    APP_ONLY_TOOLS,
    TOOL_NAMES,
    build_planner_tools,
    tool_names_for,
)

SAT_1300 = kst(2026, 10, 24, 13, 0)
CURVE_TOOLS = [
    "record_ladder_score", "record_area_scores", "add_milestone", "confirm_milestones", "propose_chapter",
    "confirm_chapters", "drop_curve_drafts", "get_curve", "get_status", "grant_xp",
]


def _ctx(conversation_id=None):
    return RunContext(conversation_id=conversation_id, run_id=None)


def _curve_titles(env):
    body = env.parts.tools.get_curve(_ctx(), zoom="year", **{"from": "2015-01-01", "to": "2026-12-31"})
    return [m["title"] for m in body["milestones"]]


# --- 슬라이스 1 ---


async def test_add_milestone_is_draft_not_in_curve(tmp_path):
    async with BeEnv.start(tmp_path, start=SAT_1300) as env:
        ctx = _ctx()
        out = env.parts.tools.add_milestone(ctx, date="2019", kind="high", title="꾸민 여행")
        m = env.parts.curve.get_milestone(out["id"])
        log = env.conn.execute("SELECT kind, data_json FROM tool_events_log").fetchall()
        acts = [(r["kind"], r["actor"], r["summary"], r["undo_json"]) for r in env.activity()]
        titles = _curve_titles(env)
        resp = await env.get("/curve?zoom=year&from=2015-01-01&to=2026-12-31")
        api = await resp.json()

    assert out["status"] == "draft" and out["date"] == "2019" and out["kind"] == "high"
    assert m is not None and m.status == "draft" and m.origin == "chat" and m.draft_since is not None
    assert [e.kind for e in ctx.events] == ["milestone_proposed"]
    assert ctx.events[0].data["id"] == out["id"]
    assert [r["kind"] for r in log] == ["milestone_proposed"]
    assert json.loads(log[0]["data_json"])["id"] == out["id"]
    assert acts == [("milestone_proposed", "secretary", "✓ 제안: 꾸민 여행", None)]
    assert titles == [] and api["milestones"] == []


async def test_milestone_date_precision_and_sort_date(tmp_path):
    async with BeEnv.start(tmp_path, start=SAT_1300) as env:
        tools = env.parts.tools
        got = []
        for d in ("2019", "2019-05", "2019-05-17"):
            mid = tools.add_milestone(_ctx(), date=d, kind="low", title=f"꾸민 {d}")["id"]
            m = env.parts.curve.get_milestone(mid)
            got.append((m.date_text, m.precision, m.sort_date.isoformat()))
        bad = [tools.add_milestone(_ctx(), date=d, kind="high", title="꾸민 것")
               for d in ("2023-5", "2019-13", "19", "2019/05", None)]
        bad_kind = tools.add_milestone(_ctx(), date="2019", kind="peak", title="꾸민 것")
        bad_title = tools.add_milestone(_ctx(), date="2019", kind="high", title="가" * 101)
        rows = env.conn.execute("SELECT COUNT(*) FROM curve_milestones").fetchone()[0]

    assert got == [("2019", "year", "2019-01-01"), ("2019-05", "month", "2019-05-01"),
                   ("2019-05-17", "day", "2019-05-17")]
    assert all("error" in b for b in [*bad, bad_kind, bad_title])
    assert rows == 3


async def test_sensitive_default_false(tmp_path):
    async with BeEnv.start(tmp_path, start=SAT_1300) as env:
        tools = env.parts.tools
        plain = tools.add_milestone(_ctx(), date="2019", kind="high", title="꾸민 하나")
        marked = tools.add_milestone(_ctx(), date="2020", kind="low", title="꾸민 둘", sensitive=True)
        wrong = tools.add_milestone(_ctx(), date="2020", kind="low", title="꾸민 셋", sensitive="yes")
        summaries = [r["summary"] for r in env.activity()]

    assert plain["sensitive"] is False and marked["sensitive"] is True
    assert "error" in wrong
    assert summaries == ["✓ 제안: 꾸민 하나", "✓ 제안: (민감)"]  # 활동 요약은 민감 제목을 가린다


async def test_get_curve_from_key_maps_to_from_(tmp_path):
    async with BeEnv.start(tmp_path, start=SAT_1300) as env:
        tools = env.parts.tools
        mid = tools.add_milestone(_ctx(), date="2019", kind="high", title="꾸민 여행")["id"]
        tools.confirm_milestones(_ctx(), ids=[mid])
        ctx = _ctx()
        handlers = {t.name: t.handler for t in build_planner_tools(tools, ctx)}
        res = await handlers["get_curve"]({"from": "2019-01-01", "to": "2019-12-31", "zoom": "year"})
        default = await handlers["get_curve"]({})

    body = json.loads(res["content"][0]["text"])
    assert res["is_error"] is False
    assert (body["from"], body["to"], body["zoom"]) == ("2019-01-01", "2019-12-31", "year")
    assert [m["title"] for m in body["milestones"]] == ["꾸민 여행"]
    assert json.loads(default["content"][0]["text"])["zoom"] == "month"  # 기본 확대 단위


# --- 슬라이스 2 ---


async def test_confirm_milestones_by_natural_language(tmp_path):
    # "응 저장해" → 두뇌가 confirm_milestones(텔레그램 대화). 확인 문구가 답 아래에 붙고 칭호가 생긴다
    async with BeEnv.start(tmp_path, start=SAT_1300) as env:
        mid = env.parts.tools.add_milestone(_ctx(), date="2019", kind="high", title="제주 여행")["id"]
        env.brain.script = [FakeTurn([("confirm_milestones", {"ids": [mid]})], "곡선에 남겼어요.")]
        await env.telegram("응 저장해")
        status = await (await env.get("/status")).json()

    assert env.sender.sent[-1].text == "곡선에 남겼어요.\n\n✓ 저장: 제주 여행 (2019, 고점)\n칭호: 「제주 여행」의 순간"
    assert [t["title"] for t in status["titles"]] == ["「제주 여행」의 순간"]
    assert env.sender.sent[-1].draft_milestone_ids == []


async def test_drop_curve_drafts_rejects_confirmed(tmp_path):
    async with BeEnv.start(tmp_path, start=SAT_1300) as env:
        tools = env.parts.tools
        kept = tools.add_milestone(_ctx(), date="2019", kind="high", title="꾸민 하나")["id"]
        tools.confirm_milestones(_ctx(), ids=[kept])
        draft = tools.add_milestone(_ctx(), date="2020", kind="low", title="꾸민 둘")["id"]
        ch = tools.propose_chapter(_ctx(), title="꾸민 시절", start="2019-01", end="2020-12")
        refused = tools.drop_curve_drafts(_ctx(), milestone_ids=[kept, draft])
        still = env.parts.curve.get_milestone(draft)
        ok = tools.drop_curve_drafts(_ctx(), milestone_ids=[draft], chapter_ids=[ch["id"]])
        gone = (env.parts.curve.get_milestone(draft), env.parts.curve.get_chapter(ch["id"]))

    assert ch["status"] == "draft" and ch["start"] == "2019-01" and ch["end"] == "2020-12"
    assert "error" in refused and still is not None
    assert ok["dropped_milestone_ids"] == [draft] and ok["dropped_chapter_ids"] == [ch["id"]]
    assert gone == (None, None)


async def test_propose_chapter_validates(tmp_path):
    async with BeEnv.start(tmp_path, start=SAT_1300) as env:
        tools = env.parts.tools
        ctx = _ctx()
        good = tools.propose_chapter(ctx, title="꾸민 지금", start="2021-01", theme="꾸민 주제")
        bad = [
            tools.propose_chapter(_ctx(), title="꾸민 것", start="2021-1"),
            tools.propose_chapter(_ctx(), title="꾸민 것", start="2021-13"),
            tools.propose_chapter(_ctx(), title="꾸민 것", start="2021-05", end="2021-04"),
            tools.propose_chapter(_ctx(), title="", start="2021-05"),
        ]
        acts = [(r["kind"], r["summary"]) for r in env.activity()]

    assert good["end"] is None and [e.kind for e in ctx.events] == ["chapter_proposed"]
    assert all("error" in b for b in bad)
    assert acts == [("chapter_proposed", "✓ 제안: 꾸민 지금")]


async def test_get_curve_masks_sensitive_title(tmp_path):
    async with BeEnv.start(tmp_path, start=SAT_1300) as env:
        tools = env.parts.tools
        a = tools.add_milestone(_ctx(), date="2019", kind="high", title="꾸민 공개", note="꾸민 메모")["id"]
        b = tools.add_milestone(_ctx(), date="2020", kind="low", title="꾸민 비밀", sensitive=True)["id"]
        tools.confirm_milestones(_ctx(), ids=[a, b])
        tools.record_ladder_score(_ctx(), now=6, note="꾸민 사다리 메모")
        body = tools.get_curve(_ctx(), zoom="year", **{"from": "2019-01-01", "to": "2026-12-31"})
        bad = tools.get_curve(_ctx(), zoom="decade")
        text = json.dumps(body, ensure_ascii=False)

    assert [(m["title"], m["sensitive"]) for m in body["milestones"]] == [("꾸민 공개", False), ("(민감)", True)]
    assert "꾸민 비밀" not in text and "메모" not in text
    assert all("note" not in m for m in body["milestones"]) and all("note" not in x for x in body["ladder"])
    assert [x["now"] for x in body["ladder"]] == [6]
    assert "error" in bad


async def test_get_status_equals_snapshot(tmp_path):
    async with BeEnv.start(tmp_path, start=SAT_1300) as env:
        tools = env.parts.tools
        mid = tools.add_milestone(_ctx(), date="2019", kind="turning_point", title="꾸민 결심")["id"]
        tools.confirm_milestones(_ctx(), ids=[mid])
        tools.record_area_scores(_ctx(), scores={"health": 4})
        got = tools.get_status(_ctx())
        p = env.parts
        snap = status_snapshot(now=env.clock.now(), tz=env.settings.timezone, boundary=env.settings.day_boundary,
                               status=p.status, curve=p.curve, tasks=p.tasks, conditions=p.conditions)
        json.dumps(got, ensure_ascii=False)  # MCP 처리기가 그대로 JSON으로 보낸다

    granted = snap["titles"][0]["granted_at"]
    assert got["titles"][0]["granted_at"] == granted.astimezone(tools.tz).isoformat(timespec="minutes")
    for t in (*got["titles"], *snap["titles"]):
        t.pop("granted_at")
    for x in (*got["recent_xp"], *snap["recent_xp"]):
        x.pop("at")
    snap.pop("moments_hidden")  # 두뇌에는 지난 7일의 보이는 순간만 준다(SP8 10.3). 14일 숨긴 수는 `GET /status`만
    assert got == snap
    assert got["titles"][0]["title"] == "「꾸민 결심」을 지나온 사람"


async def test_tool_counts_28_and_35(tmp_path):
    """S12, 10장: 텔레그램 대화 28개(SP1 12 + 곡선 10 + 습관 6, SP7 5.4 H8), 앱 대화 35개(+ 화면 3, 습관 1, 카드 3)."""
    assert TOOL_NAMES[12:22] == CURVE_TOOLS
    assert len(tool_names_for(RunContext(None, None, channel="telegram"))) == 28
    assert len(tool_names_for(RunContext(None, None, channel="app"))) == 36  # SP9-02 `set_checkin_time`(앱에만)
    assert tool_names_for(RunContext(None, None, channel="app")) == TOOL_NAMES + APP_ONLY_TOOLS
    async with BeEnv.start(tmp_path, start=SAT_1300) as env:
        names = [t.name for t in build_planner_tools(env.parts.tools, _ctx())]
    assert names == TOOL_NAMES


async def test_curve_tools_in_run_turn_are_not_rerun_after_error(tmp_path):
    """회차 두뇌 호출이 곡선 도구를 부른 뒤 오류로 끝나면 다시 부르지 않는다(중복 기록 방지, 스펙 5.4-3)."""
    add = ("add_milestone", {"date": "2019", "kind": "high", "title": "꾸민 여행"})
    ladder = ("record_ladder_score", {"now": 6})
    script = [FakeTurn([add, ladder], "", status="error"), FakeTurn([], "다시")]
    async with BeEnv.start(tmp_path, start=kst(2026, 10, 24, 10, 0) + timedelta(seconds=30), script=script) as env:
        await env.tick()
        rows = env.conn.execute("SELECT COUNT(*) FROM curve_milestones").fetchone()[0]
        acts = [r["kind"] for r in env.activity()]
        calls = len(env.brain.calls)

    assert calls == 1 and rows == 1
    assert acts.count("milestone_proposed") == 1 and acts.count("ladder_recorded") == 1


async def test_curve_tools_in_message_are_not_rerun_after_error(tmp_path):
    """사용자 메시지 처리 중 곡선 도구가 쓴 뒤 두뇌 오류: 백오프로 다시 부르지 않고 확인 문구로 마친다."""
    add = ("add_milestone", {"date": "2019", "kind": "high", "title": "꾸민 여행"})
    ladder = ("record_ladder_score", {"now": 6})
    script = [FakeTurn([add, ladder], "", status="error"), FakeTurn([], "다시")]
    async with BeEnv.start(tmp_path, start=SAT_1300, script=script) as env:
        await env.telegram("예전에 꾸민 여행이 좋았어. 이번 달은 6")
        rows = env.conn.execute("SELECT COUNT(*) FROM curve_milestones").fetchone()[0]
        acts = [r["kind"] for r in env.activity()]

    assert len(env.brain.calls) == 1 and rows == 1
    assert acts.count("milestone_proposed") == 1 and acts.count("ladder_recorded") == 1
    assert env.sender.sent[-1].text.endswith("✓ 사다리를 기록했어요 (2026-10): 지금 6")
    assert len(env.sender.sent[-1].draft_milestone_ids) == 1  # 초안 버튼은 그대로 붙는다


async def test_kill_after_curve_tool_then_restart_does_not_rerun(tmp_path, conn, state):
    """두뇌 호출 도중 강제 종료, 곡선 도구가 이미 썼다: 다시 시작해도 두뇌를 다시 부르지 않는다(사건은 하나)."""
    import asyncio

    from test_dispatcher_messages import Env
    from test_inbound_recovery import START, _kill, _receive

    from my_planner.harness.dispatcher import FALLBACK_REPLY
    from my_planner.loop.runner import resubmit_inbound
    from my_planner.store.repos.curve import CurveRepo

    add = ("add_milestone", {"date": "2019", "kind": "high", "title": "꾸민 여행"})
    first = Env(tmp_path, conn, state, script=[FakeTurn([add], "", hang=True)], start=START, with_tools=True)
    first.tools.curve = CurveRepo(conn, first.clock)
    first.dispatcher.start()
    await _receive(first, state, 46, "예전에 꾸민 여행이 좋았어")
    while not first.brain.calls:
        await asyncio.sleep(0)
    await _kill(first)

    second = Env(tmp_path, conn, state, script=[], start=START + timedelta(minutes=5), with_tools=True)
    second.tools.curve = CurveRepo(conn, second.clock)
    resubmit_inbound(state, second.dispatcher)
    await second.process()

    rows = conn.execute("SELECT id FROM curve_milestones").fetchall()
    assert second.brain.calls == [] and len(rows) == 1
    assert [o.text for o in second.sender.sent] == [FALLBACK_REPLY]  # 초안에는 확인 문구가 없다
    assert second.sender.sent[0].draft_milestone_ids == [rows[0]["id"]]  # 버튼은 도구 기록에서 다시 만든다
