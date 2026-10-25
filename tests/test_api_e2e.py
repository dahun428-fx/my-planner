"""API 수용 시험 (가짜 두뇌 + 가짜 시계, `BeEnv`)."""

from datetime import timedelta

import pytest
from be_env import BeEnv
from fakes import FakeTurn
from test_dispatcher_messages import kst


async def test_health_after_morning_brief(tmp_path):
    # 토요일(주말 아침 10:00) 10:00:30
    async with BeEnv.start(
        tmp_path, start=kst(2026, 10, 24, 10, 0) + timedelta(seconds=30), script=[FakeTurn([], "좋은 아침이에요")]
    ) as env:
        await env.tick()
        resp = await env.get("/health")
        assert resp.status == 200
        body = await resp.json()

    run = body["runs_today"][0]
    assert run["loop"] == "morning_brief"
    assert run["status"] == "done"
    assert run["delivered_via"] == ["telegram"]
    assert run["checkin_state"] == "pending"
    assert run["scheduled_for"] == "2026-10-24T01:00:00Z"
    assert body["proactive"]["sent_today"] == 1
    assert body["brain"]["calls_today"] == 1
    assert body["brain"]["auth"] == "ok"
    assert body["notify"] == {"primary": "app", "effective": "telegram"}
    assert body["status"] == "ok"


async def test_today_after_chat_and_checkin(tmp_path):
    # 월요일 09:00:30. 낮에 텔레그램으로 일정을 넣고, 저녁 체크인이 초안 둘을 제안한다
    add = ("add_task", {"title": "치과", "areas": ["health"], "planned_for": "2026-10-27",
                        "scheduled_at": "2026-10-27T14:00:00+09:00"})
    propose = ("propose_tasks", {"tasks": [{"title": "물 마시기", "areas": ["health"]},
                                           {"title": "스트레칭", "areas": ["health"]}]})
    script = [FakeTurn([add], "치과 넣었어요"), FakeTurn([propose], "오늘 어떠셨어요?")]
    async with BeEnv.start(tmp_path, start=kst(2026, 10, 26, 9, 0) + timedelta(seconds=30), script=script) as env:
        env.clock.set(kst(2026, 10, 26, 13, 0))
        await env.telegram("내일 2시 치과")
        env.clock.set(kst(2026, 10, 26, 17, 30) + timedelta(seconds=30))
        await env.tick()

        # 바로(10/26 밤): 그 체크인은 pending이고 상세에 카드 둘(초안, 컨디션)
        listing = await (await env.get("/checkins?date=2026-10-26")).json()
        (item,) = [i for i in listing["items"] if i["loop"] == "evening_checkin"]
        assert item["state"] == "pending"
        detail = await (await env.get(f"/checkins/{item['id']}")).json()
        assert len(detail["cards"]) == 2
        assert [t["title"] for t in detail["cards"][0]["data"]["todos"]] == ["물 마시기", "스트레칭"]

        # 10/27 09:00: 답장 창은 04:00에 끝났다
        env.clock.set(kst(2026, 10, 27, 9, 0))
        today = await (await env.get("/today")).json()
        after = await (await env.get(f"/checkins/{item['id']}")).json()

    assert today["date"] == "2026-10-27"
    (dentist,) = [x for x in today["todos"] if x["todo"]["title"] == "치과"]
    assert dentist["group"] == "scheduled" and dentist["todo"]["scheduled_at"] == "2026-10-27T05:00:00Z"
    assert after["state"] == "missed"
    assert "물 마시기" not in str(today["todos"])  # 초안은 오늘 목록에 없다


async def test_curve_and_status_read_model(tmp_path):
    from curve_sql import area_scores, ladder

    # 토요일 낮에 텔레그램으로 할 일을 만들고 이번 분기 우선순위로 올린다(가짜 두뇌)
    add = ("add_task", {"title": "수채화 전시 준비", "areas": ["learning"]})
    prio = ("set_priorities", {"cadence": "quarter", "period": "2026-Q4", "task_ids": [1]})
    script = [FakeTurn([add, prio], "분기 목표로 올렸어요")]
    async with BeEnv.start(tmp_path, start=kst(2026, 10, 24, 13, 0), script=script) as env:
        await env.telegram("수채화 전시 준비를 이번 분기 목표로")
        c = env.conn
        ladder(c, "2026-10", now=6, future=8)
        for d in range(1, 11):  # 평균 3.4, 10일
            c.execute(
                "INSERT INTO conditions (date, score, note, recorded_at) VALUES (?, ?, NULL, ?)",
                (f"2026-10-{d:02d}", (3, 3, 4, 4, 3, 4, 3, 4, 3, 3)[d - 1], "2026-10-11T00:00:00.000000+00:00"),
            )
        area_scores(c, "2026-Q3", health=6, career=5)
        area_scores(c, "2026-Q4", health=4, career=5)
        c.commit()
        curve = await (await env.get("/curve?zoom=quarter")).json()
        status = await (await env.get("/status")).json()

    assert curve["areas"] == [
        {"period": "2026-Q3", "scores": {"health": 6, "career": 5}},
        {"period": "2026-Q4", "scores": {"health": 4, "career": 5}},
    ]
    assert curve["reassurance"] == [
        {"period": "2026-10", "ladder_now": 6, "condition_average": 3.4, "condition_scaled": 6.0,
         "days_logged": 10, "gap": 0.0}
    ]
    assert status["main_quests"][0]["title"] == "수채화 전시 준비"
    assert (status["level"], status["xp_total"]) == (1, 0)
    assert next(s for s in status["stats"] if s["area"] == "health")["debuff"] is True


async def test_actions_end_to_end(tmp_path):
    # 토요일 낮: 텔레그램으로 할 일을 넣고(가짜 두뇌), 앱에서 완료한다(즉시 갈래)
    add = ("add_task", {"title": "운동", "areas": ["health"], "planned_for": "2026-10-24"})
    async with BeEnv.start(tmp_path, start=kst(2026, 10, 24, 13, 0), script=[FakeTurn([add], "넣었어요")]) as env:
        await env.telegram("운동 추가")
        before = await (await env.get("/today")).json()
        (todo,) = [x["todo"] for x in before["todos"]]
        assert todo["title"] == "운동"
        await env.telegram("/today")
        assert "운동" in env.bot.sent[-1][1]

        status, body = await env.action("complete_task", {"id": todo["id"]}, client_msg_id="e2e-1")
        again = await env.action("complete_task", {"id": todo["id"]}, client_msg_id="e2e-1")
        await env.telegram("/today")
        today_text = env.bot.sent[-1][1]
        after = await (await env.get("/today")).json()
        rows = [(r["kind"], r["actor"], r["channel"]) for r in env.activity()]

    assert status == 200 and body["status"] == "applied" and body["confirmation"] == "✓ 완료: 운동"
    assert again == (status, body)
    assert "운동" not in today_text
    assert after["todos"] == []
    assert rows == [("task_added", "secretary", "telegram"), ("task_completed", "user", "app")]


async def test_undo_end_to_end(tmp_path):
    # 토요일 낮: 앱에서 할 일을 넣고, 텔레그램 대화에서 비서(가짜 두뇌)가 완료하고, 앱에서 되돌린다
    async with BeEnv.start(tmp_path, start=kst(2026, 10, 24, 13, 0)) as env:
        _, added = await env.action("add_task", {"title": "운동", "areas": ["health"], "planned_for": "2026-10-24"})
        tid = added["result"]["id"]
        env.brain.script.append(FakeTurn([("complete_task", {"id": tid})], "완료했어요"))
        await env.telegram("운동 다 했어요")
        listing = await (await env.get("/activity?order=desc")).json()
        done = listing["items"][0]
        mid = await (await env.get("/today")).json()

        env.clock.advance(minutes=10)
        resp = await env.post(f"/activity/{done['undo_id']}/undo", json={"client_msg_id": "e2e-undo"})
        body = await resp.json()
        today = await (await env.get("/today")).json()
        await env.telegram("/today")
        today_text = env.bot.sent[-1][1]
        again = await env.post(f"/activity/{done['undo_id']}/undo", json={"client_msg_id": "e2e-undo"})
        again_body = await again.json()
        after = await (await env.get("/activity")).json()

    assert (done["kind"], done["actor"], done["channel"]) == ("task_completed", "secretary", "telegram")
    assert done["undo_id"] == done["id"] and mid["todos"] == []
    assert resp.status == 200 and body["status"] == "undone" and body["confirmation"] == "↩ 되돌림: 운동 완료"
    assert [x["todo"]["title"] for x in today["todos"]] == ["운동"]
    assert today["todos"][0]["todo"]["status"] == "open"
    assert "운동" in today_text
    assert again.status == 200 and again_body == {"status": "already_undone", "activity_id": body["activity_id"]}
    assert [(i["kind"], i["actor"], i["channel"]) for i in after["items"]] == [
        ("task_added", "user", "app"), ("task_completed", "secretary", "telegram"), ("undo", "user", "app")]


@pytest.mark.parametrize("deltas", [None, ["내일 치과를 ", "추가할게요."]])
async def test_chat_end_to_end(tmp_path, deltas):
    """앱 채팅(SP3-4 티켓 06): `POST /chat` → 대화 기록 → 다음 날 텔레그램 `/today`에 같은 할 일."""
    from ui_stream import parse_sse

    add = ("add_task", {"title": "치과", "areas": ["health"], "planned_for": "2026-10-25"})
    async with BeEnv.start(tmp_path, start=kst(2026, 10, 24, 13, 0), script=[FakeTurn([add], "내일 치과를 추가할게요.", deltas=deltas)]) as env:
        resp, raw = await env.chat("내일 치과 추가해 줘", message_id="msg-e2e")
        chunks = parse_sse(raw)
        conv_id = int(resp.headers["x-conversation-id"])
        listing = await (await env.get("/conversations?channel=app")).json()
        messages = await (await env.get(f"/conversations/{conv_id}/messages")).json()

        env.clock.set(kst(2026, 10, 25, 9, 0))
        await env.telegram("/today")
        today_reply = env.bot.sent[-1][1]

    assert [c["id"] for c in listing["items"]] == [conv_id]
    assert listing["items"][0]["channel"] == "app"
    items = messages["items"]
    assert [(m["speaker"], m["channel"]) for m in items] == [("user", "app"), ("secretary", "app")]
    assert items[0]["id"] == "msg-e2e"
    assert items[1]["id"] == chunks[0]["messageId"]  # 비서 줄의 id는 그 답의 start.messageId(6.4.6)
    assert items[1]["tools"] == ["add_task"]
    assert "치과" in today_reply


async def test_answer_from_app_closes_telegram(tmp_path):
    # 10/26(월) 17:30 저녁 체크인이 텔레그램으로 간다(컨디션 버튼). 18:00 앱의 체크인 화면에서 답한다
    script = [FakeTurn([], "오늘 하루 어떠셨어요?", session_id="s-run"), FakeTurn([], "앱에서 이어 가요", session_id="s-app")]
    async with BeEnv.start(tmp_path, start=kst(2026, 10, 26, 17, 30) + timedelta(seconds=30), script=script) as env:
        await env.tick()
        (message_id,) = [m for m in env.sender.message_ids if m is not None]
        listing = await (await env.get("/checkins?date=2026-10-26")).json()
        (item,) = [i for i in listing["items"] if i["loop"] == "evening_checkin"]
        env.clock.set(kst(2026, 10, 26, 18, 0))
        resp, _ = await env.chat("꾸민 앱 답", checkin_id=item["id"])
        detail = await (await env.get(f"/checkins/{item['id']}")).json()

    assert resp.status == 200
    assert (detail["state"], detail["answered_via"]) == ("answered", "app")
    assert env.sender.cleared == [message_id]
    second = env.brain.calls[1]
    assert (second["session_id"], second["fork_session"]) == ("s-run", True)


async def test_push_delivery_and_fallback(tmp_path):
    """웹 푸시 전달과 텔레그램 대체(SP3-4 티켓 08, 7.3 D1a~D6). 구독 주소는 꾸며 낸 값이다."""
    from fakes import FakePushSender
    from test_delivery import tick_at

    from my_planner.store.repos.push import PushRepo

    ep = "https://push.example.invalid/sub/e2e-fake"
    push = FakePushSender()
    script = [FakeTurn([], "좋은 아침이에요"), FakeTurn([], "오늘 하루 어떠셨어요?"), FakeTurn([], "일요일 아침이에요")]
    async with BeEnv.start(tmp_path, start=kst(2026, 10, 24, 9, 0), script=script, push=push) as env:
        # 10/24(토): 운영 앱이 구독한다 → 10:00 아침 브리핑은 푸시로만
        await env.subscribe(ep)
        await tick_at(env, kst(2026, 10, 24, 10, 0) + timedelta(seconds=30))
        morning = await (await env.get("/health")).json()
        pushes_after_morning, telegram_after_morning = len(push.sent), len(env.sender.sent)

        # 구독이 만료됐다(410) → 18:00 저녁 체크인은 텔레그램으로, 구독은 꺼진다
        push.always(ep, 410)
        await tick_at(env, kst(2026, 10, 24, 18, 0) + timedelta(seconds=30))
        evening = await (await env.get("/health")).json()
        active = PushRepo(env.conn).count_active()
        pushes_after_evening = len(push.sent)

        # 10/25(일) 10:00: 처음부터 텔레그램(푸시는 해 보지도 않는다)
        await tick_at(env, kst(2026, 10, 25, 10, 0) + timedelta(seconds=30))
        sunday = await (await env.get("/health")).json()

    assert (pushes_after_morning, telegram_after_morning) == (1, 0)
    assert morning["proactive"]["sent_today"] == 1
    assert morning["runs_today"][0]["delivered_via"] == ["app"]
    assert morning["notify"] == {"primary": "app", "effective": "app"}

    assert pushes_after_evening == 2  # 410은 다시 보내지 않는다
    assert [o.text for o in env.sender.sent[:1]] == ["오늘 하루 어떠셨어요?"]
    (ev,) = [r for r in evening["runs_today"] if r["loop"] == "evening_checkin"]
    assert ev["delivered_via"] == ["telegram"]
    assert evening["proactive"]["sent_today"] == 2
    assert active == 0
    assert evening["notify"]["effective"] == "telegram"

    assert len(push.sent) == 2 and len(env.sender.sent) == 2
    assert sunday["notify"] == {"primary": "app", "effective": "telegram"}
    (sun,) = [r for r in sunday["runs_today"] if r["loop"] == "morning_brief"]
    assert sun["delivered_via"] == ["telegram"]


async def test_pin_card_from_app_chat(tmp_path):
    """앱 대화의 두뇌가 할 일 목록을 그리고 고정한다(SP3-4 티켓 09) → `/today.cards` → 되돌리면 카드가 없다."""
    from ui_stream import parse_sse

    add = ("add_task", {"title": "꾸민 산책", "areas": ["health"], "planned_for": "2026-10-24"})
    listing = ("ui_todo_list", {"title": "오늘 할 일", "task_ids": [1]})
    pin = ("pin_card", {"component": "ui_todo_list", "props": {"title": "오늘 할 일", "task_ids": [1]}})
    script = [FakeTurn([add], "넣었어요"), FakeTurn([listing, pin], "목록을 고정해 둘게요.")]
    async with BeEnv.start(tmp_path, start=kst(2026, 10, 24, 13, 0), script=script) as env:
        await env.chat("오늘 산책 추가해 줘")
        _, raw = await env.chat("오늘 할 일 목록 고정해 줘")
        chunks = parse_sse(raw)
        today = await (await env.get("/today")).json()
        (pinned,) = [r for r in env.activity() if r["kind"] == "card_pinned"]
        resp = await env.post(f"/activity/{pinned['id']}/undo", json={"client_msg_id": "e2e-card-undo"})
        after = await (await env.get("/today")).json()

    ui = [c for c in chunks if c.get("toolCallId") == "tc_01"]
    assert ui[0]["type"] == "tool-input-available" and ui[0]["toolName"] == "ui_todo_list"
    assert ui[1]["output"] == {"ok": True, "data": {"todos": [
        {"id": 1, "title": "꾸민 산책", "cadence": None, "area": "health", "status": "open",
         "planned_for": "2026-10-24", "scheduled_at": None}]}}
    (activity,) = [c for c in chunks if c["type"] == "data-activity"]
    assert activity["data"]["undo_ids"] == [pinned["id"]]
    (card,) = today["cards"]
    assert (card["component"], card["order"]) == ("ui_todo_list", 1)
    assert card["data"]["todos"][0]["title"] == "꾸민 산책"
    assert (pinned["actor"], pinned["channel"]) == ("secretary", "app")
    assert resp.status == 200
    assert after["cards"] == []


async def test_morning_brief_proposal_needs_confirm(tmp_path):
    """회차 차례의 확인(SP3-4 10.1): 아침 브리핑(가짜 두뇌)이 꺼낸 우선순위는 그대로이고, 앱이 체크인 상세의
    `ui_confirm` 카드 값으로 `/actions`에 보내면 바뀐다(활동 `actor = user`)."""
    # 10/26(월) 09:00 tick. 그 전에 앱으로 할 일 하나를 넣어 둔다(꾸며 낸 제목)
    async with BeEnv.start(tmp_path, start=kst(2026, 10, 26, 9, 0) + timedelta(seconds=30)) as env:
        _, added = await env.action("add_task", {"title": "꾸민 편지 쓰기", "areas": ["relationships"]})
        tid = added["result"]["id"]
        args = {"cadence": "day", "period": "2026-10-26", "task_ids": [tid]}
        env.brain.script.append(FakeTurn([("set_priorities", args)], "오늘은 편지 쓰기를 먼저 해 보면 어떨까요?"))
        await env.tick()
        run_id = env.conn.execute("SELECT id FROM runs WHERE loop = 'morning_brief'").fetchone()["id"]
        before = await (await env.get("/today")).json()
        assert env.conn.execute("SELECT COUNT(*) FROM priorities").fetchone()[0] == 0
        detail = await (await env.get(f"/checkins/{run_id}")).json()
        (card,) = [c for c in detail["cards"] if c["component"] == "ui_confirm"]
        p = card["props"]
        status, body = await env.action(p["action"], p["args"], confirm_token=p["confirm_token"])
        after = await (await env.get("/today")).json()
        rows = [(r["kind"], r["actor"], r["channel"], r["risk"]) for r in env.activity()]

    assert "priority" not in [x["group"] for x in before["todos"]]  # 그대로: 오늘 우선순위가 아니다
    assert card["toolCallId"] == f"h_confirm_{run_id}_1"
    assert (p["action"], p["args"]) == ("set_priorities", args)
    assert status == 200 and body["status"] == "applied"
    assert [(x["group"], x["todo"]["id"]) for x in after["todos"]] == [("priority", tid)]
    assert rows[-1] == ("priorities_set", "user", "app", "confirm")
    assert ("confirm_requested", "secretary", "scheduler", "low") in rows


async def test_curve_write_path(tmp_path):
    from my_planner.clock import to_iso
    from my_planner.store.repos.state import PAUSE_UNTIL_KEY

    # 토요일 낮: 대화에서 나온 사건 초안(고점)을 앱에서 확정하고, 되돌리고, 3일 뒤 하루 한 번 작업이 지운다
    async with BeEnv.start(tmp_path, start=kst(2026, 10, 24, 13, 0)) as env:
        mid = env.parts.curve.add_milestone(date_text="2019", kind="high", title="꾸민 여행", status="draft",
                                            origin="chat").id
        env.conn.commit()

        async def seen():
            curve = await (await env.get("/curve?zoom=year&from=2019-01-01&to=2026-12-31")).json()
            status = await (await env.get("/status")).json()
            return [m["title"] for m in curve["milestones"]], [t["title"] for t in status["titles"]]

        draft = await seen()
        code, body = await env.action("confirm_milestones", {"ids": [mid]})
        confirmed = await seen()
        resp = await env.post(f"/activity/{body['undo_id']}/undo", json={"client_msg_id": "e2e-curve-undo"})
        undone = await seen()
        still_draft = env.parts.curve.get_milestone(mid)

        # 3일 동안 회차는 쉬게 두고(가짜 두뇌 시나리오 없이) 하루 한 번 작업만 돌린다
        env.parts.state.set(PAUSE_UNTIL_KEY, to_iso(env.clock.now() + timedelta(days=30)))
        env.clock.advance(days=3)
        await env.tick()
        after = env.parts.curve.get_milestone(mid)
        expired = [r["kind"] for r in env.activity() if r["kind"] == "milestone_drafts_expired"]

    assert draft == ([], [])
    assert code == 200 and body["confirmation"] == "✓ 저장: 꾸민 여행 (2019, 고점)\n칭호: 「꾸민 여행」의 순간"
    assert confirmed == (["꾸민 여행"], ["「꾸민 여행」의 순간"])
    assert resp.status == 200
    assert undone == ([], [])
    assert still_draft is not None and still_draft.status == "draft"
    assert after is None
    assert expired == ["milestone_drafts_expired"]


async def test_seed_then_curve(tmp_path):
    """시드 가져오기(12장) → 같은 루트로 BE → `/curve`, `/status`. 고정 자료는 꾸며 낸 내용."""
    import io
    import json
    from pathlib import Path

    from my_planner.clock import FakeClock
    from my_planner.curve.seed import EXIT_OK, run_seed_life

    fixture = Path(__file__).parent / "fixtures" / "life_seed_example.json"
    seed = json.loads(fixture.read_text(encoding="utf-8"))
    start = kst(2026, 10, 24, 13, 0)
    out = io.StringIO()
    assert run_seed_life(tmp_path, fixture, dry_run=False, out=out, clock=FakeClock(start)) == EXIT_OK
    async with BeEnv.start(tmp_path, start=start) as env:
        curve = await (await env.get("/curve?zoom=year")).json()
        with_sensitive = await (await env.get("/curve?zoom=year&include_sensitive=true")).json()
        status = await (await env.get("/status")).json()

    assert [c["title"] for c in curve["chapters"]] == [c["title"] for c in seed["chapters"]]
    shown = [m["title"] for m in curve["milestones"]]
    assert shown == [seed["events"][i]["title"] for i in (0, 1, 2)]  # 민감·미확인·틀린 것은 없다
    (sensitive,) = [m for m in with_sensitive["milestones"] if m["sensitive"]]
    assert sensitive["title"] == seed["events"][3]["title"]
    assert len(with_sensitive["milestones"]) == 4
    assert len(status["titles"]) == 2  # 고점 1 + 전환점 1
    assert {t["kind"] for t in status["titles"]} == {"high", "turning_point"}
    assert status["xp_total"] == 0
    assert curve["ladder"] == []


async def test_story_to_curve(tmp_path):
    from my_planner.clock import to_iso
    from my_planner.store.repos.state import PAUSE_UNTIL_KEY

    # 토요일 낮, 텔레그램: 지난 이야기 → 사건 초안 둘 → 하나만 ✓ 저장 → 곡선과 상태창. 3일 뒤 남은 초안은 사라진다
    add = ("add_milestone", {"date": "2019", "kind": "high", "title": "제주 여행"})
    other = ("add_milestone", {"date": "2020", "kind": "low", "title": "꾸민 다른 일"})
    script = [FakeTurn([add, other], "곡선에 고점으로 남길까요?")]
    async with BeEnv.start(tmp_path, start=kst(2026, 10, 24, 13, 0), script=script) as env:
        await env.telegram("예전에 처음 혼자 제주 여행 갔을 때 정말 좋았어")
        out = env.sender.sent[-1]
        mid, rest = out.draft_milestone_ids
        pressed = await env.press(f"m:c:{mid}")
        answer = env.bot.answers[-1][1]
        curve = await (await env.get("/curve?zoom=year&from=2019-01-01")).json()
        status = await (await env.get("/status")).json()

        env.parts.state.set(PAUSE_UNTIL_KEY, to_iso(env.clock.now() + timedelta(days=30)))
        env.clock.advance(days=3)
        await env.tick()
        left = (env.parts.curve.get_milestone(mid), env.parts.curve.get_milestone(rest))

    assert pressed == "confirmed"
    assert answer == "✓ 저장: 제주 여행 (2019, 고점)\n칭호: 「제주 여행」의 순간"
    assert [(m["title"], m["date"], m["kind"]) for m in curve["milestones"]] == [("제주 여행", "2019", "high")]
    assert [t["title"] for t in status["titles"]] == ["「제주 여행」의 순간"]
    assert left[0] is not None and left[0].status == "confirmed" and left[1] is None


async def test_month_end_review_ladder(tmp_path):
    """월말 회고 사다리(SP3-4 티켓 14, 11.1): 11/29(일) 18:00 회고+저녁 체크인 한 메시지 → 컨디션 → 1단계 → 2단계 →
    기록 문구 → `/curve.ladder`와 `/checkins/{id}`."""
    from my_planner.harness.review_steps import LADDER_STEP1, LADDER_STEP2

    start = kst(2026, 11, 29, 18, 0) + timedelta(seconds=30)
    async with BeEnv.start(tmp_path, start=start, script=[FakeTurn([], "꾸민 월말 회고")]) as env:
        await env.tick()
        (review,) = env.sender.sent
        run_id = env.conn.execute("SELECT id FROM runs WHERE loop = 'evening_checkin'").fetchone()["id"]
        await env.press("c:2026-11-29:4", message_id=env.sender.message_ids[0])
        step1 = env.sender.sent[-1]
        await env.press("l:2026-11:n:6")
        step2 = env.sender.sent[-1]
        await env.press("l:2026-11:f:8")
        done = env.sender.sent[-1]
        curve = await (await env.get("/curve?zoom=month&from=2026-11-01&to=2026-11-30")).json()
        detail = await (await env.get(f"/checkins/{run_id}")).json()

    assert review.ask_condition_for is not None and review.ladder is None  # 컨디션 줄만
    assert step1.text == f"컨디션 4 기록했어요.\n\n{LADDER_STEP1}" and step1.ladder == ("2026-11", "n")
    assert step2.text == LADDER_STEP2 and step2.ladder == ("2026-11", "f")
    assert done.text == "기록했어요: 지금 6, 5년 뒤 8"
    assert {"period": "2026-11", "now": 6, "future": 8}.items() <= curve["ladder"][0].items()
    assert detail["state"] == "answered"


async def test_week_of_xp(tmp_path):
    """상태창 경험치 한 주(SP3-4 티켓 15, 9.1): 날마다 할 일 3개(X1), 저녁 체크인 답(X3, 일요일은 회고 묶음 X5),
    컨디션 버튼(X4). 11/2는 쉬고 11/3 tick 뒤 쉬는 날(X9)."""
    from datetime import date

    from my_planner.bot.commands import status_text
    from my_planner.clock import to_iso

    async def tick_at(env, at):
        env.clock.set(at)
        env.parts.state.set("last_seen_at", to_iso(at - timedelta(minutes=1)))
        await env.tick()

    script = [FakeTurn([], "꾸민 답") for _ in range(40)]
    async with BeEnv.start(tmp_path, start=kst(2026, 10, 26, 8, 0), script=script) as env:
        for day in range(7):  # 10/26(월) ~ 11/1(일)
            d = date(2026, 10, 26) + timedelta(days=day)
            y, m, dd = d.year, d.month, d.day
            weekend = day >= 5
            await tick_at(env, kst(y, m, dd, 10 if weekend else 9, 0) + timedelta(seconds=30))
            env.clock.set(kst(y, m, dd, 13, 0))
            for n in range(3):
                _, added = await env.action("add_task", {"title": f"꾸민 일 {day}-{n}", "areas": ["health"]})
                status, body = await env.action("complete_task", {"id": added["result"]["id"]})
                assert status == 200 and body["xp"]["gained"] == 10
            await tick_at(env, kst(y, m, dd, 18 if weekend else 17, 0 if weekend else 30) + timedelta(seconds=30))
            env.clock.set(kst(y, m, dd, 18, 30))
            await env.telegram("오늘 괜찮았어")
            await env.press(f"c:{d.isoformat()}:4")
        status = await (await env.get("/status")).json()
        ledger_sum = env.conn.execute("SELECT SUM(amount) FROM status_xp_ledger").fetchone()[0]
        await env.telegram("/status")
        telegram = env.bot.sent[-1][1]
        kinds = dict(env.conn.execute(
            "SELECT source_kind, COUNT(*) FROM status_xp_ledger GROUP BY source_kind"
        ).fetchall())
        # 11/2(월)는 아무것도 하지 않는다. 11/3 아침 tick의 하루 한 번 작업이 11/2를 쉬는 날로 본다
        await tick_at(env, kst(2026, 11, 2, 9, 0) + timedelta(seconds=30))
        await tick_at(env, kst(2026, 11, 3, 9, 0) + timedelta(seconds=30))
        after = await (await env.get("/status")).json()

    assert status["xp_total"] == 305 == 6 * (30 + 5 + 5) + (30 + 30 + 5)
    assert status["level"] == 2 and ledger_sum == status["xp_total"]
    assert kinds == {"task_done": 21, "checkin_reply": 6, "review_week": 1, "condition": 7}
    assert telegram == status_text(status)
    assert telegram.startswith("상태창\n레벨 2 · 경험치 155/200")
    assert after["xp_total"] == 310
    assert (after["recent_xp"][0]["label"], after["recent_xp"][0]["amount"]) == ("쉬는 날", 5)


# --- SP7-09: 습관 끝에서 끝까지 (SP7 스펙 1장 완료 조건 1~7) ---

HABIT_BANNED = ("연속", "스트릭", "달성률", "밀렸다", "놓쳤다", "실패", "끊겼", "며칠째", "남음")  # SP7 7장


async def _habit_story(tmp_path):
    """토요일 12:00 앱에서 습관 둘 → 18:00 저녁 체크인(습관 줄, 체크인 카드) → `hb:` 누름 → 텔레그램 대화로 운동 체크
    → 운동 체크 되돌리기 → `/habits`. 시험 둘이 같은 흐름을 쓴다. 단언할 값을 dict로 돌려준다."""
    from my_planner.bot.telegram_io import message_keyboard

    run_text = "오늘 하루 어떠셨어요? 오늘 챙긴 습관은 아래에서 눌러 주세요."
    seen: dict = {"confirmations": []}
    async with BeEnv.start(tmp_path, start=kst(2026, 10, 24, 12, 0), script=[FakeTurn([], run_text)]) as env:
        seen["xp_noon"] = (await (await env.get("/status")).json())["xp_total"]
        _, water = await env.action("add_habit", {"title": "물 마시기", "area": "health", "kind": "daily"})
        _, run_h = await env.action("add_habit", {"title": "운동", "area": "health", "kind": "weekly",
                                                  "target_per_week": 3})
        seen["confirmations"] += [water["confirmation"], run_h["confirmation"]]
        wid, rid = water["result"]["id"], run_h["result"]["id"]
        seen["ids"] = (wid, rid)
        seen["today_noon"] = (await (await env.get("/today")).json())["habits"]

        # 18:00 저녁 체크인: 텔레그램 메시지의 습관 줄(컨디션 줄 앞), 앱 체크인 상세의 `h_habit_<id>` 카드
        env.clock.set(kst(2026, 10, 24, 18, 0) + timedelta(seconds=30))
        await env.tick()
        (out,) = env.sender.sent
        h = env.parts.habits
        sent_markup = message_keyboard(out, {}, habits=h.list(), checked=h.checked_on(out.habit_date))
        seen["out"], seen["sent_markup"] = out, sent_markup
        run = env.conn.execute("SELECT id FROM runs WHERE loop = 'evening_checkin'").fetchone()
        seen["run_id"] = run["id"]
        mid = env.parts.deliveries.telegram_message_id(run["id"])
        seen["cards"] = (await (await env.get(f"/checkins/{run['id']}")).json())["cards"]
        seen["preamble"] = env.brain.prompts[0]

        # 그 회차 메시지의 물 마시기 버튼을 누른다(회차의 답 → X3)
        env.clock.set(kst(2026, 10, 24, 19, 0))
        seen["pressed"] = await env.press(f"hb:{wid}:2026-10-24", message_id=mid, reply_markup=sent_markup)
        seen["press_answer"] = env.bot.answers[-1][1]
        seen["redrawn"] = env.bot.edits[-1]

        # 텔레그램 대화: 두뇌가 운동을 체크한다
        env.brain.script.append(FakeTurn([("check_habit", {"id": rid})], "운동까지 챙기셨네요."))
        env.clock.set(kst(2026, 10, 24, 19, 10))
        await env.telegram("오늘 운동도 했어")
        seen["reply"] = env.sender.sent[-1]
        seen["chat_prompt"] = env.brain.prompts[-1]
        seen["today_eve"] = (await (await env.get("/today")).json())["habits"]
        seen["status_eve"] = await (await env.get("/status")).json()
        seen["habit_xp"] = env.conn.execute(
            "SELECT SUM(amount) FROM status_xp_ledger WHERE source_kind = 'habit_check'").fetchone()[0]
        seen["ledger"] = [tuple(r) for r in env.conn.execute(
            "SELECT source_kind, source_ref, amount FROM status_xp_ledger ORDER BY id").fetchall()]

        # 운동 체크 되돌리기(앱 활동 목록에서)
        (checked,) = [a for a in (await (await env.get("/activity?order=desc")).json())["items"]
                      if a["kind"] == "habit_checked" and a["actor"] == "secretary"]
        seen["checked_activity"] = checked
        env.clock.set(kst(2026, 10, 24, 19, 20))
        resp = await env.post(f"/activity/{checked['undo_id']}/undo", json={"client_msg_id": "e2e-habit-undo"})
        seen["undo_status"], seen["undo"] = resp.status, await resp.json()
        seen["confirmations"].append(seen["undo"]["confirmation"])
        seen["today_undo"] = (await (await env.get("/today")).json())["habits"]
        seen["xp_undo"] = (await (await env.get("/status")).json())["xp_total"]

        await env.telegram("/habits")
        seen["habits_text"], seen["habits_markup"] = env.bot.sent[-1][1], env.bot.markups[-1]
        seen["habits_list"] = (await (await env.get("/habits")).json())
        seen["telegram"] = [o.text for o in env.sender.sent] + [t for _, t in env.bot.sent]
        seen["answers"] = [a for _, a in env.bot.answers]
        seen["prompts"] = env.brain.prompts
    return seen


def _rows(markup):
    return [[(b.text, b.callback_data) for b in row] for row in markup.inline_keyboard]


async def test_habit_story(tmp_path):
    s = await _habit_story(tmp_path)
    wid, rid = s["ids"]
    habit_row = lambda w, r: [(f"{w} 물 마시기", f"hb:{wid}:2026-10-24"), (f"{r} 운동", f"hb:{rid}:2026-10-24")]
    condition = [(str(n), f"c:2026-10-24:{n}") for n in range(1, 6)]

    # 완료 조건 1: 앱에서 추가한 두 습관이 오늘 블록에(같은 순서가 `/habits`에도, 아래)
    assert s["confirmations"][:2] == ["✓ 습관 추가: 물 마시기 (매일)", "✓ 습관 추가: 운동 (주 3회)"]
    assert [(x["id"], x["checked"]) for x in s["today_noon"]] == [(wid, False), (rid, False)]

    # 완료 조건 3: 저녁 체크인 메시지의 습관 줄은 컨디션 줄 앞, 앱 카드는 `h_habit_<id>`
    out = s["out"]
    assert out.habit_date == out.ask_condition_for and str(out.habit_date) == "2026-10-24"
    assert _rows(s["sent_markup"]) == [habit_row("☐", "☐"), condition]
    (card,) = [c for c in s["cards"] if c["component"] == "ui_habit_check"]
    assert card["toolCallId"] == f"h_habit_{s['run_id']}" and card["props"] == {"date": "2026-10-24"}
    assert s["cards"].index(card) == 0  # 컨디션 고르기 앞
    assert "## 습관 버튼" in s["preamble"] and "## 오늘 습관\n- 물 마시기 (매일)\n- 운동 (주 3회): 이번 주 0번" in s["preamble"]

    # 텔레그램 버튼: ☐ → ✓, 같은 메시지의 버튼만 다시 그린다
    assert s["pressed"] == "recorded" and s["press_answer"] == "✓ 습관: 물 마시기"
    assert _rows(s["redrawn"][1]) == [habit_row("✓", "☐"), condition]

    # 완료 조건 4: 대화에서 두뇌가 `check_habit`, 확인 문구가 붙는다
    assert "✓ 습관: 운동" in s["reply"].text
    assert s["chat_prompt"].endswith("오늘 운동도 했어")  # 회차 세션을 이어 가는 답(앞머리는 회차 프롬프트에)
    assert (s["checked_activity"]["actor"], s["checked_activity"]["channel"]) == ("secretary", "telegram")
    eve = {x["id"]: x for x in s["today_eve"]}
    assert eve[wid]["checked"] and eve[rid]["checked"] and eve[rid]["week_count"] == 1

    # 완료 조건 5: 체크마다 3(X11) × 2 + 회차 답(X3) 5 = 11. 되돌려도 줄지 않는다
    assert s["status_eve"]["xp_total"] - s["xp_noon"] == 11
    assert s["habit_xp"] == 6
    assert sorted(s["ledger"]) == sorted([
        ("habit_check", f"habit:{wid}:2026-10-24", 3), ("habit_check", f"habit:{rid}:2026-10-24", 3),
        ("checkin_reply", f"run:{s['run_id']}", 5),
    ])
    assert s["undo_status"] == 200 and s["undo"]["status"] == "undone"
    assert s["xp_undo"] == s["status_eve"]["xp_total"]
    after = {x["id"]: x for x in s["today_undo"]}
    assert after[wid]["checked"] and not after[rid]["checked"] and after[rid]["week_count"] == 0

    # `/habits`가 같은 상태, 같은 순서
    assert s["habits_text"] == "오늘 습관 (10/24 토)\n- 물 마시기\n- 운동 · 이번 주 0번 / 목표 3번"
    assert _rows(s["habits_markup"]) == [habit_row("✓", "☐")]
    assert [x["id"] for x in s["habits_list"]["items"]] == [wid, rid]


async def test_habit_copy_has_no_banned_words(tmp_path):
    s = await _habit_story(tmp_path)
    copy = [*s["telegram"], *s["answers"], *s["confirmations"], *s["prompts"]]
    assert len(s["telegram"]) >= 3 and len(s["answers"]) == 1 and len(s["prompts"]) == 2
    hits = [(w, c) for c in copy for w in HABIT_BANNED if w in c]
    assert hits == []


async def test_end_of_day_moments(tmp_path):
    """하루 끝 이룬 순간(SP8 6.2~6.3, 1장 조건 3): 앱에서 말한 날 → 다음 날 04:01 tick → `save_moments` 하나로 저장."""
    moment = {"text": "포트폴리오 사례 하나를 끝까지 다듬었어요", "area": "career", "sources": ["chat"]}
    script = [FakeTurn([], "축하해요!"), FakeTurn([("save_moments", {"date": "2026-10-25", "moments": [moment]})], "")]
    async with BeEnv.start(tmp_path, start=kst(2026, 10, 25, 13, 0), script=script) as env:
        env.parts.runner.checkins = False  # 회차 없이 하루 한 번 작업만
        await env.chat("드디어 사례 하나 끝냈다")
        env.clock.set(kst(2026, 10, 26, 4, 1))
        await env.tick()
        rows = env.conn.execute("SELECT date, slot, text, area FROM status_moments").fetchall()
        day = env.conn.execute("SELECT state, saved FROM status_moment_days WHERE date = '2026-10-25'").fetchone()
        kinds = [c["run_ctx"].kind for c in env.brain.calls]

    assert kinds == ["chat", "moments"]
    assert [tuple(r) for r in rows] == [("2026-10-25", 1, moment["text"], "career")]
    assert tuple(day) == ("done", 1)
