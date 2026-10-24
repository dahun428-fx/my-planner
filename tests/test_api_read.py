"""읽기 경로 (SP3-4 스펙 6.3.2~6.3.4, 6.3.7, 6.3.8, 6.4.5, 6.4.6). 내용은 모두 꾸며 낸 것이다."""

from datetime import date, timedelta

import pytest
from be_env import BeEnv
from fakes import FakeTurn
from test_dispatcher_messages import kst

from my_planner.bot.commands import today_text, week_text
from my_planner.clock import to_iso
from my_planner.domain import Area, Cadence, LoopKey, TaskStatus

SAT = kst(2026, 10, 24, 13, 0)  # 토요일, 논리적 날짜 10/24, 이번 주 2026-W43 (10/19~10/25)
MON_EVENING = kst(2026, 10, 26, 17, 30) + timedelta(seconds=30)


def mk(env, title, *, status=TaskStatus.open, planned_for=None, scheduled_at=None, areas=(Area.career,)):
    pf = date.fromisoformat(planned_for) if planned_for else None
    return env.parts.tasks.create(title, list(areas), status, pf, scheduled_at, None, "")


async def get_json(env, path, status=200):
    resp = await env.get(path)
    assert resp.status == status, await resp.text()
    return await resp.json()


def titles_in_order(text, titles):
    """`titles`가 모두 `text`에 있고 같은 순서로 나온다."""
    pos = [text.index(t) for t in titles]
    assert pos == sorted(pos)


# --- 슬라이스 1: 오늘, 이번 주 ---


async def test_today_matches_today_text_same_order(tmp_path):
    async with BeEnv.start(tmp_path, start=SAT) as env:
        a = mk(env, "수채화 밑그림", planned_for="2026-10-24")
        b = mk(env, "도서관 반납", planned_for="2026-10-24")
        c = mk(env, "치과 정기 검진", planned_for="2026-10-24", scheduled_at=kst(2026, 10, 24, 15, 0))
        d = mk(env, "지난 주에 잡은 빨래", planned_for="2026-10-22")
        mk(env, "다음 주 장보기", planned_for="2026-10-28")
        env.parts.tasks.set_priorities(Cadence.day, "2026-10-24", [b.id, a.id])
        body = await get_json(env, "/today")
        text = today_text(env.parts.tasks, env.clock.now(), env.settings.timezone, env.settings.day_boundary)

    assert body["date"] == "2026-10-24" and body["weekday"] == "토"
    got = [(x["group"], x["todo"]["id"]) for x in body["todos"]]
    assert got == [("priority", b.id), ("priority", a.id), ("scheduled", c.id), ("open", d.id)]
    titles_in_order(text, [x["todo"]["title"] for x in body["todos"]])
    assert "다음 주 장보기" not in text and all(x["todo"]["title"] != "다음 주 장보기" for x in body["todos"])
    assert body["todos"][0]["todo"]["priority"] == {"cadence": "day", "period": "2026-10-24", "rank": 1}
    assert body["brief"] is None and body["condition"] is None and body["cards"] == []


async def test_week_has_all_7_days_and_matches_week_text(tmp_path):
    async with BeEnv.start(tmp_path, start=SAT) as env:
        w = mk(env, "수요일 도자기 수업", planned_for="2026-10-21", scheduled_at=kst(2026, 10, 21, 19, 0))
        t = mk(env, "토요일 산책", planned_for="2026-10-24")
        p = mk(env, "이번 주 책 한 권", planned_for="2026-10-23")
        env.parts.tasks.set_priorities(Cadence.week, "2026-W43", [p.id])
        body = await get_json(env, "/week")
        text = week_text(env.parts.tasks, env.clock.now(), env.settings.timezone, env.settings.day_boundary)

    assert body["week"] == "2026-W43" and (body["start"], body["end"]) == ("2026-10-19", "2026-10-25")
    assert [d["date"] for d in body["days"]] == [f"2026-10-{n}" for n in range(19, 26)]
    assert [d["is_today"] for d in body["days"]] == [False] * 5 + [True, False]
    by_day = {d["date"]: [x["id"] for x in d["todos"]] for d in body["days"]}
    assert by_day["2026-10-21"] == [w.id] and by_day["2026-10-24"] == [t.id]
    assert by_day["2026-10-19"] == [] and by_day["2026-10-25"] == []  # 빈 날도 들어 있다
    assert [x["id"] for x in body["priorities"]] == [p.id]
    ordered = [body["priorities"][0]["title"]] + [x["title"] for d in body["days"] for x in d["todos"]]
    titles_in_order(text, list(dict.fromkeys(ordered)))  # 우선순위에 나온 일은 날짜 칸에도 있다


async def test_today_checkins_equal_checkins_list(tmp_path):
    async with BeEnv.start(
        tmp_path, start=kst(2026, 10, 24, 10, 0) + timedelta(seconds=30), script=[FakeTurn([], "좋은 아침이에요")]
    ) as env:
        await env.tick()
        today = await get_json(env, "/today")
        listed = await get_json(env, "/checkins?date=2026-10-24")
        default = await get_json(env, "/checkins")

    assert len(today["checkins"]) == 1
    assert today["checkins"] == listed["items"] == default["items"]
    assert today["brief"]["text"] == "좋은 아침이에요" and today["brief"]["loop"] == "morning_brief"


# --- 슬라이스 2: 숨김, 우선순위, 안내, 시각 ---


async def test_drafts_and_soft_deleted_never_in_get(tmp_path):
    async with BeEnv.start(tmp_path, start=SAT) as env:
        draft = mk(env, "초안 쓰기 연습", status=TaskStatus.draft, planned_for="2026-10-24")
        gone = mk(env, "지운 일", planned_for="2026-10-24")
        kept = mk(env, "남은 일", planned_for="2026-10-24")
        for cadence, period in ((Cadence.day, "2026-10-24"), (Cadence.week, "2026-W43")):
            env.parts.tasks.set_priorities(cadence, period, [draft.id, gone.id, kept.id])
        env.conn.execute("UPDATE tasks SET deleted_at = ? WHERE id = ?", (to_iso(env.clock.now()), gone.id))
        env.conn.commit()
        seen = {}
        for path in ("/today", "/week", "/priorities?cadence=week"):
            seen[path] = await get_json(env, path)
        drafts = await get_json(env, "/drafts")

    flat = repr(seen)
    assert "초안 쓰기 연습" not in flat and "지운 일" not in flat and "남은 일" in flat
    assert [x["todo"]["title"] for x in drafts["items"]] == ["초안 쓰기 연습"]
    assert drafts["items"][0]["todo"]["status"] == "draft"


async def test_todo_priority_is_biggest_current_period(tmp_path):
    async with BeEnv.start(tmp_path, start=SAT) as env:
        big = mk(env, "분기 목표", planned_for="2026-10-24")
        small = mk(env, "오늘만", planned_for="2026-10-24")
        old = mk(env, "지난 주 우선순위", planned_for="2026-10-24")
        tasks = env.parts.tasks
        tasks.set_priorities(Cadence.day, "2026-10-24", [small.id, big.id])
        tasks.set_priorities(Cadence.week, "2026-W43", [old.id, big.id])
        tasks.set_priorities(Cadence.quarter, "2026-Q4", [big.id])
        tasks.set_priorities(Cadence.week, "2026-W42", [old.id])  # 지금 기간이 아니다
        tasks.set_priorities(Cadence.week, "2026-W43", [big.id])
        body = await get_json(env, "/today")

    pri = {x["todo"]["id"]: x["todo"]["priority"] for x in body["todos"]}
    assert pri[big.id] == {"cadence": "quarter", "period": "2026-Q4", "rank": 1}
    assert pri[small.id] == {"cadence": "day", "period": "2026-10-24", "rank": 1}
    assert pri.get(old.id) is None


async def test_brief_from_done_morning_or_return(tmp_path):
    async with BeEnv.start(tmp_path, start=SAT) as env:
        runs = env.parts.runs

        def done(loop, hour, text):
            r = runs.ensure(loop, kst(2026, 10, 24, hour, 0))
            runs.save_outbound(r.id, text)
            runs.mark_done(r.id)
            return r

        failed = runs.ensure(LoopKey.morning_brief, kst(2026, 10, 24, 9, 0), Cadence.week)
        runs.save_outbound(failed.id, "보내지 못한 글")
        runs.mark_failed(failed.id, "send")
        assert (await get_json(env, "/today"))["brief"] is None  # done이 아니면 없다
        morning = done(LoopKey.morning_brief, 10, "아침 브리핑")
        first = (await get_json(env, "/today"))["brief"]
        back = done(LoopKey.return_, 12, "다시 오셨네요")
        second = (await get_json(env, "/today"))["brief"]
        evening = done(LoopKey.evening_checkin, 18, "저녁 인사")
        third = (await get_json(env, "/today"))["brief"]

    assert (first["run_id"], first["loop"], first["text"]) == (morning.id, "morning_brief", "아침 브리핑")
    assert (second["run_id"], second["loop"]) == (back.id, "return")
    assert third["run_id"] == back.id and evening.id != back.id  # 저녁 체크인은 브리핑이 아니다
    assert second["sent_at"].endswith("Z")


async def test_times_are_utc_z(tmp_path):
    async with BeEnv.start(tmp_path, start=kst(2026, 10, 26, 9, 0)) as env:
        t = mk(env, "내일 치과", planned_for="2026-10-27", scheduled_at=kst(2026, 10, 27, 14, 0))
        week = await get_json(env, "/week")
    todo = next(x for d in week["days"] for x in d["todos"] if x["id"] == t.id)
    assert todo["scheduled_at"] == "2026-10-27T05:00:00Z"
    assert todo["completed_at"] is None and todo["planned_for"] == "2026-10-27"  # 날짜는 그대로


# --- 슬라이스 3: 컨디션, 잘못된 쿼리 ---


async def test_conditions_default_30_days_skips_empty(tmp_path):
    async with BeEnv.start(tmp_path, start=SAT) as env:
        cond = env.parts.conditions
        cond.upsert(date(2026, 10, 23), 3, None)
        cond.upsert(date(2026, 10, 21), 4, "푹 잠")
        cond.upsert(date(2026, 9, 25), 5, None)
        cond.upsert(date(2026, 9, 24), 1, None)  # 30일 밖
        body = await get_json(env, "/conditions")
        today = await get_json(env, "/today")
        ranged = await get_json(env, "/conditions?from=2026-10-21&to=2026-10-21")

    assert (body["from"], body["to"]) == ("2026-09-25", "2026-10-24")
    assert body["items"] == [
        {"date": "2026-09-25", "score": 5, "note": None},
        {"date": "2026-10-21", "score": 4, "note": "푹 잠"},
        {"date": "2026-10-23", "score": 3, "note": None},
    ]  # 기록 없는 날은 넣지 않는다
    assert body["days_logged"] == 3 and body["average"] == 4.0
    assert today["condition"] is None  # 오늘은 기록 없음
    assert ranged["items"] == [{"date": "2026-10-21", "score": 4, "note": "푹 잠"}]
    async with BeEnv.start(tmp_path / "e", start=SAT) as env:
        empty = await get_json(env, "/conditions")
    assert empty["items"] == [] and empty["days_logged"] == 0 and empty["average"] is None


@pytest.mark.parametrize(
    "path",
    [
        "/conditions?from=abc",
        "/conditions?to=2026-13-40",
        "/conditions?from=2026-10-24&to=2026-10-23",
        "/conditions?from=2025-10-23&to=2026-10-24",  # 367일
        "/conditions?from=2026-1-2",
        "/checkins?date=내일",
        "/checkins/abc",
        "/conversations?limit=0",
        "/conversations?limit=201",
        "/conversations?limit=abc",
        "/conversations?channel=sms",
        "/conversations/abc/messages",
        "/priorities",
        "/priorities?cadence=day",
        "/priorities?cadence=week&period=2026-10",
        "/priorities?cadence=quarter&period=2026-Q5",
        "/priorities?cadence=month&period=2026-13",
        "/priorities?cadence=year&period=26",
        "/priorities?cadence=week&period=",  # 빈 값은 기본 기간이 아니라 형식 오류
    ],
)
async def test_bad_query_values_400(tmp_path, path):
    async with BeEnv.start(tmp_path, start=SAT) as env:
        resp = await env.get(path)
        body = await resp.json()
    assert resp.status == 400
    assert body["error"]["code"] == "invalid_request"
    assert "abc" not in body["error"]["message"]  # 요청 값을 되돌려 주지 않는다


async def test_conditions_366_days_ok_and_missing_ids_404(tmp_path):
    async with BeEnv.start(tmp_path, start=SAT) as env:
        assert (await env.get("/conditions?from=2025-10-24&to=2026-10-24")).status == 200  # 366일
        for path in ("/checkins/999", "/conversations/999/messages"):
            resp = await env.get(path)
            assert resp.status == 404 and (await resp.json())["error"]["code"] == "not_found"
        assert (await env.get("/checkins", token=None)).status == 401


# --- 슬라이스 4: 답할 회차, 대화 ---


def propose(*titles):
    return ("propose_tasks", {"tasks": [{"title": t, "areas": ["health"]} for t in titles]})


async def test_checkin_states_and_detail_cards(tmp_path):
    script = [FakeTurn([propose("저녁 스트레칭", "물 마시기")], "오늘 어떠셨어요?")]
    async with BeEnv.start(tmp_path, start=MON_EVENING, script=script) as env:
        await env.tick()
        listing = await get_json(env, "/checkins?date=2026-10-26")
        (item,) = listing["items"]
        detail = await get_json(env, f"/checkins/{item['id']}")
        assert item["state"] == "pending" and item["loop"] == "evening_checkin"
        assert item["delivered_via"] == ["telegram"] and item["answered_via"] is None
        assert item["reply_until"] == "2026-10-26T19:00:00Z"  # 다음 날 04:00 KST
        assert item["conversation_ids"]["app"] is None and item["conversation_ids"]["telegram"] is not None
        assert detail["text"] == "오늘 어떠셨어요?"
        draft, cond = detail["cards"]
        ids = draft["props"]["task_ids"]
        assert draft["toolCallId"] == f"h_draft_{item['id']}" and draft["component"] == "ui_todo_draft"
        assert draft["data"] == {
            "todos": [
                {"id": ids[0], "title": "저녁 스트레칭", "cadence": None, "area": "health", "status": "draft"},
                {"id": ids[1], "title": "물 마시기", "cadence": None, "area": "health", "status": "draft"},
            ]
        }
        assert cond == {
            "toolCallId": f"h_cond_{item['id']}", "component": "ui_condition_picker", "props": {"date": "2026-10-26"}
        }  # 조각마다 data가 없을 수 있다
        # 하나 확정하면 남은 초안만, 컨디션을 기록하면 그 카드가 빠진다
        env.parts.tasks.set_status(ids[0], TaskStatus.open)
        env.parts.conditions.upsert(date(2026, 10, 26), 4, None)
        after = await get_json(env, f"/checkins/{item['id']}")
        assert [c["component"] for c in after["cards"]] == ["ui_todo_draft"]
        assert after["cards"][0]["props"] == {"task_ids": [ids[1]]}
        # 답장 창이 끝나면 지나감, 답했으면 answered
        env.clock.set(kst(2026, 10, 27, 9, 0))
        assert (await get_json(env, f"/checkins/{item['id']}"))["state"] == "missed"
        env.conn.execute(
            "UPDATE runs SET answered_at = ?, answered_via = 'app' WHERE id = ?", (to_iso(kst(2026, 10, 26, 20, 0)), item["id"])
        )
        env.conn.commit()
        answered = await get_json(env, f"/checkins/{item['id']}")
        today = await get_json(env, "/today")

    assert answered["state"] == "answered" and answered["answered_via"] == "app"
    assert answered["answered_at"] == "2026-10-26T11:00:00Z"
    assert today["date"] == "2026-10-27" and today["checkins"] == []  # 어제 회차는 어제 날짜에


async def test_merged_run_listed_once_with_latest_window(tmp_path):
    async with BeEnv.start(tmp_path, start=kst(2026, 10, 25, 22, 0)) as env:  # 일요일 밤
        runs = env.parts.runs
        evening = runs.ensure(LoopKey.evening_checkin, kst(2026, 10, 25, 18, 0))
        review = runs.ensure(LoopKey.review, kst(2026, 10, 25, 21, 0), Cadence.week)
        for r in (evening, review):
            runs.save_outbound(r.id, f"본문 {r.id}")
            runs.mark_done(r.id)
        runs.add_merged(review.id, [evening.id])
        listing = await get_json(env, "/checkins?date=2026-10-25")
        gone = await env.get(f"/checkins/{evening.id}")
        detail = await get_json(env, f"/checkins/{review.id}")

        from my_planner.harness.checkins import reply_until

        latest = max(reply_until(runs.get(r.id), runs=runs, settings=env.settings) for r in (evening, review))

    assert [i["id"] for i in listing["items"]] == [review.id]  # 합쳐진 회차는 따로 나오지 않는다
    assert gone.status == 404
    assert listing["items"][0]["reply_until"] == latest.isoformat().replace("+00:00", "Z")
    assert detail["text"] == f"본문 {review.id}"
    assert [c["component"] for c in detail["cards"]] == ["ui_condition_picker"]  # 합쳐진 저녁 체크인의 날짜
    assert detail["cards"][0]["props"] == {"date": "2026-10-25"}


async def test_skipped_runs_are_not_checkins(tmp_path):
    async with BeEnv.start(tmp_path, start=SAT) as env:
        runs = env.parts.runs
        skipped = runs.ensure(LoopKey.morning_brief, kst(2026, 10, 24, 10, 0))
        runs.mark_skipped(skipped.id, "late")
        failed = runs.ensure(LoopKey.evening_checkin, kst(2026, 10, 24, 12, 0))
        runs.mark_failed(failed.id, "exception")
        pending = runs.ensure(LoopKey.return_, kst(2026, 10, 24, 12, 30))
        assert (await get_json(env, "/checkins"))["items"] == []
        for r in (skipped, failed, pending):
            assert (await env.get(f"/checkins/{r.id}")).status == 404
        assert (await get_json(env, "/today"))["checkins"] == []


async def test_conversations_list_and_messages(tmp_path):
    script = [FakeTurn([], "네, 알겠어요"), FakeTurn([], "물론이죠")]
    async with BeEnv.start(tmp_path, start=SAT, script=script) as env:
        await env.telegram("오늘 책 읽을 시간이 있을까")
        env.clock.advance(timedelta(minutes=5))
        await env.telegram("그럼 30분만 잡아 줘")
        convs = await get_json(env, "/conversations")
        tg = await get_json(env, "/conversations?channel=telegram&limit=1")
        app = await get_json(env, "/conversations?channel=app")
        cid = convs["items"][0]["id"]
        messages = await get_json(env, f"/conversations/{cid}/messages")
        again = await get_json(env, f"/conversations/{cid}/messages")

    (conv,) = convs["items"]
    assert set(conv) == {"id", "kind", "channel", "run_id", "opened_at", "last_message_at", "closed_at"}
    assert conv["channel"] == "telegram" and conv["kind"] == "chat" and conv["closed_at"] is None
    assert conv["opened_at"].endswith("Z")
    assert tg["items"] == convs["items"] and app["items"] == []
    items = messages["items"]
    assert [(m["speaker"], m["text"]) for m in items] == [
        ("user", "오늘 책 읽을 시간이 있을까"), ("secretary", "네, 알겠어요"),
        ("user", "그럼 30분만 잡아 줘"), ("secretary", "물론이죠"),
    ]
    assert [m["id"] for m in items] == [f"l-{cid}-{n}" for n in (1, 2, 3, 4)]  # 텔레그램 줄은 모두 l-<대화>-<n>
    assert all(m["channel"] == "telegram" and m["tools"] == [] for m in items)
    assert items[0]["at"] == "2026-10-24T04:00:00Z" and again == messages  # 다시 읽어도 같다


async def test_messages_list_tool_names(tmp_path):
    script = [FakeTurn([("add_task", {"title": "책 읽기", "areas": ["learning"]})], "넣었어요")]
    async with BeEnv.start(tmp_path, start=SAT, script=script) as env:
        await env.telegram("책 읽기 넣어 줘")
        cid = (await get_json(env, "/conversations"))["items"][0]["id"]
        messages = await get_json(env, f"/conversations/{cid}/messages")
    assert [m["tools"] for m in messages["items"]] == [[], ["add_task"]]


async def test_drafts_list_fields_order_and_expiry(tmp_path):
    script = [FakeTurn([propose("산책 20분", "일기 쓰기")], "이렇게 해 볼까요?")]
    async with BeEnv.start(tmp_path, start=SAT, script=script) as env:
        await env.telegram("저녁 루틴 짜 줘")
        first = await get_json(env, "/drafts")
        conv = (await get_json(env, "/conversations"))["items"][0]["id"]
        env.clock.advance(timedelta(days=2))
        old = mk(env, "수동 초안", status=TaskStatus.draft)  # 도구 기록이 없는 초안
        later = await get_json(env, "/drafts")
        env.clock.advance(timedelta(days=1, minutes=1))  # 처음 초안은 3일이 지났다
        last = await get_json(env, "/drafts")

    one, two = first["items"]
    assert (one["todo"]["title"], two["todo"]["title"]) == ("산책 20분", "일기 쓰기")  # proposed_at이 같으면 id 순
    assert one["conversation_id"] == conv and one["run_id"] is None
    assert one["proposed_at"] == "2026-10-24T04:00:00Z" and one["expires_at"] == "2026-10-27T04:00:00Z"
    assert [i["todo"]["id"] for i in later["items"]] == [one["todo"]["id"], two["todo"]["id"], old.id]
    manual = later["items"][2]
    assert manual["run_id"] is None and manual["conversation_id"] is None
    assert [i["todo"]["title"] for i in last["items"]] == ["수동 초안"]  # 만료 전 초안만


async def test_proposed_at_follows_latest_proposed_event(tmp_path):
    async with BeEnv.start(tmp_path, start=SAT) as env:
        t = mk(env, "다시 제안한 일", status=TaskStatus.draft)
        env.clock.advance(timedelta(days=2))
        # 확정을 되돌리면 같은 할 일에 새 `proposed` 이벤트가 붙는다(6.4.3)
        env.conn.execute(
            "INSERT INTO task_events (task_id, kind, payload_json, at) VALUES (?, 'proposed', '{}', ?)",
            (t.id, to_iso(env.clock.now())),
        )
        env.conn.commit()
        env.clock.advance(timedelta(days=2))  # 처음 제안한 지 4일, 다시 제안한 지 2일
        body = await get_json(env, "/drafts")
    (item,) = body["items"]
    assert item["proposed_at"] == "2026-10-26T04:00:00Z" and item["expires_at"] == "2026-10-29T04:00:00Z"


async def test_priorities_default_and_explicit_period_in_rank_order(tmp_path):
    async with BeEnv.start(tmp_path, start=SAT) as env:
        a, b, c = (mk(env, n) for n in ("첫째 일", "둘째 일", "셋째 일"))
        draft = mk(env, "초안 일", status=TaskStatus.draft)
        tasks = env.parts.tasks
        tasks.set_priorities(Cadence.quarter, "2026-Q4", [c.id, draft.id, a.id])
        tasks.set_priorities(Cadence.quarter, "2026-Q3", [b.id])
        tasks.set_priorities(Cadence.week, "2026-W43", [b.id])
        tasks.set_priorities(Cadence.month, "2026-10", [a.id])
        tasks.set_priorities(Cadence.year, "2026", [c.id])
        quarter = await get_json(env, "/priorities?cadence=quarter")
        past = await get_json(env, "/priorities?cadence=quarter&period=2026-Q3")
        none = await get_json(env, "/priorities?cadence=quarter&period=2027-Q1")
        week = await get_json(env, "/priorities?cadence=week")
        month = await get_json(env, "/priorities?cadence=month")
        year = await get_json(env, "/priorities?cadence=year")

    assert (quarter["cadence"], quarter["period"]) == ("quarter", "2026-Q4")
    assert [i["id"] for i in quarter["items"]] == [c.id, a.id]  # 순위 순서, 초안은 뺀다
    assert quarter["items"][0]["priority"] == {"cadence": "year", "period": "2026", "rank": 1}  # 가장 큰 주기
    assert [i["id"] for i in past["items"]] == [b.id] and past["period"] == "2026-Q3"
    assert none["items"] == []
    assert (week["period"], month["period"], year["period"]) == ("2026-W43", "2026-10", "2026")


async def test_app_message_ids_in_api(tmp_path):
    from my_planner.store.transcripts import (
        app_secretary_message_id,
        app_user_message_id,
    )

    async with BeEnv.start(tmp_path, start=SAT) as env:
        conv = env.parts.convs.open("chat", date(2026, 10, 24))
        env.conn.execute("UPDATE conversations SET channel = 'app' WHERE id = ?", (conv.id,))
        env.conn.commit()
        ts, at = env.parts.transcripts, env.clock.now()
        ts.append(at, "비서", conv.id, "morning_brief", "아침 본문", channel="app")
        ts.append(at, "사용자", conv.id, None, "책 읽기 넣어 줘", channel="app",
                  message_id=app_user_message_id(conv.id, -1, "나쁜 id!"))
        ts.append(at, "비서", conv.id, None, "넣었어요", ["add_task"], channel="app",
                  message_id=app_secretary_message_id(conv.id, -1))
        ts.append(at, "사용자", conv.id, None, "고마워", channel="telegram")
        body = await get_json(env, f"/conversations/{conv.id}/messages")
        listing = await get_json(env, "/conversations?channel=app")

    c = conv.id
    assert [m["id"] for m in body["items"]] == [f"l-{c}-1", f"u-{c}-1", f"m-{c}-1", f"l-{c}-4"]
    assert [m["channel"] for m in body["items"]] == ["app", "app", "app", "telegram"]
    assert body["items"][2]["tools"] == ["add_task"]
    assert [i["id"] for i in listing["items"]] == [c]


def test_todo_refs_follow_6_3(tmp_path, conn):
    """R4c: `data.todos`는 `TodoRef{id,title,cadence,area,status}`. 소프트 삭제는 빠지고 `dropped`는 남는다."""
    from my_planner.clock import FakeClock
    from my_planner.store.repos.tasks import TasksRepo
    from my_planner.store.views import todo_refs

    clock = FakeClock(SAT)
    repo = TasksRepo(conn, clock)
    a = repo.create("정리 하나", [Area.learning, Area.career], TaskStatus.open)
    b = repo.create("정리 둘", [], TaskStatus.draft)
    c = repo.create("정리 셋", [Area.health], TaskStatus.open)
    d = repo.create("정리 넷", [Area.health], TaskStatus.open)
    repo.set_priorities(Cadence.month, "2026-10", [a.id])
    repo.set_status(c.id, TaskStatus.dropped)
    conn.execute("UPDATE tasks SET deleted_at = ? WHERE id = ?", (to_iso(SAT), d.id))
    conn.commit()
    got = todo_refs([b.id, a.id, c.id, d.id, 999], repo, date(2026, 10, 24))
    assert got == [
        {"id": b.id, "title": "정리 둘", "cadence": None, "area": None, "status": "draft"},
        {"id": a.id, "title": "정리 하나", "cadence": "month", "area": "career", "status": "open"},  # 영역 순서의 첫째
        {"id": c.id, "title": "정리 셋", "cadence": None, "area": "health", "status": "dropped"},
    ]


async def test_read_routes_get_only_read_only_connections(tmp_path):
    import sqlite3

    seen = []
    async with BeEnv.start(tmp_path, start=SAT) as env:
        real = env.deps.read_conn

        def spy():
            conn = real()
            with pytest.raises(sqlite3.OperationalError, match="readonly"):
                conn.execute("INSERT INTO app_state (key, value) VALUES ('x', 'y')")
            seen.append(conn)
            return conn

        env.deps.read_conn = spy
        paths = ["/today", "/week", "/conditions", "/priorities?cadence=year", "/drafts", "/checkins", "/checkins/1",
                 "/conversations", "/conversations/1/messages", "/ui/catalog", "/schema"]
        for path in paths:
            assert (await env.get(path)).status in (200, 404)
        assert env.parts.state.get("x") is None
    assert len(seen) == len(paths)


async def test_expired_draft_hidden_in_cards_and_drafts_alike(tmp_path):
    script = [FakeTurn([propose("오래된 초안")], "오늘 어떠셨어요?")]
    async with BeEnv.start(tmp_path, start=MON_EVENING, script=script) as env:
        await env.tick()
        (item,) = [i for i in (await get_json(env, "/checkins?date=2026-10-26"))["items"]]
        before = await get_json(env, f"/checkins/{item['id']}")
        drafts_before = await get_json(env, "/drafts")
        env.clock.advance(timedelta(days=3, minutes=1))  # 밤 작업은 아직 안 돌았다: 행은 draft로 남아 있다
        after = await get_json(env, f"/checkins/{item['id']}")
        drafts_after = await get_json(env, "/drafts")

    assert before["cards"][0]["component"] == "ui_todo_draft" and drafts_before["items"]
    assert "ui_todo_draft" not in [c["component"] for c in after["cards"]]
    assert drafts_after["items"] == []
