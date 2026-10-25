"""앱의 사건·챕터 초안 카드 (SP3-4 스펙 6.4.1, 6.4.5, 6.4.7, 11.3). 내용은 꾸며 낸 것이다."""

from datetime import timedelta

from be_env import BeEnv
from fakes import FakeTurn
from test_dispatcher_messages import kst
from ui_stream import parse_sse

from my_planner.tools.ui import validate_props

SAT_1300 = kst(2026, 10, 24, 13, 0)


def _harness(chunks):
    return [c for c in chunks if str(c.get("toolCallId", "")).startswith("h_")]


async def test_app_milestone_draft_chunk(tmp_path):
    add = ("add_milestone", {"date": "2019-05", "kind": "high", "title": "꾸민 여행"})
    secret = ("add_milestone", {"date": "2020", "kind": "low", "title": "꾸민 비밀", "sensitive": True})
    script = [FakeTurn([add, secret], "곡선에 남길까요?")]
    async with BeEnv.start(tmp_path, start=SAT_1300, script=script) as env:
        _, raw = await env.chat("예전 꾸민 여행이 좋았어")
        ids = [r[0] for r in env.conn.execute("SELECT id FROM curve_milestones ORDER BY id")]
    chunks = parse_sse(raw)

    harness = _harness(chunks)
    assert [(c["type"], c["toolCallId"]) for c in harness] == [
        ("tool-input-available", "h_mdraft_1"), ("tool-output-available", "h_mdraft_1"),
    ]
    assert harness[0]["toolName"] == "ui_milestone_draft" and harness[0]["input"] == {"milestone_ids": ids}
    assert validate_props("ui_milestone_draft", harness[0]["input"]) is None
    assert harness[1]["output"] == {"ok": True, "data": {"milestones": [
        {"id": ids[0], "title": "꾸민 여행", "date": "2019-05", "area": None, "sensitive": False},
        {"id": ids[1], "title": "꾸민 비밀", "date": "2020", "area": None, "sensitive": True},
    ]}}
    # 두뇌 도구 조각(tc_)도 그대로 나간다. 하네스 조각은 두뇌 조각 뒤, finish-step 앞
    kinds = [c["type"] for c in chunks]
    assert [c["toolName"] for c in chunks if c.get("toolCallId", "").startswith("tc_")
            and c["type"] == "tool-input-available"] == ["add_milestone", "add_milestone"]
    assert chunks.index(harness[1]) < kinds.index("finish-step") < kinds.index("data-activity")


async def test_app_chapter_draft_chunk_after_milestone(tmp_path):
    propose_task = ("propose_tasks", {"tasks": [{"title": "꾸민 산책", "areas": ["health"]}]})
    chapter = ("propose_chapter", {"title": "꾸민 시절", "start": "2019-03", "end": "2020-12"})
    add = ("add_milestone", {"date": "2019", "kind": "turning_point", "title": "꾸민 결심"})
    script = [FakeTurn([propose_task, chapter, add], "정리해 볼게요.")]
    async with BeEnv.start(tmp_path, start=SAT_1300, script=script) as env:
        _, raw = await env.chat("올해를 돌아보자")
        cid = env.conn.execute("SELECT id FROM curve_chapters").fetchone()[0]
        mid = env.conn.execute("SELECT id FROM curve_milestones").fetchone()[0]
    harness = _harness(parse_sse(raw))

    outputs = [c for c in harness if c["type"] == "tool-output-available"]
    assert [c["toolCallId"] for c in outputs] == ["h_draft_1", "h_mdraft_2", "h_cdraft_3"]  # 할 일 → 사건 → 챕터
    inputs = {c["toolCallId"]: c for c in harness if c["type"] == "tool-input-available"}
    assert inputs["h_mdraft_2"]["input"] == {"milestone_ids": [mid]}
    assert inputs["h_cdraft_3"]["toolName"] == "ui_chapter_draft"
    assert inputs["h_cdraft_3"]["input"] == {"chapter_ids": [cid]}
    assert outputs[2]["output"] == {"ok": True, "data": {"chapters": [
        {"id": cid, "title": "꾸민 시절", "start_month": "2019-03", "end_month": "2020-12"},
    ]}}


async def test_app_draft_settled_in_same_turn_has_no_card(tmp_path):
    add = ("add_milestone", {"date": "2019", "kind": "high", "title": "꾸민 여행"})
    script = [FakeTurn([add], "곡선에 남길까요?"), FakeTurn([("confirm_milestones", {"ids": [1]})], "남겼어요.")]
    async with BeEnv.start(tmp_path, start=SAT_1300, script=script) as env:
        await env.chat("꾸민 여행이 좋았어")
        _, raw = await env.chat("응 저장해")
    chunks = parse_sse(raw)

    assert _harness(chunks) == []
    (act,) = [c for c in chunks if c["type"] == "data-activity"]
    assert act["data"]["confirmation"] == "✓ 저장: 꾸민 여행 (2019, 높은 때)\n칭호: 「꾸민 여행」의 순간"


async def test_checkin_cards_include_curve_drafts_until_confirmed(tmp_path):
    add_a = ("add_milestone", {"date": "2019", "kind": "high", "title": "꾸민 하나"})
    add_b = ("add_milestone", {"date": "2020", "kind": "low", "title": "꾸민 둘"})
    chapter = ("propose_chapter", {"title": "꾸민 시절", "start": "2019-01"})
    propose = ("propose_tasks", {"tasks": [{"title": "꾸민 산책", "areas": ["health"]}]})
    script = [FakeTurn([propose, add_a, add_b, chapter], "좋은 아침이에요")]
    async with BeEnv.start(tmp_path, start=kst(2026, 10, 24, 10, 0) + timedelta(seconds=30), script=script) as env:
        await env.tick()
        (item,) = (await (await env.get("/checkins?date=2026-10-24")).json())["items"]
        rid = item["id"]
        first = (await (await env.get(f"/checkins/{rid}")).json())["cards"]
        ms = first[1]["props"]["milestone_ids"]
        code, _ = await env.action("confirm_milestones", {"ids": [ms[0]]})
        second = (await (await env.get(f"/checkins/{rid}")).json())["cards"]
        await env.action("drop_milestone", {"id": ms[1]})
        await env.action("confirm_chapters", {"ids": first[2]["props"]["chapter_ids"]})
        third = (await (await env.get(f"/checkins/{rid}")).json())["cards"]

    assert [(c["toolCallId"], c["component"]) for c in first] == [
        (f"h_draft_{rid}", "ui_todo_draft"), (f"h_mdraft_{rid}", "ui_milestone_draft"),
        (f"h_cdraft_{rid}", "ui_chapter_draft"), (f"h_cond_{rid}", "ui_condition_picker"),  # 텔레그램 줄 순서
    ]
    assert [m["title"] for m in first[1]["data"]["milestones"]] == ["꾸민 하나", "꾸민 둘"]
    assert first[2]["data"]["chapters"][0] == {
        "id": first[2]["props"]["chapter_ids"][0], "title": "꾸민 시절", "start_month": "2019-01", "end_month": None,
    }
    assert code == 200
    assert second[1]["props"] == {"milestone_ids": [ms[1]]}
    assert [c["component"] for c in third] == ["ui_todo_draft", "ui_condition_picker"]  # 남은 사건·챕터 초안이 없으면 카드도 없다
