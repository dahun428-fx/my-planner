"""답할 회차 `GET /checkins`, `GET /checkins/{id}` (SP3-4 스펙 6.4.5): 통로별 대화 id, 보낸 시각 기준 상태.

가짜 두뇌 + 가짜 시계(`BeEnv`). 날짜는 2026-10-26(월). 내용은 모두 꾸며 낸 것이다.
"""

from datetime import date, timedelta

from be_env import BeEnv
from fakes import FakeTurn
from test_dispatcher_messages import kst
from ui_stream import parse_sse


async def get_json(env, path):
    resp = await env.get(path)
    assert resp.status == 200, await resp.text()
    return await resp.json()


def by_loop(listing, loop):
    (item,) = [i for i in listing["items"] if i["loop"] == loop]
    return item


async def test_checkin_detail_conversation_ids_per_channel(tmp_path):
    script = [FakeTurn([], "꾸민 저녁 체크인", session_id="s-run"), FakeTurn([], "앱 답", session_id="s-fork")]
    async with BeEnv.start(tmp_path, start=kst(2026, 10, 26, 17, 30) + timedelta(seconds=30), script=script) as env:
        await env.tick()
        tele_id = env.brain.calls[0]["run_ctx"].conversation_id
        run_id = env.conn.execute("SELECT id FROM runs WHERE loop = 'evening_checkin'").fetchone()["id"]
        before = await get_json(env, f"/checkins/{run_id}")
        env.clock.set(kst(2026, 10, 26, 18, 0))
        _, raw = await env.chat("꾸민 앱 답", checkin_id=run_id)
        app_id = parse_sse(raw)[0]["messageMetadata"]["conversation_id"]
        after = await get_json(env, f"/checkins/{run_id}")
        listed = by_loop(await get_json(env, "/checkins?date=2026-10-26"), "evening_checkin")

    assert before["conversation_ids"] == {"telegram": tele_id, "app": None}
    assert after["conversation_ids"] == {"telegram": tele_id, "app": app_id}
    assert listed["conversation_ids"] == after["conversation_ids"]
    assert (after["state"], after["answered_via"], after["answered_at"]) == ("answered", "app", "2026-10-26T09:00:00Z")
    assert after["delivered_via"] == ["telegram"]


async def test_states_pending_answered_missed_by_sent_time(tmp_path):
    script = [FakeTurn([], "꾸민 아침"), FakeTurn([], "늦게 받은 답"), FakeTurn([], "꾸민 저녁")]
    async with BeEnv.start(tmp_path, start=kst(2026, 10, 26, 9, 0) + timedelta(seconds=30), script=script) as env:
        await env.tick()  # 아침 브리핑(답장 창 12:00까지)
        env.clock.set(kst(2026, 10, 26, 11, 0))
        morning_pending = by_loop(await get_json(env, "/checkins"), "morning_brief")
        # 11:59에 보낸 답을 12:30에 받는다: 보낸 시각이 창 안이라 답이다
        env.clock.set(kst(2026, 10, 26, 12, 30))
        await env.telegram("꾸민 아침 답", sent_at=kst(2026, 10, 26, 11, 59))
        morning_answered = by_loop(await get_json(env, "/checkins"), "morning_brief")
        env.clock.set(kst(2026, 10, 26, 17, 30) + timedelta(seconds=30))
        await env.tick()  # 저녁 체크인(답장 창 10/27 04:00까지)
        env.clock.set(kst(2026, 10, 27, 3, 59))
        evening_pending = by_loop(await get_json(env, "/checkins?date=2026-10-26"), "evening_checkin")
        env.clock.set(kst(2026, 10, 27, 4, 1))
        listing = await get_json(env, "/checkins?date=2026-10-26")

    assert morning_pending["state"] == "pending" and morning_pending["answered_at"] is None
    assert (morning_answered["state"], morning_answered["answered_via"]) == ("answered", "telegram")
    assert morning_answered["answered_at"] == "2026-10-26T02:59:00Z"  # 보낸 시각
    assert evening_pending["state"] == "pending"
    assert by_loop(listing, "evening_checkin")["state"] == "missed"
    assert by_loop(listing, "morning_brief")["state"] == "answered"  # 창이 끝나도 답한 회차는 그대로


# --- SP7-06: 체크인 카드의 습관 ---


def _add_habit(env, title, kind="daily", target=None):
    return env.parts.habits.add(title, "health", kind, target, env.clock.now())


async def test_checkin_cards_habit_card_order(tmp_path):
    """저녁 체크인: ui_confirm 뒤, ui_condition_picker 앞(텔레그램 버튼 줄 순서). 이미 다 체크해도 카드는 남는다."""
    script = [FakeTurn([("propose_tasks", {"tasks": [{"title": "저녁 스트레칭", "areas": ["health"]}]})], "오늘 어떠셨어요?")]
    async with BeEnv.start(tmp_path, start=kst(2026, 10, 24, 18, 0) + timedelta(seconds=30), script=script) as env:
        run_hab = _add_habit(env, "꾸민 운동")
        paused = _add_habit(env, "쉬는 습관")
        env.parts.habits.set_status(paused.id, "paused", env.clock.now())
        await env.tick()
        run_id = env.conn.execute("SELECT id FROM runs WHERE loop = 'evening_checkin'").fetchone()["id"]
        detail = await get_json(env, f"/checkins/{run_id}")
        comps = [c["component"] for c in detail["cards"]]
        assert comps == ["ui_todo_draft", "ui_habit_check", "ui_condition_picker"]
        card = detail["cards"][1]
        assert card["toolCallId"] == f"h_habit_{run_id}" and card["props"] == {"date": "2026-10-24"}
        assert [h["title"] for h in card["data"]["habits"]] == ["꾸민 운동"]
        assert card["data"]["habits"][0]["checked"] is False
        env.parts.habits.check(run_hab.id, date(2026, 10, 24), env.clock.now())
        again = (await get_json(env, f"/checkins/{run_id}"))["cards"][1]
        assert again["data"]["habits"][0]["checked"] is True and again["data"]["habits"][0]["week_count"] == 1
        env.parts.conditions.upsert(date(2026, 10, 24), 4, None)
        after = await get_json(env, f"/checkins/{run_id}")
        assert [c["component"] for c in after["cards"]] == ["ui_todo_draft", "ui_habit_check"]


async def test_checkin_cards_no_habit_card_without_habits(tmp_path):
    script = [FakeTurn([], "꾸민 저녁")]
    async with BeEnv.start(tmp_path, start=kst(2026, 10, 24, 18, 0) + timedelta(seconds=30), script=script) as env:
        paused = _add_habit(env, "쉬는 습관")
        env.parts.habits.set_status(paused.id, "paused", env.clock.now())
        await env.tick()
        run_id = env.conn.execute("SELECT id FROM runs WHERE loop = 'evening_checkin'").fetchone()["id"]
        detail = await get_json(env, f"/checkins/{run_id}")
        assert [c["component"] for c in detail["cards"]] == ["ui_condition_picker"]  # 활성 습관이 없다
