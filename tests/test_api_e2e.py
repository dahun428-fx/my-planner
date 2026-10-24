"""API 수용 시험 (가짜 두뇌 + 가짜 시계, `BeEnv`)."""

from datetime import timedelta

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
