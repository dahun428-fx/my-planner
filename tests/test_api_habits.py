"""습관 API (SP7 스펙 5.5, 5.7 "누름은 그 회차의 답으로 친다"의 앱 쪽). 내용은 모두 꾸며 낸 것이다."""

import json
from datetime import date, timedelta

import jsonschema
import pytest
from be_env import BeEnv
from fakes import FakeTurn
from test_api_read import get_json
from test_dispatcher_messages import kst

from my_planner.api.models import schema_bundle
from my_planner.domain import RunContext
from my_planner.store.repos.activity import ConfirmsRepo
from my_planner.tools.actions import ActionRequest

SAT = kst(2026, 10, 24, 13, 0)  # 토요일, 논리적 날짜 10/24, 이번 주 2026-W43 (10/19~10/25)
SAT_EVENING = kst(2026, 10, 24, 18, 0) + timedelta(seconds=30)  # 토요일 저녁 체크인 18:00
ARCHIVE_ASK = "운동 습관을 그만둘까요? 기록은 남아요."


def _validate(model, body):
    jsonschema.Draft202012Validator(schema_bundle()["models"][model]).validate(body)


def habit(env, title, *, area="health", kind="daily", target=None, status="active"):
    h = env.parts.habits.add(title, area, kind, target, env.clock.now())
    if status != "active":
        h = env.parts.habits.set_status(h.id, status, env.clock.now())
    return h


def check(env, h, day):
    env.parts.habits.check(h.id, date.fromisoformat(day), env.clock.now())


def run_row(env):
    return env.conn.execute("SELECT * FROM runs WHERE loop = 'evening_checkin' ORDER BY id DESC").fetchone()


# --- 슬라이스 1: /today.habits, GET /habits ---


async def test_today_has_habits_in_sort_order(tmp_path):
    async with BeEnv.start(tmp_path, start=SAT) as env:
        water = habit(env, "물 마시기")
        run = habit(env, "운동", kind="weekly", target=3)
        habit(env, "쉬는 습관", status="paused")
        habit(env, "그만둔 습관", status="archived")
        stretch = habit(env, "스트레칭", area="quality_of_life")
        env.conn.execute("UPDATE habits SET sort_order = 0 WHERE id = ?", (stretch.id,))
        env.conn.commit()
        check(env, water, "2026-10-24")
        check(env, run, "2026-10-20")
        check(env, run, "2026-10-22")
        check(env, run, "2026-10-18")  # 전 주(W42)
        body = await get_json(env, "/today")

    _validate("Today", body)
    assert [h["id"] for h in body["habits"]] == [stretch.id, water.id, run.id]
    assert body["habits"][1] == {
        "id": water.id, "title": "물 마시기", "area": "health", "kind": "daily", "target_per_week": None,
        "status": "active", "checked": True, "week_count": 1,
    }
    assert (body["habits"][2]["checked"], body["habits"][2]["week_count"]) == (False, 2)
    assert body["habits"][2]["target_per_week"] == 3


async def test_today_habits_empty_list(tmp_path):
    async with BeEnv.start(tmp_path, start=SAT) as env:
        empty = await get_json(env, "/today")
        habit(env, "쉬는 습관", status="paused")
        only_paused = await get_json(env, "/today")
    assert empty["habits"] == [] and only_paused["habits"] == []


async def test_get_habits_status_filter(tmp_path):
    async with BeEnv.start(tmp_path, start=SAT) as env:
        a = habit(env, "물 마시기")
        p = habit(env, "운동", kind="weekly", target=3, status="paused")
        r = habit(env, "그만둔 습관", status="archived")
        gone = habit(env, "지운 습관")
        env.parts.habits.soft_delete(gone.id, env.clock.now())
        check(env, a, "2026-10-21")
        default = await get_json(env, "/habits")
        by = {s: await get_json(env, f"/habits?status={s}") for s in ("active", "paused", "archived", "all")}
        past = await get_json(env, "/habits?date=2026-10-21")
        last_week = await get_json(env, "/habits?date=2026-10-18")

    for body in (default, *by.values(), past, last_week):
        _validate("HabitsList", body)
    assert (default["date"], default["week"]) == ("2026-10-24", "2026-W43")
    assert default == by["active"] and [h["id"] for h in default["items"]] == [a.id]
    assert [h["id"] for h in by["paused"]["items"]] == [p.id]
    assert [h["id"] for h in by["archived"]["items"]] == [r.id]
    assert [h["id"] for h in by["all"]["items"]] == [a.id, p.id, r.id]  # 삭제된 습관은 없다
    assert (past["date"], past["items"][0]["checked"], past["items"][0]["week_count"]) == ("2026-10-21", True, 1)
    assert default["items"][0]["checked"] is False
    assert (last_week["week"], last_week["items"][0]["week_count"]) == ("2026-W42", 0)


@pytest.mark.parametrize("query", [
    "date=2026-1-24", "date=2026-02-30", "date=오늘", "status=done", "status=", "status=ACTIVE",
])
async def test_get_habits_bad_date_400(tmp_path, query):
    async with BeEnv.start(tmp_path, start=SAT) as env:
        resp = await env.get(f"/habits?{query}")
        body = await resp.json()
    assert resp.status == 400
    _validate("Error", body)
    assert body["error"]["code"] == "invalid_request"
    assert "2026" not in body["error"]["message"] and "done" not in body["error"]["message"]


# --- 슬라이스 2: GET /habits/{id} ---


async def test_habit_history_weeks_default_4_and_bounds(tmp_path):
    async with BeEnv.start(tmp_path, start=SAT) as env:
        h = habit(env, "운동", kind="weekly", target=3)
        for d in ("2026-09-27", "2026-09-28", "2026-10-01", "2026-10-13", "2026-10-20", "2026-10-24"):
            check(env, h, d)
        default = await get_json(env, f"/habits/{h.id}")
        one = await get_json(env, f"/habits/{h.id}?weeks=1")
        twelve = await get_json(env, f"/habits/{h.id}?weeks=12")
        bad = {}
        for w in ("0", "13", "-1", "abc", "", "4.0"):
            resp = await env.get(f"/habits/{h.id}?weeks={w}")
            bad[w] = (resp.status, (await resp.json())["error"]["code"])

    for body in (default, one, twelve):
        _validate("HabitHistory", body)
    assert (default["from"], default["to"]) == ("2026-09-28", "2026-10-24")  # 10/24(토), weeks=4 → 9/28(월)
    assert default["checked_dates"] == ["2026-09-28", "2026-10-01", "2026-10-13", "2026-10-20", "2026-10-24"]
    # 체크가 있는 주만(W42 10/12~18은 1, W41은 없음)
    assert default["weeks"] == [
        {"week": "2026-W40", "count": 2}, {"week": "2026-W42", "count": 1}, {"week": "2026-W43", "count": 2},
    ]
    assert default["habit"]["id"] == h.id and default["habit"]["checked"] is True
    assert default["habit"]["week_count"] == 2
    assert (one["from"], one["checked_dates"]) == ("2026-10-19", ["2026-10-20", "2026-10-24"])
    assert twelve["from"] == "2026-08-03" and len(twelve["checked_dates"]) == 6
    assert bad == {w: (400, "invalid_request") for w in bad}


async def test_habit_history_deleted_404(tmp_path):
    async with BeEnv.start(tmp_path, start=SAT) as env:
        h = habit(env, "지운 습관")
        archived = habit(env, "그만둔 습관", status="archived")
        env.parts.habits.soft_delete(h.id, env.clock.now())
        resp = await env.get(f"/habits/{h.id}")
        body = await resp.json()
        missing = await env.get("/habits/999")
        bad_id = await env.get("/habits/abc")
        kept = await get_json(env, f"/habits/{archived.id}")

    assert resp.status == 404 and body == {"error": {"code": "not_found", "message": "없는 습관이에요."}}
    assert missing.status == 404 and bad_id.status == 400
    assert kept["habit"]["status"] == "archived"  # 그만둔 습관의 기록은 남는다


async def test_times_are_utc(tmp_path):
    """새벽 01:30(UTC 전날 16:30)은 논리적 전날이다. 습관 응답의 시각은 UTC `Z`이고 오프셋 붙은 시각은 없다."""
    async with BeEnv.start(tmp_path, start=kst(2026, 10, 25, 1, 30)) as env:
        h = habit(env, "운동")
        status, checked = await env.action("check_habit", {"id": h.id})
        listed = await get_json(env, "/habits")
        history = await get_json(env, f"/habits/{h.id}")
        today = await get_json(env, "/today")
        _, ask = await env.action("set_habit_status", {"id": h.id, "status": "archived"})

    assert status == 200 and checked["result"]["date"] == "2026-10-24"
    assert listed["date"] == "2026-10-24" and listed["items"][0]["checked"] is True
    assert history["to"] == "2026-10-24" and history["checked_dates"] == ["2026-10-24"]
    assert today["habits"][0]["checked"] is True
    assert ask["expires_at"] == "2026-10-24T16:40:00Z"
    for body in (checked, listed, history, today, ask):
        assert "+09:00" not in json.dumps(body) and "+00:00" not in json.dumps(body)


# --- 슬라이스 3: /actions ---


async def test_actions_check_habit_applied_with_xp_3_and_undo_id(tmp_path):
    async with BeEnv.start(tmp_path, start=SAT) as env:
        h = habit(env, "운동")
        status, body = await env.action("check_habit", {"id": h.id})
        (row,) = [r for r in env.activity() if r["kind"] == "habit_checked"]
        _, again = await env.action("check_habit", {"id": h.id})
        _, past = await env.action("check_habit", {"id": h.id, "date": "2026-10-22"})
        _, off = await env.action("uncheck_habit", {"id": h.id})
        _, back = await env.action("check_habit", {"id": h.id})
        _, bad = await env.action("check_habit", {"id": h.id, "date": "2026-10-25"})

    assert status == 200
    _validate("ActionApplied", body)
    assert body["activity_id"] == row["id"] and body["undo_id"] == row["id"]
    assert body["confirmation"] == "✓ 습관: 운동"
    assert body["xp"] == {"gained": 3, "level_up": None}  # X11
    assert body["result"] == {"habit": body["result"]["habit"], "date": "2026-10-24", "already": False}
    assert body["result"]["habit"]["checked"] is True and body["result"]["habit"]["week_count"] == 1
    assert (row["actor"], row["channel"], row["target"], row["risk"]) == ("user", "app", f"habit:{h.id}:2026-10-24", "low")
    # 이미 체크한 날: 바꾸지 않고 활동·경험치 없음
    assert again["status"] == "applied" and again["result"]["already"] is True
    assert again["activity_id"] is None and "undo_id" not in again and again["xp"]["gained"] == 0
    assert past["confirmation"] == "✓ 습관: 운동 (10/22)" and past["xp"]["gained"] == 3
    assert off["confirmation"] == "↩ 습관 체크 취소: 운동" and off["xp"]["gained"] == 0
    assert back["xp"]["gained"] == 0  # 같은 날짜는 한 번만
    assert bad["status"] == "rejected" and bad["error"]["message"] == "아직 오지 않은 날은 체크할 수 없어요."


async def test_actions_archive_needs_confirm_then_applies_with_token(tmp_path):
    async with BeEnv.start(tmp_path, start=SAT) as env:
        h = habit(env, "운동", kind="weekly", target=3)
        status, ask = await env.action("set_habit_status", {"id": h.id, "status": "archived"})
        before = env.parts.habits.get(h.id).status
        rows_before = [r["kind"] for r in env.activity()]
        status2, done = await env.action(
            "set_habit_status", {"id": h.id, "status": "archived"}, confirm_token=ask["confirm_token"]
        )
        after = env.parts.habits.get(h.id).status
        (row,) = [r for r in env.activity() if r["kind"] == "habit_status_set"]
        token = env.conn.execute("SELECT * FROM pending_confirms WHERE token = ?", (ask["confirm_token"],)).fetchone()

    assert status == 200
    _validate("ActionNeedsConfirm", ask)
    assert ask["status"] == "needs_confirm" and ask["summary"] == ARCHIVE_ASK
    assert before == "active" and rows_before == []
    assert status2 == 200 and done["status"] == "applied"
    assert done["confirmation"] == "✓ 습관 그만두기: 운동"
    assert after == "archived" and token["resolution"] == "applied" and row["risk"] == "confirm"


async def test_actions_archive_token_stale_after_habit_changes(tmp_path):
    async with BeEnv.start(tmp_path, start=SAT) as env:
        h = habit(env, "운동")
        _, ask = await env.action("set_habit_status", {"id": h.id, "status": "archived"})
        env.clock.advance(minutes=1)
        await env.action("update_habit", {"id": h.id, "title": "달리기"})
        status, body = await env.action(
            "set_habit_status", {"id": h.id, "status": "archived"}, confirm_token=ask["confirm_token"]
        )
        after = env.parts.habits.get(h.id).status

    assert status == 409 and body["error"]["code"] == "conflict"
    assert after == "active"


async def test_actions_pause_applies_directly(tmp_path):
    async with BeEnv.start(tmp_path, start=SAT) as env:
        h = habit(env, "운동")
        status, body = await env.action("set_habit_status", {"id": h.id, "status": "paused"})
        _, again = await env.action("set_habit_status", {"id": h.id, "status": "paused"})
        _, resume = await env.action("set_habit_status", {"id": h.id, "status": "active"})
        _, archived_twice = await env.action("set_habit_status", {"id": 999, "status": "archived"})
        confirms = env.conn.execute("SELECT COUNT(*) FROM pending_confirms").fetchone()[0]

    assert status == 200 and body["status"] == "applied" and body["undo_id"] == body["activity_id"]
    assert body["confirmation"] == "✓ 습관 쉬어 가기: 운동" and body["xp"]["gained"] == 0
    assert again["result"]["already"] is True and again["activity_id"] is None
    assert resume["confirmation"] == "✓ 습관 다시 시작: 운동"
    # 없는 습관의 그만두기는 확인을 묻지 않고 도구가 거절한다
    assert archived_twice["status"] == "rejected" and archived_twice["error"]["message"] == "없는 습관이에요."
    assert confirms == 0


@pytest.mark.parametrize(("actor", "channel"), [("user", "telegram"), ("secretary", "scheduler")])
async def test_telegram_and_scheduler_archive_no_confirm(tmp_path, actor, channel):
    async with BeEnv.start(tmp_path, start=SAT) as env:
        h = habit(env, "운동")
        res = env.parts.dispatcher.apply_action(
            ActionRequest("set_habit_status", {"id": h.id, "status": "archived"}, actor=actor, channel=channel)
        )
        after = env.parts.habits.get(h.id).status
        confirms = env.conn.execute("SELECT COUNT(*) FROM pending_confirms").fetchone()[0]

    assert res.status == "applied" and res.body["confirmation"] == "✓ 습관 그만두기: 운동"
    assert after == "archived" and confirms == 0


async def test_actions_add_and_update_habit(tmp_path):
    async with BeEnv.start(tmp_path, start=SAT) as env:
        _, added = await env.action("add_habit", {"title": " 운동 ", "area": "health", "kind": "weekly",
                                                  "target_per_week": 3})
        hid = added["result"]["id"]
        _, dup = await env.action("add_habit", {"title": "운동", "area": "health", "kind": "daily"})
        _, upd = await env.action("update_habit", {"id": hid, "target_per_week": 2})
        status, bad = await env.action("update_habit", {"id": hid, "colour": "red"})

    assert added["status"] == "applied" and added["confirmation"] == "✓ 습관 추가: 운동 (주 3회)"
    assert added["result"]["title"] == "운동" and added["undo_id"] == added["activity_id"]
    assert dup["status"] == "rejected" and dup["error"]["message"] == "이미 있는 습관이에요."
    assert upd["confirmation"] == "✓ 습관 고침: 운동 (주 2회)"
    assert status == 400 and bad["error"]["code"] == "invalid_request"


async def test_run_turn_archive_token_applies_through_actions(tmp_path):
    """회차 차례의 그만두기·고치기는 확인 토큰만 만든다(규칙 H7). 그 토큰은 `/actions`로 적용한다."""
    async with BeEnv.start(tmp_path, start=SAT_EVENING, script=[FakeTurn([], "꾸민 회차 본문")]) as env:
        await env.tick()
        h = habit(env, "운동")
        run = run_row(env)
        ctx = RunContext(conversation_id=None, run_id=run["id"], activity_channel="scheduler", channel="telegram")
        out = env.parts.tools.set_habit_status(ctx, id=h.id, status="archived")
        upd = env.parts.tools.update_habit(ctx, id=h.id, kind="weekly", target_per_week=2)
        env.clock.advance(minutes=5)
        confirms = ConfirmsRepo(env.conn, env.clock)
        a_upd, a_out = confirms.get(upd["confirm_token"]).args, confirms.get(out["confirm_token"]).args
        status, body = await env.action("update_habit", a_upd, confirm_token=upd["confirm_token"])
        # 고치기가 그 습관(`habit:<id>`)을 바꿨다: 먼저 만든 그만두기 토큰은 stale
        status2, body2 = await env.action("set_habit_status", a_out, confirm_token=out["confirm_token"])
        got = env.parts.habits.get(h.id)
        answered = run_row(env)

    assert (out["status"], upd["status"]) == ("needs_confirm", "needs_confirm")
    assert out["summary"] == ARCHIVE_ASK and a_out == {"id": h.id, "status": "archived"}
    assert status == 200 and body["confirmation"] == "✓ 습관 고침: 운동 (주 2회)"
    assert status2 == 409 and body2["error"]["code"] == "conflict"
    assert (got.status, got.kind, got.target_per_week) == ("active", "weekly", 2)
    assert answered["answered_via"] == "app"  # 회차가 만든 토큰의 확인은 그 회차의 답


# --- 슬라이스 4: 앱 체크가 저녁 체크인의 답 ---


async def test_app_check_on_evening_date_marks_run_answered(tmp_path):
    async with BeEnv.start(tmp_path, start=SAT_EVENING, script=[FakeTurn([], "꾸민 회차 본문")]) as env:
        h = habit(env, "운동")
        await env.tick()
        env.clock.set(kst(2026, 10, 25, 0, 30))  # 자정이 지나도 답장 창 안, 논리적 날짜 10/24
        before = run_row(env)
        status, body = await env.action("check_habit", {"id": h.id})
        await env.drain()
        run = run_row(env)
        detail = await get_json(env, f"/checkins/{run['id']}")

    assert before["answered_at"] is None
    assert status == 200 and body["status"] == "applied"
    assert run["answered_via"] == "app"
    assert (detail["state"], detail["answered_via"]) == ("answered", "app")
    assert len(env.sender.cleared) == 1  # 앱에서 먼저 답했으니 텔레그램 버튼을 거둔다


async def test_app_check_other_date_does_not_answer(tmp_path):
    async with BeEnv.start(tmp_path, start=SAT_EVENING, script=[FakeTurn([], "꾸민 회차 본문")]) as env:
        h = habit(env, "운동")
        await env.tick()
        env.clock.set(kst(2026, 10, 24, 19, 0))
        await env.action("check_habit", {"id": h.id, "date": "2026-10-23"})
        await env.action("uncheck_habit", {"id": h.id, "date": "2026-10-23"})
        rejected = await env.action("check_habit", {"id": 999})
        await env.drain()
        mid = run_row(env)
        env.clock.set(kst(2026, 10, 25, 13, 0))  # 답장 창(10/25 04:00)이 지났다
        await env.action("check_habit", {"id": h.id, "date": "2026-10-24"})
        await env.drain()
        late = run_row(env)

    assert rejected[0] == 422
    assert mid["answered_at"] is None and late["answered_at"] is None
    assert env.sender.cleared == []


async def test_app_uncheck_on_evening_date_marks_run_answered(tmp_path):
    async with BeEnv.start(tmp_path, start=SAT_EVENING, script=[FakeTurn([], "꾸민 회차 본문")]) as env:
        h = habit(env, "운동")
        check(env, h, "2026-10-24")
        await env.tick()
        env.clock.set(kst(2026, 10, 24, 19, 0))
        status, _ = await env.action("uncheck_habit", {"id": h.id, "date": "2026-10-24"})
        await env.drain()
        run = run_row(env)

    assert status == 200 and run["answered_via"] == "app"


async def test_app_check_on_sunday_merged_review_marks_primary_answered(tmp_path):
    """일요일 10/25 18:00: 저녁 체크인을 주간 회고에 합쳐 한 메시지로 보낸다. 10/25 앱 체크는 그 묶음(primary)의 답이다."""
    sunday = kst(2026, 10, 25, 18, 0) + timedelta(seconds=30)
    async with BeEnv.start(tmp_path, start=sunday, script=[FakeTurn([], "꾸민 회고 본문")]) as env:
        h = habit(env, "운동")
        await env.tick()
        rows = env.conn.execute("SELECT * FROM runs ORDER BY id").fetchall()
        env.clock.set(kst(2026, 10, 25, 19, 0))
        status, body = await env.action("check_habit", {"id": h.id, "date": "2026-10-25"})
        await env.drain()
        after = {r["id"]: r for r in env.conn.execute("SELECT * FROM runs").fetchall()}

    primary = [r for r in rows if json.loads(r["merged_run_ids"] or "[]")]
    assert len(primary) == 1
    merged_ids = json.loads(primary[0]["merged_run_ids"])
    loops = {r["loop"] for r in rows if r["id"] in (primary[0]["id"], *merged_ids)}
    assert {"evening_checkin", "review"} <= loops
    assert status == 200 and body["status"] == "applied"
    assert after[primary[0]["id"]]["answered_via"] == "app"
    assert len(env.sender.cleared) == 1
