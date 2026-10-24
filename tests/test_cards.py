"""고정 카드: `CardsRepo`, 카드 도구 `pin_card`·`unpin_card`·`reorder_cards`, `GET /today.cards` (SP3-4 스펙 5.3, 6.3.2,
6.4.2, 6.4.3, 10장). 내용은 꾸며 낸 것이다.
"""

import pytest
from be_env import BeEnv
from test_api_undo import undo
from test_dispatcher_messages import kst
from test_tools_tasks import ToolEnv

from my_planner.domain import RunContext
from my_planner.store.repos.cards import CardsRepo

START = kst(2026, 10, 24, 13, 0)
SUMMARY = {"title": "꾸민 요약", "lines": ["한 줄"]}


def _app(conv=1):
    return RunContext(conversation_id=conv, run_id=None, events=[], channel="app")


@pytest.fixture
def cenv(tmp_path, conn):
    env = ToolEnv(tmp_path, conn)
    env.cards = CardsRepo(conn, env.clock)
    env.tools.cards = env.cards
    return env


def test_pin_card_validates_against_its_own_component(cenv):
    tools = cenv.tools
    wrong = tools.pin_card(_app(), component="ui_summary_card", props={"title": "목록", "task_ids": [1]})
    harness = tools.pin_card(_app(), component="ui_todo_draft", props={"task_ids": [1]})
    unknown = tools.pin_card(_app(), component="ui_nope", props={})
    not_obj = tools.pin_card(_app(), component="ui_todo_list", props=["x"])
    assert all("error" in o for o in (wrong, harness, unknown, not_obj))
    assert cenv.cards.active() == []

    ok = tools.pin_card(_app(conv=5), component="ui_todo_list", props={"title": "목록", "task_ids": [1]})
    assert "error" not in ok
    (card,) = cenv.cards.active()
    assert (card.id, card.component, card.props, card.sort_order, card.conversation_id) == (
        ok["id"], "ui_todo_list", {"title": "목록", "task_ids": [1]}, 1, 5)
    assert ok["order"] == 1


def test_reorder_requires_all_pinned_ids(cenv):
    tools = cenv.tools
    a, b, c = (tools.pin_card(_app(), component="ui_summary_card", props=SUMMARY)["id"] for _ in range(3))
    for bad in ([a, b], [a, b, c, c], [a, b, c, 99], []):
        with pytest.raises(ValueError):
            cenv.cards.reorder(bad)
        assert "error" in tools.reorder_cards(_app(), ids=bad)
    assert "error" in tools.reorder_cards(_app(), ids="1,2,3")
    assert cenv.cards.order() == [a, b, c]

    assert tools.reorder_cards(_app(), ids=[c, a, b]) == {"ids": [c, a, b]}
    assert cenv.cards.order() == [c, a, b]
    assert [x.sort_order for x in cenv.cards.active()] == [1, 2, 3]
    tools.unpin_card(_app(), id=a)
    assert "error" in tools.reorder_cards(_app(), ids=[c, a, b])  # 고정을 푼 카드는 순서에 없다
    assert "error" in tools.unpin_card(_app(), id=a)  # 이미 풀었다
    assert tools.reorder_cards(_app(), ids=[b, c]) == {"ids": [b, c]}


async def test_card_activity_actor_secretary_and_undo_each(tmp_path):
    async with BeEnv.start(tmp_path, start=START) as env:
        tools = env.parts.tools
        a = tools.pin_card(_app(), component="ui_summary_card", props=SUMMARY)["id"]
        b = tools.pin_card(_app(), component="ui_choice", props={
            "question": "어느 쪽?", "options": [{"id": "x", "label": "가"}, {"id": "y", "label": "나"}]})["id"]
        tools.reorder_cards(_app(), ids=[b, a])
        tools.unpin_card(_app(), id=a)
        rows = [(r["kind"], r["actor"], r["channel"], r["target"], r["risk"]) for r in env.activity()]
        ids = [r["id"] for r in env.activity()]
        order = env.parts.tools.cards.order

        steps = []
        for aid in reversed(ids):  # 나중 것부터 하나씩 되돌린다
            status, body = await undo(env, aid)
            steps.append((status, body.get("status") or body["error"]["code"], body.get("confirmation"), order()))
        today = await (await env.get("/today")).json()

    assert rows == [
        ("card_pinned", "secretary", "app", f"card:{a}", "low"),
        ("card_pinned", "secretary", "app", f"card:{b}", "low"),
        ("cards_reordered", "secretary", "app", "cards:order", "low"),
        ("card_unpinned", "secretary", "app", f"card:{a}", "low"),
    ]
    assert steps == [
        (200, "undone", "↩ 되돌림: 꾸민 요약 카드 고정 해제", [b, a]),
        (200, "undone", "↩ 되돌림: 카드 순서 바꿈", [a, b]),
        (200, "undone", "↩ 되돌림: 어느 쪽? 카드 고정", [a]),
        # 고정 해제를 되돌린 활동이 그 카드를 나중에 바꿨다(U3): 고정은 되돌릴 수 없다
        (409, "superseded", None, [a]),
    ]
    assert [c["id"] for c in today["cards"]] == [a]


async def test_card_undo_superseded_and_order_merge(tmp_path):
    """고정 뒤 고정을 풀면 고정 되돌리기는 막힌다(U3, 대상 `card:<id>`). 순서 되돌리기는 그 뒤에 고정한 카드를 맨 뒤에 둔다."""
    async with BeEnv.start(tmp_path, start=START) as env:
        tools = env.parts.tools
        a = tools.pin_card(_app(), component="ui_summary_card", props=SUMMARY)["id"]
        b = tools.pin_card(_app(), component="ui_summary_card", props=SUMMARY)["id"]
        tools.reorder_cards(_app(), ids=[b, a])
        reorder_id = env.activity()[-1]["id"]
        c = tools.pin_card(_app(), component="ui_summary_card", props=SUMMARY)["id"]
        tools.unpin_card(_app(), id=b)
        pin_b = env.activity()[1]["id"]
        blocked = await undo(env, pin_b)
        done = await undo(env, reorder_id)
        order = tools.cards.order()

    assert blocked[0] == 409 and blocked[1]["error"]["code"] == "superseded"
    assert done[1]["status"] == "undone"
    assert order == [a, c]


async def test_cards_from_actions_are_user(tmp_path):
    async with BeEnv.start(tmp_path, start=START) as env:
        status, body = await env.action("pin_card", {"component": "ui_summary_card", "props": SUMMARY})
        bad = await env.action("pin_card", {"component": "ui_summary_card", "props": {"title": "x"}})
        cid = body["result"]["id"]
        moved = await env.action("reorder_cards", {"ids": [cid]})
        off = await env.action("unpin_card", {"id": cid})
        rows = [(r["kind"], r["actor"], r["channel"]) for r in env.activity()]

    assert status == 200 and body["status"] == "applied" and body["undo_id"] == body["activity_id"]
    assert body["confirmation"] == "✓ 카드 고정: 꾸민 요약"
    assert bad[0] == 422 and bad[1]["status"] == "rejected"
    assert moved[0] == 200 and off[0] == 200
    assert rows == [("card_pinned", "user", "app"), ("cards_reordered", "user", "app"),
                    ("card_unpinned", "user", "app")]


async def test_today_cards_filled_with_current_task_data(tmp_path):
    async with BeEnv.start(tmp_path, start=START) as env:
        tools = env.parts.tools
        ctx = _app()
        a = tools.add_task(ctx, title="꾸민 하나", areas=["health"])["id"]
        b = tools.add_task(ctx, title="꾸민 둘", areas=["finance"])["id"]
        d = tools.propose_tasks(ctx, tasks=[{"title": "꾸민 초안", "areas": ["health"]}])["proposed"][0]["id"]
        gone = tools.add_task(ctx, title="꾸민 삭제", areas=["health"])["id"]
        tools.set_priorities(ctx, cadence="week", period="2026-W43", task_ids=[b])
        summary = tools.pin_card(ctx, component="ui_summary_card", props=SUMMARY)["id"]
        listed = tools.pin_card(ctx, component="ui_todo_list", props={"title": "목록", "task_ids": [b, d, gone, a]})
        tools.reorder_cards(ctx, ids=[listed["id"], summary])
        # 고정한 뒤에 바뀐 값이 보인다(카드가 낡지 않게)
        tools.update_task(ctx, id=a, title="꾸민 하나(바뀜)")
        tools.drop_task(ctx, id=b)
        undo_add = [r["id"] for r in env.activity() if r["kind"] == "task_added" and r["target"] == f"task:{gone}"]
        await undo(env, undo_add[0])  # 소프트 삭제
        today = await (await env.get("/today")).json()

    first, second = today["cards"]
    assert (first["id"], first["component"], first["order"]) == (listed["id"], "ui_todo_list", 1)
    assert first["props"] == {"title": "목록", "task_ids": [b, d, gone, a]}
    assert first["pinned_at"].endswith("Z")
    assert first["data"] == {"todos": [
        {"id": b, "title": "꾸민 둘", "cadence": None, "area": "finance", "status": "dropped"},
        {"id": a, "title": "꾸민 하나(바뀜)", "cadence": None, "area": "health", "status": "open"},
    ]}
    assert (second["id"], second["order"], second["props"]) == (summary, 2, SUMMARY)
    assert second.get("data") is None


PIN = ("pin_card", {"component": "ui_summary_card", "props": SUMMARY})


async def test_pin_card_then_brain_error_is_not_retried(tmp_path):
    """고정한 뒤 두뇌가 오류로 끝나도 다시 부르지 않는다(중복 쓰기 방지, 스펙 5.4-3): 카드는 한 장."""
    from fakes import FakeTurn
    from ui_stream import parse_sse

    script = [FakeTurn([PIN], "", status="error", error="boom"), FakeTurn([PIN], "고정했어요.")]
    async with BeEnv.start(tmp_path, start=START, script=script) as env:
        _, raw = await env.chat("요약 고정해 줘")
        calls = len(env.brain.calls)
        today = await (await env.get("/today")).json()
        kinds = [r["kind"] for r in env.activity()]
        logged = [r["kind"] for r in env.conn.execute("SELECT kind FROM tool_events_log ORDER BY id")]

    assert calls == 1
    assert len(today["cards"]) == 1 and kinds == ["card_pinned"] and logged == ["card_pinned"]
    (activity,) = [c for c in parse_sse(raw) if c["type"] == "data-activity"]
    assert activity["data"]["confirmation"] == "✓ 카드 고정: 꾸민 요약"


async def test_requeued_after_restart_does_not_pin_twice(tmp_path, conn, state):
    """두뇌 호출 도중 멈춘 뒤 다시 넣은 행은 기록된 도구 호출을 보고 두뇌를 다시 부르지 않는다: 카드는 한 장."""
    import asyncio
    from datetime import timedelta

    from fakes import FakeTurn
    from test_dispatcher_messages import Env
    from test_inbound_recovery import _kill, _receive

    from my_planner.loop.runner import resubmit_inbound

    first = Env(tmp_path, conn, state, script=[FakeTurn([PIN], "", hang=True)], start=START, with_tools=True)
    first.tools.cards = CardsRepo(conn, first.clock)
    first.dispatcher.start()
    await _receive(first, state, 44, "요약 고정해 줘")
    while not first.brain.calls:
        await asyncio.sleep(0)
    await _kill(first)

    second = Env(tmp_path, conn, state, script=[], start=START + timedelta(minutes=5), with_tools=True)
    second.tools.cards = CardsRepo(conn, second.clock)
    assert resubmit_inbound(state, second.dispatcher) == 1
    await second.process()

    assert second.brain.calls == []
    assert len(second.tools.cards.active()) == 1
    assert second.sender.sent[-1].text.endswith("✓ 카드 고정: 꾸민 요약")
    assert state.pending_inbound() == []


async def test_reorder_cards_rejects_empty_list(tmp_path):
    async with BeEnv.start(tmp_path, start=START) as env:
        status, body = await env.action("reorder_cards", {"ids": []})
        rows = env.activity()

    assert status == 422 and body["status"] == "rejected"
    assert rows == []
