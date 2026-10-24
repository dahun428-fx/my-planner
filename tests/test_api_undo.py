"""되돌리기 `POST /activity/{id}/undo`(SP3-4 스펙 6.4.3, U1~U6)와 `GET /activity`(6.4.4). 내용은 꾸며 낸 것이다."""

import logging
from datetime import timedelta

import jsonschema
import pytest
from be_env import BeEnv
from test_dispatcher_messages import kst

from my_planner.api.models import schema_bundle
from my_planner.domain import RunContext
from my_planner.store.repos.activity import ActivityRepo
from my_planner.tools.actions import ActionRequest

SAT_1300 = kst(2026, 10, 24, 13, 0)  # 토요일 낮: 예정된 회차가 없다


def _validate(model, body):
    jsonschema.Draft202012Validator(schema_bundle()["models"][model]).validate(body)


def _ctx():
    return RunContext(conversation_id=None, run_id=None)


async def _add(env, title="운동", **extra):
    status, body = await env.action("add_task", {"title": title, "areas": ["health"], **extra})
    assert status == 200, body
    return body["result"]["id"]


async def _apply(env, action, args):
    status, body = await env.action(action, args)
    assert (status, body["status"]) == (200, "applied"), body
    return body


def _propose(env, *titles):
    out = env.parts.tools.propose_tasks(_ctx(), tasks=[{"title": t, "areas": ["health"]} for t in titles])
    return [t["id"] for t in out["proposed"]]


async def undo(env, aid, client_msg_id=None):
    body = {"client_msg_id": client_msg_id or f"undo-{next(env._ids)}"}
    resp = await env.post(f"/activity/{aid}/undo", json=body)
    return resp.status, await resp.json()


async def activity_list(env, query=""):
    resp = await env.get(f"/activity{query}")
    return resp.status, await resp.json()


def _row(env, aid):
    return env.conn.execute("SELECT * FROM activity WHERE id = ?", (aid,)).fetchone()


def _state(env):
    """되돌리기가 맞춰야 할 데이터 전부(살아 있는 할 일, 영역, 우선순위, 컨디션, 습관, 습관 체크). `updated_at`은 뺀다."""
    q = env.conn.execute
    tasks = [dict(r) for r in q("SELECT * FROM tasks WHERE deleted_at IS NULL ORDER BY id")]
    for t in tasks:
        del t["updated_at"]
    habits = [dict(r) for r in q("SELECT * FROM habits WHERE deleted_at IS NULL ORDER BY id")]
    for h in habits:
        del h["updated_at"]
    checks = [tuple(r) for r in q("SELECT habit_id, date, checked_at FROM habit_checks ORDER BY 1, 2")]
    areas = [tuple(r) for r in q(
        "SELECT a.task_id, a.area FROM task_areas a JOIN tasks t ON t.id = a.task_id "
        "WHERE t.deleted_at IS NULL ORDER BY a.task_id, a.area")]
    prios = [tuple(r) for r in q("SELECT cadence, period, rank, task_id FROM priorities ORDER BY 1, 2, 3")]
    conds = [tuple(r) for r in q("SELECT date, score, note, recorded_at FROM conditions ORDER BY date")]
    return {"tasks": tasks, "areas": areas, "priorities": prios, "conditions": conds, "habits": habits,
            "habit_checks": checks}


def _ledger(env):
    return [tuple(r) for r in env.conn.execute("SELECT * FROM status_xp_ledger ORDER BY id")]


# --- 종류별 되돌리기 (6.4.3 표) ---


async def _case_task_added(env):
    return "add_task", {"title": "운동", "areas": ["health"], "planned_for": "2026-10-24"}, "운동 추가"


async def _case_task_updated(env):
    a = await _add(env, scheduled_at="2026-10-24T18:00")
    return "update_task", {"id": a, "title": "아침 운동", "note": "꾸민 메모", "areas": ["health", "learning"],
                           "scheduled_at": "2026-10-25T07:00"}, "아침 운동 바꿈"


async def _case_task_moved(env):
    # 앱 통로에서 시각 있는 할 일을 옮기면 확인을 거친다(SP6 8장). 시각 있는 옮김의 되돌리기는 아래 텔레그램 시험
    a = await _add(env, planned_for="2026-10-24")
    return "move_task", {"id": a, "planned_for": "2026-10-26"}, "운동 옮김"


async def _case_task_completed(env):
    a = await _add(env, planned_for="2026-10-24")
    return "complete_task", {"id": a}, "운동 완료"


async def _case_task_reopened(env):
    a = await _add(env)
    env.clock.advance(minutes=3)
    await _apply(env, "complete_task", {"id": a})
    env.clock.advance(minutes=3)
    return "reopen_task", {"id": a}, "운동 다시 열기"


async def _case_task_dropped(env):
    a = await _add(env)
    await _apply(env, "set_priorities", {"cadence": "week", "period": "2026-W45", "task_ids": [a]})  # 지금 기간이 아니다
    return "drop_task", {"id": a}, "운동 내려놓음"


async def _case_tasks_confirmed(env):
    ids = _propose(env, "물 마시기", "스트레칭")
    return "confirm_tasks", {"ids": ids}, "물 마시기, 스트레칭 확정"


async def _case_priorities_set(env):
    a, b = await _add(env, "가"), await _add(env, "나")
    await _apply(env, "set_priorities", {"cadence": "week", "period": "2026-W43", "task_ids": [a]})
    return "set_priorities", {"cadence": "week", "period": "2026-W43", "task_ids": [b, a]}, "우선순위(이번 주)"


async def _case_condition_recorded(env):
    await _apply(env, "record_condition", {"score": 3, "note": "꾸민 메모"})
    env.clock.advance(minutes=7)
    return "record_condition", {"score": 5}, "컨디션 5 기록"


# 습관(SP7 5.5): `/actions` 습관 동작은 SP7-03이 더한다. 여기서는 `/actions`와 같은 맥락으로 도구를 직접 부른다
HABIT = "tool:"


def _hctx():
    return RunContext(conversation_id=None, run_id=None, actor="user", channel="app")


def _habit_call(env, name, **args):
    """습관 도구 하나를 사용자(앱)로 부른다. `/actions` 응답처럼 `activity_id`, `undo_id`를 돌려준다."""
    ctx = _hctx()
    out = getattr(env.parts.tools, name)(ctx, **args)
    assert "error" not in out, out
    aid = ctx.activity_ids[-1] if ctx.activity_ids else None
    return {"result": out, "activity_id": aid, "undo_id": aid if aid in ctx.undo_ids else None}


def _habit(env, title="운동", **extra):
    args = {"area": "health", "kind": "weekly", "target_per_week": 3, **extra}
    return _habit_call(env, "add_habit", title=title, **args)["result"]["id"]


async def _case_habit_added(env):
    return HABIT + "add_habit", {"title": "운동", "area": "health", "kind": "weekly", "target_per_week": 3}, "운동 습관 추가"


async def _case_habit_updated(env):
    h = _habit(env)
    return HABIT + "update_habit", {"id": h, "title": "아침 운동", "area": "learning", "target_per_week": 2}, (
        "아침 운동 습관 고침")


async def _case_habit_status_set(env):
    h = _habit(env)
    return HABIT + "set_habit_status", {"id": h, "status": "paused"}, "운동 습관 쉬어 가기"


async def _case_habit_checked(env):
    h = _habit(env)
    return HABIT + "check_habit", {"id": h, "date": "2026-10-22"}, "운동 습관 체크"


async def _case_habit_unchecked(env):
    h = _habit(env)
    _habit_call(env, "check_habit", id=h)
    env.clock.advance(minutes=5)
    return HABIT + "uncheck_habit", {"id": h}, "운동 습관 체크 취소"


CASES = {
    "task_added": _case_task_added,
    "task_updated": _case_task_updated,
    "task_moved": _case_task_moved,
    "task_completed": _case_task_completed,
    "task_reopened": _case_task_reopened,
    "task_dropped": _case_task_dropped,
    "tasks_confirmed": _case_tasks_confirmed,
    "priorities_set": _case_priorities_set,
    "condition_recorded": _case_condition_recorded,
    "habit_added": _case_habit_added,
    "habit_updated": _case_habit_updated,
    "habit_status_set": _case_habit_status_set,
    "habit_checked": _case_habit_checked,
    "habit_unchecked": _case_habit_unchecked,
}


@pytest.mark.parametrize("kind", list(CASES))
async def test_undo_each_kind(tmp_path, kind):
    async with BeEnv.start(tmp_path, start=SAT_1300) as env:
        action, args, gist = await CASES[kind](env)
        before = _state(env)
        env.clock.advance(minutes=1)
        if action.startswith(HABIT):
            body = _habit_call(env, action.removeprefix(HABIT), **args)
        else:
            body = await _apply(env, action, args)
        assert body["undo_id"] == body["activity_id"]
        assert _row(env, body["activity_id"])["kind"] == kind
        changed = _state(env)
        ledger_before = _ledger(env)  # 적용이 쌓은 경험치(완료, 컨디션 등)까지
        env.clock.advance(minutes=1)
        status, out = await undo(env, body["undo_id"])
        after = _state(env)
        original = _row(env, body["activity_id"])
        new = _row(env, out["activity_id"])
        repo = ActivityRepo(env.conn, env.clock)
        new_targets, old_targets = repo.targets(new["id"]), repo.targets(original["id"])
        ledger_after = _ledger(env)

    assert changed != before
    assert status == 200, out
    _validate("UndoResponse", out)
    assert out == {"status": "undone", "activity_id": new["id"], "undone": original["id"],
                   "confirmation": f"↩ 되돌림: {gist}"}
    assert after == before
    assert original["undone_by"] == new["id"] and original["undone_at"] == new["at"]
    assert (new["kind"], new["undo_json"], new["risk"], new["actor"], new["channel"]) == (
        "undo", None, "low", "user", "app")
    assert new["summary"] == out["confirmation"] and new["target"] == original["target"]
    # 되돌리기 행은 원래 행의 대상을 모두 적는다(목록 변경의 할 일 대상은 지켜보는 대상으로)
    assert new_targets == old_targets
    assert ledger_after == ledger_before  # U6: 되돌리기는 원장을 건드리지 않는다


async def test_undo_task_added_soft_deletes(tmp_path):
    async with BeEnv.start(tmp_path, start=SAT_1300) as env:
        body = await _apply(env, "add_task", {"title": "운동", "areas": ["health"]})
        env.clock.advance(minutes=2)
        await undo(env, body["undo_id"])
        row = env.conn.execute("SELECT * FROM tasks WHERE id = ?", (body["result"]["id"],)).fetchone()
        gone = env.parts.tasks.get(body["result"]["id"])

    assert row["deleted_at"] == "2026-10-24T04:02:00.000000+00:00" and gone is None


async def test_undo_condition_without_prior_deletes_row(tmp_path):
    async with BeEnv.start(tmp_path, start=SAT_1300) as env:
        body = await _apply(env, "record_condition", {"score": 2})
        status, _ = await undo(env, body["undo_id"])
        count = env.conn.execute("SELECT count(*) FROM conditions").fetchone()[0]

    assert status == 200 and count == 0


async def test_undo_task_dropped_restores_priority_only_if_slot_empty(tmp_path):
    week = {"cadence": "week", "period": "2026-W45"}
    async with BeEnv.start(tmp_path, start=SAT_1300) as env:
        a, b = await _add(env, "가"), await _add(env, "나")
        await _apply(env, "set_priorities", {**week, "task_ids": [a]})
        dropped = await _apply(env, "drop_task", {"id": a})
        env.parts.tasks.set_priorities("week", "2026-W45", [b])  # 활동 없이 그 칸이 찼다
        n_rows = len(env.activity())
        status, body = await undo(env, dropped["undo_id"])
        still = (env.parts.tasks.get(a).status.value, [t.id for t in env.parts.tasks.priorities("week", "2026-W45")])
        mid_rows = len(env.activity())
        undone_at = _row(env, dropped["activity_id"])["undone_at"]

        env.parts.tasks.set_priorities("week", "2026-W45", [])  # 칸이 비었다
        status2, body2 = await undo(env, dropped["undo_id"])
        restored = (env.parts.tasks.get(a).status.value, env.parts.tasks.priority_rows(a))

    assert status == 409 and body["error"]["code"] == "superseded"
    assert still == ("dropped", [b]) and mid_rows == n_rows and undone_at is None
    assert status2 == 200 and body2["status"] == "undone"
    assert restored == ("open", [("week", "2026-W45", 1)])


async def test_undo_tasks_confirmed_restarts_draft_clock(tmp_path):
    async with BeEnv.start(tmp_path, start=SAT_1300) as env:
        (d,) = _propose(env, "물 마시기")
        env.clock.advance(days=2)
        confirmed = await _apply(env, "confirm_tasks", {"ids": [d]})
        status, _ = await undo(env, confirmed["undo_id"])
        assert status == 200 and env.parts.tasks.get(d).status.value == "draft"

        def expire():
            now = env.clock.now()
            return env.parts.dispatcher.apply_action(ActionRequest(
                "expire_drafts", {"older_than": now - timedelta(days=3)}, actor="secretary", channel="scheduler"))

        env.clock.advance(days=2, hours=23)
        expire()
        mid = env.parts.tasks.get(d).status.value
        drafts = await (await env.get("/drafts")).json()
        env.clock.advance(hours=1)
        expire()
        end = env.parts.tasks.get(d).status.value

    assert mid == "draft" and [i["todo"]["id"] for i in drafts["items"]] == [d]
    assert drafts["items"][0]["expires_at"] == "2026-10-29T04:00:00Z"  # 되돌린 시각(10/26 13:00)부터 3일
    assert end == "dropped"


async def test_undo_and_undone_at_atomic(tmp_path, monkeypatch):
    async with BeEnv.start(tmp_path, start=SAT_1300) as env:
        tid = await _add(env)
        done = await _apply(env, "complete_task", {"id": tid})
        n_rows = len(env.activity())

        def boom(*a, **kw):
            raise RuntimeError("boom")

        monkeypatch.setattr(env.parts.activity, "mark_undone", boom)
        status, body = await undo(env, done["undo_id"], client_msg_id="u-atomic")
        state = (env.parts.tasks.get(tid).status.value, _row(env, done["activity_id"])["undone_at"], len(env.activity()))
        n_targets = env.conn.execute("SELECT count(*) FROM activity_targets").fetchone()[0]
        stored = env.conn.execute("SELECT count(*) FROM api_idempotency WHERE client_msg_id = 'u-atomic'").fetchone()[0]
        monkeypatch.undo()
        status2, body2 = await undo(env, done["undo_id"], client_msg_id="u-atomic")
        final = env.parts.tasks.get(tid).status.value

    assert status == 500 and body["error"]["code"] == "internal"
    assert state == ("done", None, n_rows) and n_targets == n_rows and stored == 0
    assert status2 == 200 and body2["status"] == "undone" and final == "open"


# --- U1~U5 ---


async def test_u1_not_undoable(tmp_path):
    async with BeEnv.start(tmp_path, start=SAT_1300) as env:
        a, b = await _add(env, "가"), await _add(env, "나")
        q = {"cadence": "quarter", "period": "2026-Q4"}
        await _apply(env, "set_priorities", {**q, "task_ids": [a]})
        _, nc = await env.action("set_priorities", {**q, "task_ids": [b]})
        st, confirmed = await env.action("set_priorities", {**q, "task_ids": [b]}, confirm_token=nc["confirm_token"])
        assert st == 200 and "undo_id" not in confirmed
        _propose(env, "초안")
        (proposed,) = [r["id"] for r in env.activity() if r["kind"] == "tasks_proposed"]
        _, nc2 = await env.action("set_priorities", {**q, "task_ids": [a]})
        declined = await _apply(env, "decline_confirm", {"confirm_token": nc2["confirm_token"]})
        before = _state(env)
        results = [await undo(env, i) for i in (confirmed["activity_id"], proposed, declined["activity_id"])]
        after = _state(env)
        kinds = [r["kind"] for r in env.activity()]

    for status, body in results:
        assert status == 422
        _validate("Error", body)
        assert body["error"] == {"code": "not_undoable", "message": "되돌릴 수 없는 변경이에요."}
    assert after == before and "undo" not in kinds


async def test_u2_24h_boundary(tmp_path):
    async with BeEnv.start(tmp_path, start=SAT_1300) as env:
        a, b = await _add(env, "가"), await _add(env, "나")
        ca = await _apply(env, "complete_task", {"id": a})
        cb = await _apply(env, "complete_task", {"id": b})
        env.clock.advance(hours=23, minutes=59, seconds=59)
        status_a, _ = await undo(env, ca["undo_id"])
        _, listing_before = await activity_list(env)
        env.clock.advance(seconds=1)  # 딱 24시간
        status_b, body_b = await undo(env, cb["undo_id"])
        _, listing_after = await activity_list(env)
        still = env.parts.tasks.get(b).status.value

    by_id_before = {i["id"]: i for i in listing_before["items"]}
    by_id_after = {i["id"]: i for i in listing_after["items"]}
    assert status_a == 200
    assert by_id_before[cb["activity_id"]]["undo_id"] == cb["activity_id"]
    assert status_b == 409 and body_b["error"] == {"code": "undo_expired",
                                                   "message": "되돌릴 수 있는 24시간이 지났어요."}
    assert by_id_after[cb["activity_id"]]["undo_id"] is None and still == "done"


async def test_undo_scheduled_move_from_telegram(tmp_path):
    """텔레그램 통로는 시각 있는 할 일도 바로 옮긴다. 그 되돌리기는 날짜와 시각을 함께 되돌린다."""
    from my_planner.tools.actions import ActionRequest

    async with BeEnv.start(tmp_path, start=SAT_1300) as env:
        a = await _add(env, scheduled_at="2026-10-24T18:00")
        before = _state(env)
        env.clock.advance(minutes=1)
        res = env.parts.dispatcher.apply_action(
            ActionRequest("move_task", {"id": a, "planned_for": "2026-10-26"}, actor="user", channel="telegram")
        )
        moved = env.parts.tasks.get(a)
        env.clock.advance(minutes=1)
        status, out = await undo(env, res.body["undo_id"])
        after = _state(env)

    assert res.status == "applied" and moved.planned_for.isoformat() == "2026-10-26"
    assert status == 200 and out["confirmation"] == "↩ 되돌림: 운동 옮김"
    assert after == before


async def test_u3_superseded_chain(tmp_path):
    async with BeEnv.start(tmp_path, start=SAT_1300) as env:
        a = await _add(env, planned_for="2026-10-24")
        done = await _apply(env, "complete_task", {"id": a})
        # 같은 시각, 더 나중 행(끝난 할 일은 옮길 수 없어 메모를 고친다, SP6 8장)
        moved = await _apply(env, "update_task", {"id": a, "note": "꾸민 메모"})
        s1, b1 = await undo(env, done["undo_id"])
        s2, _ = await undo(env, moved["undo_id"])
        s3, b3 = await undo(env, done["undo_id"])  # 되돌리기 자체도 활동이다
        task = env.parts.tasks.get(a)

        _, listing = await activity_list(env)

    superseded = {"code": "superseded", "message": "그 뒤에 바뀐 내용이 있어서 되돌릴 수 없어요."}
    assert (s1, b1["error"]) == (409, superseded)
    assert s2 == 200
    assert (s3, b3["error"]) == (409, superseded)
    assert task.status.value == "done" and task.planned_for.isoformat() == "2026-10-24"
    by_id = {i["id"]: i for i in listing["items"]}
    assert by_id[done["activity_id"]]["undo_id"] is None


async def test_undo_tasks_confirmed_partial(tmp_path):
    """6.4.3: 확정한 할 일 가운데 아직 `open`이고 나중 변경이 없는 것만 `draft`로. 나머지는 그대로 둔다."""
    async with BeEnv.start(tmp_path, start=SAT_1300) as env:
        d1, d2, d3 = _propose(env, "물 마시기", "스트레칭", "산책")
        confirmed = await _apply(env, "confirm_tasks", {"ids": [d1, d2, d3]})
        done2 = await _apply(env, "complete_task", {"id": d2})  # 하나는 나중에 바뀌었다
        _, listing = await activity_list(env)
        status, body = await undo(env, confirmed["undo_id"])
        statuses = [env.parts.tasks.get(i).status.value for i in (d1, d2, d3)]
        undo_targets = ActivityRepo(env.conn, env.clock).targets(body["activity_id"])
        undo_row_summary = _row(env, body["activity_id"])["summary"]
        # 되돌리기 행은 되돌린 할 일만 적는다: 그대로 둔 할 일의 완료는 여전히 되돌릴 수 있다
        status2, _ = await undo(env, done2["undo_id"])
        d2_after = env.parts.tasks.get(d2).status.value

    by_id = {i["id"]: i for i in listing["items"]}
    assert by_id[confirmed["activity_id"]]["undo_id"] == confirmed["activity_id"]
    assert status == 200 and body["status"] == "undone"
    assert statuses == ["draft", "done", "draft"]
    assert undo_targets == [f"task:{d1}", f"task:{d3}"]
    assert body["confirmation"] == "↩ 되돌림: 물 마시기, 산책 확정" == undo_row_summary
    assert status2 == 200 and d2_after == "open"


async def test_undo_tasks_confirmed_superseded_only_when_none_left(tmp_path):
    async with BeEnv.start(tmp_path, start=SAT_1300) as env:
        d1, d2 = _propose(env, "물 마시기", "스트레칭")
        confirmed = await _apply(env, "confirm_tasks", {"ids": [d1, d2]})
        await _apply(env, "complete_task", {"id": d1})
        await _apply(env, "move_task", {"id": d2, "planned_for": "2026-10-26"})
        _, listing = await activity_list(env)
        n_rows = len(env.activity())
        status, body = await undo(env, confirmed["undo_id"])
        statuses = [env.parts.tasks.get(i).status.value for i in (d1, d2)]
        rows = len(env.activity())

    by_id = {i["id"]: i for i in listing["items"]}
    assert by_id[confirmed["activity_id"]]["undo_id"] is None
    assert status == 409 and body["error"]["code"] == "superseded"
    assert statuses == ["done", "open"] and rows == n_rows


async def test_undo_tasks_confirmed_task_closed_without_activity_superseded(tmp_path):
    """나중 활동은 없지만 할 일이 이미 `open`이 아니면 돌리지 않는다. 하나도 못 돌리면 superseded(쓴 것 없음)."""
    async with BeEnv.start(tmp_path, start=SAT_1300) as env:
        (d,) = _propose(env, "물 마시기")
        confirmed = await _apply(env, "confirm_tasks", {"ids": [d]})
        env.parts.tasks.set_status(d, "done")  # 활동 없이
        status, body = await undo(env, confirmed["undo_id"])
        task = env.parts.tasks.get(d).status.value

    assert status == 409 and body["error"]["code"] == "superseded" and task == "done"


# --- priorities_set: 할 일 대상은 지켜보기만 한다(U3은 목록 대상만) ---

WEEK = {"cadence": "week", "period": "2026-W43"}


async def test_undo_complete_after_list_dropped_it_p1(tmp_path):
    """P1: 목록 [a, b] → a 완료 → 목록 [b] → a 완료 되돌리기. 목록 변경은 a를 바꾼 것이 아니다."""
    async with BeEnv.start(tmp_path, start=SAT_1300) as env:
        a, b = await _add(env, "가"), await _add(env, "나")
        await _apply(env, "set_priorities", {**WEEK, "task_ids": [a, b]})
        done = await _apply(env, "complete_task", {"id": a})
        await _apply(env, "set_priorities", {**WEEK, "task_ids": [b]})
        status, body = await undo(env, done["undo_id"])
        task = env.parts.tasks.get(a).status.value
        listed = [t.id for t in env.parts.tasks.priorities("week", "2026-W43")]

    assert status == 200 and body["status"] == "undone"
    assert task == "open" and listed == [b]


async def test_undo_list_after_listed_task_completed_p2(tmp_path):
    """P2: 목록 [a] → a 완료 → 목록 되돌리기(이전 목록은 비어 있었다). 할 일 완료는 목록을 바꾼 것이 아니다."""
    async with BeEnv.start(tmp_path, start=SAT_1300) as env:
        a = await _add(env, "가")
        listed = await _apply(env, "set_priorities", {**WEEK, "task_ids": [a]})
        await _apply(env, "complete_task", {"id": a})
        status, body = await undo(env, listed["undo_id"])
        rows = env.parts.tasks.priority_rows(a)
        task = env.parts.tasks.get(a).status.value

    assert status == 200 and body["status"] == "undone"
    assert rows == [] and task == "done"


async def test_undo_list_superseded_when_old_list_task_not_open(tmp_path):
    """이전 목록의 할 일이 지금 목록에 오를 수 없으면(완료, 내려놓음, 지움) superseded이고 목록은 그대로다."""
    async with BeEnv.start(tmp_path, start=SAT_1300) as env:
        a, b = await _add(env, "가"), await _add(env, "나")
        await _apply(env, "set_priorities", {**WEEK, "task_ids": [a]})
        second = await _apply(env, "set_priorities", {**WEEK, "task_ids": [b]})
        await _apply(env, "complete_task", {"id": a})
        status, body = await undo(env, second["undo_id"])
        listed = [t.id for t in env.parts.tasks.priorities("week", "2026-W43")]
        undone_at = _row(env, second["activity_id"])["undone_at"]

    assert status == 409 and body["error"]["code"] == "superseded"
    assert listed == [b] and undone_at is None


async def test_u4_double_undo_already_undone_same_with_same_client_msg_id(tmp_path):
    async with BeEnv.start(tmp_path, start=SAT_1300) as env:
        a = await _add(env)
        done = await _apply(env, "complete_task", {"id": a})
        s1, first = await undo(env, done["undo_id"], client_msg_id="u-1")
        n_rows = len(env.activity())
        env.clock.advance(minutes=5)
        s2, same_id = await undo(env, done["undo_id"], client_msg_id="u-1")
        s3, new_id = await undo(env, done["undo_id"], client_msg_id="u-2")
        s4, new_id_again = await undo(env, done["undo_id"], client_msg_id="u-2")
        rows = env.activity()
        task = env.parts.tasks.get(a).status.value

    assert s1 == 200 and first["status"] == "undone"
    expected = {"status": "already_undone", "activity_id": first["activity_id"]}
    assert (s2, same_id) == (200, expected) == (s3, new_id) == (s4, new_id_again)
    _validate("UndoResponse", same_id)
    assert len(rows) == n_rows and task == "open"


async def test_u5_undo_of_undo_not_undoable(tmp_path):
    async with BeEnv.start(tmp_path, start=SAT_1300) as env:
        a = await _add(env)
        done = await _apply(env, "complete_task", {"id": a})
        _, first = await undo(env, done["undo_id"])
        status, body = await undo(env, first["activity_id"])
        _, listing = await activity_list(env)
        task = env.parts.tasks.get(a).status.value

    assert status == 422 and body["error"]["code"] == "not_undoable"
    (row,) = [i for i in listing["items"] if i["kind"] == "undo"]
    assert row["undo_id"] is None and row["undone_at"] is None and task == "open"


# --- GET /activity (6.4.4) ---


async def test_activity_list_shape_order_and_undo_id_now(tmp_path):
    async with BeEnv.start(tmp_path, start=SAT_1300) as env:
        a = await _add(env, "가")  # 04:00Z
        env.clock.advance(minutes=1)
        b = await _add(env, "나")  # 04:01Z
        env.clock.advance(minutes=1)
        done = await _apply(env, "complete_task", {"id": a})  # 04:02Z
        await _apply(env, "complete_task", {"id": b})  # 04:02Z, 같은 시각
        env.clock.advance(minutes=1)
        _, u = await undo(env, done["undo_id"])  # 04:03Z
        ids = [r["id"] for r in env.activity()]

        status, full = await activity_list(env)
        _, page1 = await activity_list(env, "?limit=2")
        _, page2 = await activity_list(env, f"?limit=2&since={page1['next_since']}")
        _, page3 = await activity_list(env, f"?limit=2&since={page2['next_since']}")
        _, d1 = await activity_list(env, "?order=desc&limit=2")
        _, d2 = await activity_list(env, f"?order=desc&limit=2&before={d1['next_before']}")
        _, d3 = await activity_list(env, f"?order=desc&limit=2&before={d2['next_before']}")
        _, d_since = await activity_list(env, "?order=desc&since=2026-10-24T04:01:00Z")
        _, empty = await activity_list(env, "?since=2026-10-24T04:03:00Z")

    assert status == 200
    _validate("ActivityResponse", full)
    add_a, add_b, done_a, done_b, undo_a = ids
    assert [i["id"] for i in full["items"]] == ids
    first = full["items"][0]
    assert set(first) == {"id", "at", "actor", "channel", "kind", "summary", "risk", "undo_id", "undone_at"}
    assert first == {"id": add_a, "at": "2026-10-24T04:00:00Z", "actor": "user", "channel": "app",
                     "kind": "task_added", "summary": "✓ 추가: 가", "risk": "low", "undo_id": None, "undone_at": None}
    undo_ids = {i["id"]: i["undo_id"] for i in full["items"]}
    # 가 추가는 그 뒤 완료가 덮었다. 가 완료는 되돌렸다. 되돌리기는 되돌릴 수 없다
    assert undo_ids == {add_a: None, add_b: None, done_a: None, done_b: done_b, undo_a: None}
    assert full["items"][2]["undone_at"] == "2026-10-24T04:03:00Z"
    assert full["next_since"] == "2026-10-24T04:03:00Z" and full["next_before"] is None
    assert u["activity_id"] == undo_a

    assert [i["id"] for i in page1["items"]] == [add_a, add_b] and page1["next_since"] == "2026-10-24T04:01:00Z"
    assert [i["id"] for i in page2["items"]] == [done_a, done_b] and page2["next_since"] == "2026-10-24T04:02:00Z"
    assert [i["id"] for i in page3["items"]] == [undo_a]
    assert page1["next_before"] is None
    assert [i["id"] for i in d1["items"]] == [undo_a, done_b] and d1["next_before"] == str(done_b)
    assert d1["next_since"] == "2026-10-24T04:03:00Z"
    assert [i["id"] for i in d2["items"]] == [done_a, add_b] and d2["next_before"] == str(add_b)
    assert [i["id"] for i in d3["items"]] == [add_a] and d3["next_before"] is None
    assert [i["id"] for i in d_since["items"]] == [undo_a, done_b, done_a]
    assert empty == {"items": [], "next_since": "2026-10-24T04:03:00Z", "next_before": None}


async def test_activity_asc_page_keeps_rows_with_same_at(tmp_path):
    """`next_since`는 시각이다. 같은 시각의 행이 쪽 경계에 걸려도 빠지지 않는다."""
    async with BeEnv.start(tmp_path, start=SAT_1300) as env:
        for t in ("가", "나", "다"):
            await _add(env, t)  # 모두 04:00Z
        env.clock.advance(minutes=1)
        await _add(env, "라")
        _, page1 = await activity_list(env, "?limit=2")
        _, page2 = await activity_list(env, f"?limit=2&since={page1['next_since']}")

    assert [i["summary"] for i in page1["items"]] == ["✓ 추가: 가", "✓ 추가: 나", "✓ 추가: 다"]
    assert [i["summary"] for i in page2["items"]] == ["✓ 추가: 라"]


@pytest.mark.parametrize("query", [
    "?limit=0", "?limit=201", "?limit=abc", "?limit=-1", "?order=up", "?before=3", "?order=asc&before=3",
    "?order=desc&before=abc", "?order=desc&before=999", "?since=yesterday", "?since=2026-10-24T09:00:00",
    "?since=2026-13-40T00:00:00Z",
])
async def test_activity_bad_query_400_and_bad_path_404(tmp_path, query):
    async with BeEnv.start(tmp_path, start=SAT_1300) as env:
        await _add(env)
        status, body = await activity_list(env, query)
        paths = []
        for path in ("/activity/abc/undo", "/activity/999/undo", "/activity/1x/undo", "/activity/1"):
            resp = await env.post(path, json={"client_msg_id": "u-x"})
            paths.append((resp.status, (await resp.json())["error"]["code"]))
        no_cmid = await env.post("/activity/1/undo", json={})
        not_json = await env.post("/activity/1/undo", data=b"nope")
        no_auth = await env.post("/activity/1/undo", json={"client_msg_id": "u-y"}, token=None)
        task = env.parts.tasks.get(1)

    assert status == 400 and body["error"]["code"] == "invalid_request"
    assert paths == [(404, "not_found")] * 4
    assert no_cmid.status == 400 and not_json.status == 400 and no_auth.status == 401
    assert task is not None and task.deleted_at is None


async def test_undo_log_has_no_title(tmp_path, caplog):
    caplog.set_level(logging.DEBUG)
    async with BeEnv.start(tmp_path, start=SAT_1300) as env:
        a = await _add(env, "꾸민제목문장")
        done = await _apply(env, "complete_task", {"id": a})
        await undo(env, done["undo_id"])
        await activity_list(env)

    text = "\n".join(f"{r.getMessage()} {r.__dict__}" for r in caplog.records)
    routes = {getattr(r, "route", None) for r in caplog.records if r.getMessage() == "api_request"}
    assert {"/api/v1/activity/{id}/undo", "/api/v1/activity"} <= routes
    handled = [r for r in caplog.records if r.getMessage() == "action_handled" and getattr(r, "action", "") == "undo"]
    assert [r.status for r in handled] == ["undone"]
    assert "꾸민제목문장" not in text


async def test_undo_not_callable_through_actions(tmp_path):
    async with BeEnv.start(tmp_path, start=SAT_1300) as env:
        a = await _add(env)
        done = await _apply(env, "complete_task", {"id": a})
        status, body = await env.action("undo", {"activity_id": done["activity_id"]})
        task = env.parts.tasks.get(a).status.value

    assert status == 400 and body["error"]["code"] == "invalid_request" and task == "done"


async def test_u6_undo_leaves_xp_ledger(tmp_path):
    """경험치는 그대로다: 완료로 쌓인 원장 행은 완료를 되돌려도 남고, 다시 완료해도 늘지 않는다(UNIQUE)."""
    async with BeEnv.start(tmp_path, start=SAT_1300) as env:
        a = await _add(env)
        done = await _apply(env, "complete_task", {"id": a})  # X1이 같은 트랜잭션에 쌓인다
        before = _ledger(env)
        status, _ = await undo(env, done["undo_id"])
        after_undo = _ledger(env)
        await _apply(env, "complete_task", {"id": a})
        after_redo = _ledger(env)

    assert status == 200 and len(before) == 1
    assert after_undo == before == after_redo


async def test_undo_client_msg_id_reused_for_other_activity_conflict(tmp_path):
    async with BeEnv.start(tmp_path, start=SAT_1300) as env:
        a, b = await _add(env, "가"), await _add(env, "나")
        da = await _apply(env, "complete_task", {"id": a})
        db = await _apply(env, "complete_task", {"id": b})
        s1, first = await undo(env, da["undo_id"], client_msg_id="u-same")
        s2, second = await undo(env, db["undo_id"], client_msg_id="u-same")
        s3, _ = await undo(env, 999, client_msg_id="u-404")
        s4, other = await undo(env, da["undo_id"], client_msg_id="u-404")  # 404를 저장한 id를 다른 활동에
        s5, replay = await undo(env, da["undo_id"], client_msg_id="u-same")
        b_status = env.parts.tasks.get(b).status.value

    assert s1 == 200 and first["status"] == "undone"
    assert s2 == 409 and second["error"] == {"code": "conflict", "message": "이미 다른 요청에 쓴 client_msg_id예요."}
    assert s3 == 404 and s4 == 409 and other["error"]["code"] == "conflict"
    assert (s5, replay) == (200, {"status": "already_undone", "activity_id": first["activity_id"]})
    assert b_status == "done"


def test_undo_summary_keeps_title_arrow():
    from my_planner.tools.confirmations import undo_summary

    assert undo_summary("✓ 완료: 서울 → 부산") == "↩ 되돌림: 서울 → 부산 완료"
    assert undo_summary("✓ 바꿈: 계획 → 실행") == "↩ 되돌림: 계획 → 실행 바꿈"
    assert undo_summary("✓ 추가: 서울 → 부산 → 내일") == "↩ 되돌림: 서울 → 부산 추가"
    assert undo_summary("✓ 추가: 서울 → 부산") == "↩ 되돌림: 서울 → 부산 추가"
    assert undo_summary("✓ 추가: 치과 (10/27 14:00)") == "↩ 되돌림: 치과 추가"
    assert undo_summary("✓ 옮김: 서울 → 부산 → 10/26") == "↩ 되돌림: 서울 → 부산 옮김"
    assert undo_summary("✓ 옮김: 운동 → 날짜 없음") == "↩ 되돌림: 운동 옮김"


def test_undo_handlers_registered_regardless_of_import_order():
    """`tools.activity`만 가져온 새 인터프리터에서도 `undo_block`이 종류별 되돌리기를 본다."""
    import subprocess
    import sys

    code = (
        "from datetime import datetime, UTC\n"
        "from my_planner.tools.activity import undo_block\n"
        "from my_planner.store.repos.activity import Activity\n"
        "class Repo:\n"
        "    def targets(self, id): return ['task:1']\n"
        "    def changed_after(self, *a, **kw): return False\n"
        "now = datetime(2026, 10, 24, 4, tzinfo=UTC)\n"
        "a = Activity(1, now, 'user', 'app', 'task_completed', 'task:1', 's', 'low', {'task_id': 1}, None, None,"
        " None, None, None)\n"
        "print(undo_block(a, Repo(), now))\n"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "None"


async def test_undo_tasks_confirmed_partial_single_summary(tmp_path):
    async with BeEnv.start(tmp_path, start=SAT_1300) as env:
        d1, d2 = _propose(env, "물 마시기", "스트레칭")
        confirmed = await _apply(env, "confirm_tasks", {"ids": [d1, d2]})
        await _apply(env, "drop_task", {"id": d1})
        status, body = await undo(env, confirmed["undo_id"])
        row = _row(env, body["activity_id"])["summary"]

    assert status == 200 and body["confirmation"] == "↩ 되돌림: 스트레칭 확정" == row


async def test_undo_list_with_task_done_before_change_p4(tmp_path):
    """N1/P4: 목록 [a, b] → a 완료 → 목록 [b] → 목록 되돌리기. a는 목록 변경 전에 이미 `done`이었다."""
    async with BeEnv.start(tmp_path, start=SAT_1300) as env:
        a, b = await _add(env, "가"), await _add(env, "나")
        await _apply(env, "set_priorities", {**WEEK, "task_ids": [a, b]})
        await _apply(env, "complete_task", {"id": a})
        second = await _apply(env, "set_priorities", {**WEEK, "task_ids": [b]})
        status, body = await undo(env, second["undo_id"])
        listed = [t.id for t in env.parts.tasks.priorities("week", "2026-W43")]
        task = env.parts.tasks.get(a).status.value

    assert status == 200 and body["status"] == "undone"
    assert listed == [a, b] and task == "done"


async def test_list_undo_makes_drop_token_stale_n2(tmp_path):
    """N2: 이번 주 목록 [n] → `drop_task n` 확인 토큰 → 목록 되돌리기(n이 빠진다) → 그 토큰은 stale(409).
    되돌리기 행의 할 일 대상은 지켜보기만 하므로 U3은 그대로다(그 전 완료 되돌리기는 막히지 않는다)."""
    async with BeEnv.start(tmp_path, start=SAT_1300) as env:
        n, m = await _add(env, "가"), await _add(env, "나")
        done_m = await _apply(env, "complete_task", {"id": m})
        listed = await _apply(env, "set_priorities", {**WEEK, "task_ids": [n]})
        _, nc = await env.action("drop_task", {"id": n})
        assert nc["status"] == "needs_confirm"
        env.clock.advance(minutes=1)
        s_undo, _ = await undo(env, listed["undo_id"])
        st, body = await env.action("drop_task", {"id": n}, confirm_token=nc["confirm_token"])
        token = env.conn.execute("SELECT resolution FROM pending_confirms WHERE token = ?",
                                 (nc["confirm_token"],)).fetchone()["resolution"]
        task = env.parts.tasks.get(n).status.value
        s_m, _ = await undo(env, done_m["undo_id"])

    assert s_undo == 200
    assert st == 409 and body["error"]["code"] == "conflict" and token == "stale" and task == "open"
    assert s_m == 200


# --- 습관 되돌리기 (SP7 5.5) ---


def _checks(env):
    return [tuple(r) for r in env.conn.execute("SELECT habit_id, date FROM habit_checks ORDER BY 1, 2")]


WED_1300 = kst(2026, 10, 28, 13, 0)


async def test_undo_monday_check_after_tuesday_check(tmp_path):
    """체크 활동의 대상은 `habit:<id>:<날짜>` 하나: 다른 날짜의 체크끼리는 U3로 막지 않는다."""
    async with BeEnv.start(tmp_path, start=WED_1300) as env:
        h = _habit(env)
        mon = _habit_call(env, "check_habit", id=h, date="2026-10-26")
        env.clock.advance(minutes=1)
        _habit_call(env, "check_habit", id=h, date="2026-10-27")
        env.clock.advance(minutes=1)
        status, out = await undo(env, mon["undo_id"])
        repo = ActivityRepo(env.conn, env.clock)
        targets = repo.targets(out["activity_id"])
        checks = _checks(env)
    assert (status, out["status"], out["confirmation"]) == (200, "undone", "↩ 되돌림: 운동 습관 체크")
    assert targets == [f"habit:{h}:2026-10-26"]
    assert checks == [(h, "2026-10-27")]


async def test_undo_same_day_check_blocked_by_uncheck(tmp_path):
    async with BeEnv.start(tmp_path, start=SAT_1300) as env:
        h = _habit(env)
        chk = _habit_call(env, "check_habit", id=h)
        checked_at = env.conn.execute("SELECT checked_at FROM habit_checks").fetchone()[0]
        env.clock.advance(minutes=1)
        unchk = _habit_call(env, "uncheck_habit", id=h)
        env.clock.advance(minutes=1)
        blocked = await undo(env, chk["undo_id"])
        restored = await undo(env, unchk["undo_id"])
        rows = [tuple(r) for r in env.conn.execute("SELECT habit_id, date, checked_at FROM habit_checks")]
    assert blocked[0] == 409 and blocked[1]["error"]["code"] == "superseded"
    assert restored[0] == 200 and restored[1]["confirmation"] == "↩ 되돌림: 운동 습관 체크 취소"
    assert rows == [(h, "2026-10-24", checked_at)]  # 이전 `checked_at` 그대로


async def test_undo_add_with_checks_superseded(tmp_path):
    async with BeEnv.start(tmp_path, start=SAT_1300) as env:
        add = _habit_call(env, "add_habit", title="물 마시기", area="health", kind="daily")
        h = add["result"]["id"]
        chk = _habit_call(env, "check_habit", id=h)
        env.clock.advance(minutes=1)
        blocked = await undo(env, add["undo_id"])
        alive = env.parts.tools.habits.get(h)
        # 체크를 먼저 되돌리면 추가도 되돌릴 수 있다. 두 번째 되돌리기는 U4
        await undo(env, chk["undo_id"])
        done = await undo(env, add["undo_id"])
        again = await undo(env, add["undo_id"])
        gone = env.parts.tools.habits.get(h)
        deleted_at = env.conn.execute("SELECT deleted_at FROM habits WHERE id = ?", (h,)).fetchone()[0]
        ledger = _ledger(env)
    assert blocked[0] == 409 and blocked[1]["error"]["code"] == "superseded"
    assert alive is not None
    assert done[0] == 200 and done[1]["confirmation"] == "↩ 되돌림: 물 마시기 습관 추가"
    assert again[0] == 200 and again[1]["status"] == "already_undone"
    assert gone is None and deleted_at is not None
    assert [r[3] for r in ledger] == ["habit_check"]  # U6: 원장은 그대로


async def test_undo_check_of_paused_habit_restores(tmp_path):
    """체크·취소의 되돌리기는 5.3의 거절(쉬는 습관)을 보지 않는다."""
    async with BeEnv.start(tmp_path, start=SAT_1300) as env:
        a, b = _habit(env, "운동"), _habit(env, "물 마시기", kind="daily", target_per_week=None)
        chk = _habit_call(env, "check_habit", id=a)
        _habit_call(env, "check_habit", id=b, date="2026-10-23")
        unchk = _habit_call(env, "uncheck_habit", id=b, date="2026-10-23")
        env.clock.advance(minutes=1)
        _habit_call(env, "set_habit_status", id=a, status="paused")
        _habit_call(env, "set_habit_status", id=b, status="archived")
        env.clock.advance(minutes=1)
        r1 = await undo(env, chk["undo_id"])
        r2 = await undo(env, unchk["undo_id"])
        checks = _checks(env)
        statuses = [env.parts.tools.habits.get(i).status for i in (a, b)]
    assert (r1[0], r2[0]) == (200, 200)
    assert checks == [(b, "2026-10-23")]
    assert statuses == ["paused", "archived"]


async def test_undo_pause_can_exceed_cap_then_add_rejected(tmp_path):
    """Review Focus 4: 활성 10개 → 하나 쉬어 가기 → 새 습관(10개) → 쉬어 가기 되돌리기 → 11개.
    그동안 새 추가·다시 시작은 거절, 체크는 된다."""
    async with BeEnv.start(tmp_path, start=SAT_1300) as env:
        tools = env.parts.tools
        ids = [_habit(env, f"습관{i}", kind="daily", target_per_week=None) for i in range(10)]
        other = _habit_call(env, "set_habit_status", id=ids[1], status="paused")  # 쉬는 습관 하나 더
        _habit_call(env, "set_habit_status", id=ids[1], status="active")  # 9개
        pause = _habit_call(env, "set_habit_status", id=ids[0], status="paused")
        extra = _habit(env, "열한째", kind="daily", target_per_week=None)  # 다시 10개
        _habit_call(env, "set_habit_status", id=ids[2], status="paused")  # 9개
        _habit(env, "열두째", kind="daily", target_per_week=None)  # 10개
        env.clock.advance(minutes=1)
        status, out = await undo(env, pause["undo_id"])
        count = tools.habits.count_active()
        add = tools.add_habit(_hctx(), title="열셋째", area="health", kind="daily")
        resume = tools.set_habit_status(_hctx(), id=ids[2], status="active")
        check = tools.check_habit(_hctx(), id=extra)
    assert other["undo_id"] is not None
    assert (status, out["confirmation"]) == (200, "↩ 되돌림: 습관0 습관 쉬어 가기")
    assert count == 11
    assert add == {"error": "습관은 한 번에 10개까지 챙길 수 있어요. 하나를 쉬어 가거나 그만두면 더할 수 있어요."}
    assert resume == add
    assert check["already"] is False and check["habit"]["checked"] is True


async def test_undo_check_of_deleted_habit_superseded(tmp_path):
    """추가 → 체크 → 취소 → 추가 되돌리기 → 취소 되돌리기: 지운 습관에 체크 행을 되살리지 않는다."""
    async with BeEnv.start(tmp_path, start=SAT_1300) as env:
        add = _habit_call(env, "add_habit", title="물 마시기", area="health", kind="daily")
        h = add["result"]["id"]
        chk = _habit_call(env, "check_habit", id=h)
        env.clock.advance(minutes=1)
        unchk = _habit_call(env, "uncheck_habit", id=h)
        env.clock.advance(minutes=1)
        removed = await undo(env, add["undo_id"])
        restored = await undo(env, unchk["undo_id"])
        rechecked = await undo(env, chk["undo_id"])
        checks = _checks(env)
    assert removed[0] == 200
    assert restored[0] == 409 and restored[1]["error"]["code"] == "superseded"
    assert rechecked[0] == 409 and rechecked[1]["error"]["code"] == "superseded"
    assert checks == []
