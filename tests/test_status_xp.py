"""상태창 경험치 원장 X1~X10, 레벨 오름 (SP3-4 스펙 9.1, 9.2, 4.3). 내용은 꾸며 낸 것이다."""

import re
import sqlite3
from datetime import date, timedelta
from pathlib import Path

import pytest
from be_env import BeEnv
from fakes import FakeTurn
from test_dispatcher_messages import kst

from my_planner.domain import Cadence, LoopKey, RunContext
from my_planner.harness.dispatcher import Dispatcher
from my_planner.store.repos.status import StatusRepo
from my_planner.tools.actions import ActionRequest
from my_planner.tools.confirmations import level_up_line

SAT_1300 = kst(2026, 10, 24, 13, 0)


def _ledger(env):
    return [
        (r["source_kind"], r["source_ref"], r["amount"])
        for r in env.conn.execute("SELECT * FROM status_xp_ledger ORDER BY id")
    ]


def _ctx():
    return RunContext(conversation_id=None, run_id=None)


async def _add(env, title="꾸민 할 일", **extra):
    _, body = await env.action("add_task", {"title": title, "areas": ["health"], **extra})
    return body["result"]["id"]


def _sent_run(env, loop, at, cadence=Cadence.day):
    runs = env.parts.runs
    run = runs.ensure(loop, at, cadence)
    runs.mark_done(run.id)
    return run


def _scheduler(env, action):
    return env.parts.dispatcher.apply_action(ActionRequest(action, {}, actor="secretary", channel="scheduler"))


# --- X1~X10 표 ---


async def _x1(env):
    a = await _add(env)
    await env.action("complete_task", {"id": a})
    return ("task_done", f"task:{a}", 10)


async def _x2(env):
    a = await _add(env)
    await env.action("set_priorities", {"cadence": "week", "period": "2026-W43", "task_ids": [a]})
    await env.action("complete_task", {"id": a})
    return ("task_done", f"task:{a}", 25)


async def _x3(env):
    run = _sent_run(env, LoopKey.evening_checkin, kst(2026, 10, 24, 18, 0))
    env.clock.set(kst(2026, 10, 24, 18, 30))
    assert env.parts.dispatcher.mark_answered(run.id, "telegram")
    return ("checkin_reply", f"run:{run.id}", 5)


async def _x4(env):
    await env.action("record_condition", {"score": 4})
    return ("condition", "date:2026-10-24", 5)


async def _x5(env):
    review = _sent_run(env, LoopKey.review, kst(2026, 10, 25, 18, 0), Cadence.week)
    env.clock.set(kst(2026, 10, 25, 18, 30))
    env.parts.dispatcher.mark_answered(review.id, "app")
    return ("review_week", f"run:{review.id}", 30)


async def _x6(env):
    await env.action("record_ladder_score", {"now": 6})
    return ("ladder", "ladder:2026-10", 10)


async def _x7(env):
    await env.action("record_area_scores", {"scores": {"health": 6}})
    return ("wheel", "areas:2026-Q4", 20)


async def _x8(env):
    review = _sent_run(env, LoopKey.review, kst(2026, 12, 27, 18, 0), Cadence.week)
    env.clock.set(kst(2026, 12, 27, 19, 0))
    env.parts.dispatcher.mark_answered(review.id, "telegram")
    return ("year_review", "year:2026", 50)


async def _x9(env):
    env.clock.set(kst(2026, 10, 25, 9, 0))
    assert _scheduler(env, "grant_rest_days").status == "applied"
    return ("rest_day", "date:2026-10-24", 5)


async def _x10(env):
    out = env.parts.tools.grant_xp(_ctx(), amount=10, reason="꾸민 산책")
    assert "error" not in out
    return ("secretary", "secretary:2026-10-24:1", 10)


X_CASES = {"X1": _x1, "X2": _x2, "X3": _x3, "X4": _x4, "X5": _x5, "X6": _x6, "X7": _x7, "X8": _x8, "X9": _x9,
           "X10": _x10}


@pytest.mark.parametrize("rule", list(X_CASES))
async def test_xp_table_x1_to_x10(tmp_path, rule):
    async with BeEnv.start(tmp_path, start=SAT_1300) as env:
        expected = await X_CASES[rule](env)
        ledger = _ledger(env)
        status = await (await env.get("/status")).json()

    assert expected in ledger
    assert status["xp_total"] == sum(a for *_, a in ledger)


async def test_x2_biggest_cadence_at_completion(tmp_path):
    async with BeEnv.start(tmp_path, start=SAT_1300) as env:
        a = await _add(env, "가")
        b = await _add(env, "나")
        c = await _add(env, "다")
        d = await _add(env, "라")
        await env.action("set_priorities", {"cadence": "week", "period": "2026-W43", "task_ids": [a]})
        await env.action("set_priorities", {"cadence": "quarter", "period": "2026-Q4", "task_ids": [a]})
        await env.action("set_priorities", {"cadence": "day", "period": "2026-10-24", "task_ids": [b]})
        await env.action("set_priorities", {"cadence": "month", "period": "2026-10", "task_ids": [c]})
        # 지난 주의 우선순위는 "완료 순간 그 할 일이 든 우선순위"가 아니다
        await env.action("set_priorities", {"cadence": "week", "period": "2026-W42", "task_ids": [d]})
        await env.action("set_priorities", {"cadence": "month", "period": "2026-10", "task_ids": []})  # 완료 전에 뺐다
        for i in (a, b, c, d):
            await env.action("complete_task", {"id": i})
        got = {ref: amount for kind, ref, amount in _ledger(env) if kind == "task_done"}

    assert got == {f"task:{a}": 100, f"task:{b}": 15, f"task:{c}": 10, f"task:{d}": 10}


async def test_recomplete_after_undo_does_not_double(tmp_path):
    """U6: 되돌리기는 원장을 건드리지 않고, 다시 완료해도 `task:<id>`는 한 번이다."""
    async with BeEnv.start(tmp_path, start=SAT_1300) as env:
        a = await _add(env)
        await env.action("set_priorities", {"cadence": "week", "period": "2026-W43", "task_ids": [a]})
        _, first = await env.action("complete_task", {"id": a})
        resp = await env.post(f"/activity/{first['activity_id']}/undo", json={"client_msg_id": "u-1"})
        assert resp.status == 200
        after_undo = _ledger(env)
        _, again = await env.action("complete_task", {"id": a})
        after_redo = _ledger(env)

    assert first["xp"] == {"gained": 25, "level_up": None}
    assert again["xp"] == {"gained": 0, "level_up": None}
    assert after_undo == after_redo == [("task_done", f"task:{a}", 25)]


async def test_x5_once_for_bundle_and_x8_on_1227(tmp_path):
    async with BeEnv.start(tmp_path, start=SAT_1300) as env:
        runs = env.parts.runs
        # 일요일 저녁 체크인과 주간 회고를 합쳐 보낸 묶음(10/25): 묶음 전체에 X5 하나, X3은 없다
        evening = _sent_run(env, LoopKey.evening_checkin, kst(2026, 10, 25, 18, 0))
        review = _sent_run(env, LoopKey.review, kst(2026, 10, 25, 18, 0), Cadence.week)
        runs.add_merged(evening.id, [review.id])
        env.clock.set(kst(2026, 10, 25, 18, 30))
        assert env.parts.dispatcher.mark_answered(review.id, "telegram")  # 합쳐진 회차로 와도 primary에 적는다
        assert not env.parts.dispatcher.mark_answered(evening.id, "app")  # 두 번째 답
        bundle = _ledger(env)
        # 12/27(12월 마지막 일요일) 회고: X5 + X8
        year_evening = _sent_run(env, LoopKey.evening_checkin, kst(2026, 12, 27, 18, 0))
        year_review = _sent_run(env, LoopKey.review, kst(2026, 12, 27, 18, 0), Cadence.week)
        runs.add_merged(year_evening.id, [year_review.id])
        env.clock.set(kst(2026, 12, 27, 18, 40))
        env.parts.dispatcher.mark_answered(year_evening.id, "app")
        year = _ledger(env)[len(bundle):]
        # 12/20은 연말 회고가 아니다
        dec20 = _sent_run(env, LoopKey.review, kst(2026, 12, 20, 18, 0), Cadence.week)
        env.parts.dispatcher.mark_answered(dec20.id, "app")
        later = _ledger(env)[len(bundle) + len(year):]

    assert bundle == [("review_week", f"run:{review.id}", 30)]
    assert year == [("review_week", f"run:{year_review.id}", 30), ("year_review", "year:2026", 50)]
    assert later == [("review_week", f"run:{dec20.id}", 30)]


# --- 같은 트랜잭션 ---


async def test_mark_answered_and_ledger_atomic(tmp_path, monkeypatch):
    def boom(self, **kw):
        raise sqlite3.OperationalError("꾸민 오류")

    async with BeEnv.start(tmp_path, start=SAT_1300) as env:
        run = _sent_run(env, LoopKey.evening_checkin, kst(2026, 10, 24, 18, 0))
        env.clock.set(kst(2026, 10, 24, 18, 30))
        monkeypatch.setattr(StatusRepo, "grant", boom)
        with pytest.raises(sqlite3.OperationalError):
            env.parts.dispatcher.mark_answered(run.id, "app")
        answered = env.parts.runs.get(run.id).answered_at
        ledger = _ledger(env)
        # 즉시 갈래 안에서 답 기록이 안 되면 그것만 되돌리고 동작은 그대로 적용한다(안쪽 SAVEPOINT)
        monkeypatch.undo()
        monkeypatch.setattr(Dispatcher, "_grant_answer_xp", lambda self, primary, at: boom(None))
        monkeypatch.setattr("my_planner.harness.checkins.run_answered_by", lambda req, **kw: run.id)
        status, body = await env.action("record_condition", {"score": 3, "date": "2026-10-24"})
        cond = env.parts.conditions.get(date(2026, 10, 24))
        after = (env.parts.runs.get(run.id).answered_at, _ledger(env))

    assert answered is None and ledger == []
    assert status == 200 and body["status"] == "applied" and cond is not None
    assert body["xp"] == {"gained": 5, "level_up": None}
    assert after == (None, [("condition", "date:2026-10-24", 5)])


async def test_condition_task_and_curve_ledger_roll_back_with_change(tmp_path, monkeypatch):
    """X1/X4가 변경과 한 트랜잭션: 원장 쓰기가 안 되면 변경도 활동도 없다."""
    def boom(self, **kw):
        raise sqlite3.OperationalError("꾸민 오류")

    async with BeEnv.start(tmp_path, start=SAT_1300) as env:
        a = await _add(env)
        monkeypatch.setattr(StatusRepo, "grant", boom)
        with pytest.raises(sqlite3.OperationalError):
            env.parts.dispatcher.apply_action(ActionRequest("complete_task", {"id": a}, actor="user", channel="app"))
        task = env.parts.tasks.get(a)
        kinds = [r["kind"] for r in env.activity()]

    assert task.status.value == "open"
    assert kinds == ["task_added"]


# --- X9 쉬는 날 ---


async def test_rest_days_rules(tmp_path):
    async with BeEnv.start(tmp_path, start=SAT_1300) as env:  # installed_at = 10/24 12:59
        a = await _add(env)
        env.clock.set(kst(2026, 10, 25, 15, 0))
        await env.action("complete_task", {"id": a})  # 10/25는 쉰 날이 아니다
        env.clock.set(kst(2026, 10, 28, 5, 0))
        first = _scheduler(env, "grant_rest_days").body["result"]["granted_dates"]
        again = _scheduler(env, "grant_rest_days").body["result"]["granted_dates"]
        checked = env.parts.state.get("last_rest_day_checked")
        (act,) = [r for r in env.activity() if r["kind"] == "rest_days_granted"]
        # 멈춘 날도 쉰 날이다. 한 번에 최대 14일(어제까지): 10/28~11/19 가운데 11/6~11/19
        env.parts.state.set("pause_until", "2026-11-12T00:00:00.000000+00:00")
        env.clock.set(kst(2026, 11, 20, 9, 0))
        capped = _scheduler(env, "grant_rest_days").body["result"]["granted_dates"]
        rows = env.conn.execute(
            "SELECT logical_date, label, amount FROM status_xp_ledger WHERE source_kind = 'rest_day' ORDER BY id"
        ).fetchall()

    assert first == ["2026-10-24", "2026-10-26", "2026-10-27"]
    assert again == [] and checked == "2026-10-27"
    assert (act["actor"], act["channel"], act["summary"], act["undo_json"]) == (
        "secretary", "scheduler", "✓ 쉬는 날: 3일", None)
    assert capped == [f"2026-11-{d:02d}" for d in range(6, 20)]
    assert all(r["label"] == "쉬는 날" and r["amount"] == 5 for r in rows)
    assert [r["logical_date"] for r in rows][:3] == first


async def test_rest_days_skip_before_install(tmp_path):
    async with BeEnv.start(tmp_path, start=SAT_1300) as env:
        env.parts.state.set("installed_at", "2026-10-26T01:00:00.000000+00:00")  # 10/26 10:00 KST
        env.clock.set(kst(2026, 10, 28, 5, 0))
        got = _scheduler(env, "grant_rest_days").body["result"]["granted_dates"]
    assert got == ["2026-10-26", "2026-10-27"]


async def test_task_done_at_0130_counts_previous_day_so_no_rest_day(tmp_path):
    """Review Focus 5: 01:30에 끝낸 할 일은 전날(논리적 날짜)의 완료다."""
    async with BeEnv.start(tmp_path, start=SAT_1300) as env:
        a = await _add(env)
        env.clock.set(kst(2026, 10, 26, 1, 30))  # 달력 10/26, 논리적 날짜 10/25
        await env.action("complete_task", {"id": a})
        (row,) = env.conn.execute("SELECT logical_date FROM status_xp_ledger WHERE source_kind = 'task_done'")
        env.clock.set(kst(2026, 10, 27, 5, 0))
        got = _scheduler(env, "grant_rest_days").body["result"]["granted_dates"]

    assert row["logical_date"] == "2026-10-25"
    assert got == ["2026-10-24", "2026-10-26"]


async def test_rest_days_run_from_daily_tick(tmp_path):
    async with BeEnv.start(tmp_path, start=SAT_1300) as env:
        env.clock.set(kst(2026, 10, 25, 9, 0) + timedelta(seconds=30))
        env.parts.state.set("last_seen_at", "2026-10-24T23:59:00.000000+00:00")
        await env.tick()
        status = await (await env.get("/status")).json()
    assert status["recent_xp"][0]["label"] == "쉬는 날" and status["recent_xp"][0]["amount"] == 5


# --- X10 grant_xp ---


async def test_grant_xp_amounts_reason_and_daily_cap(tmp_path):
    async with BeEnv.start(tmp_path, start=SAT_1300) as env:
        tools = env.parts.tools
        bad = [
            tools.grant_xp(_ctx(), amount=7, reason="꾸민 사유"),
            tools.grant_xp(_ctx(), amount=True, reason="꾸민 사유"),
            tools.grant_xp(_ctx(), amount="10", reason="꾸민 사유"),
            tools.grant_xp(_ctx(), amount=10, reason="  "),
            tools.grant_xp(_ctx(), amount=10, reason=None),
            tools.grant_xp(_ctx(), amount=10, reason="가" * 61),
        ]
        ctx = _ctx()
        ok = [tools.grant_xp(ctx, amount=n, reason=f" 꾸민 사유 {n} ") for n in (5, 10, 5)]
        capped = tools.grant_xp(_ctx(), amount=5, reason="꾸민 사유")
        env.clock.set(kst(2026, 10, 25, 9, 0))  # 다음 논리적 날짜
        next_day = tools.grant_xp(_ctx(), amount=5, reason="가" * 60)
        rows = env.conn.execute(
            "SELECT source_ref, amount, label FROM status_xp_ledger WHERE source_kind = 'secretary' ORDER BY id"
        ).fetchall()
        acts = [(r["kind"], r["summary"], r["undo_json"]) for r in env.activity()]

    assert all("error" in b for b in bad)
    assert "5 또는 10" in bad[0]["error"] and "60자" in bad[5]["error"]
    assert [o["today_count"] for o in ok] == [1, 2, 3]
    assert "하루 3번" in capped["error"]
    assert "error" not in next_day
    assert [tuple(r) for r in rows] == [
        ("secretary:2026-10-24:1", 5, "꾸민 사유 5"), ("secretary:2026-10-24:2", 10, "꾸민 사유 10"),
        ("secretary:2026-10-24:3", 5, "꾸민 사유 5"), ("secretary:2026-10-25:1", 5, "가" * 60),
    ]
    assert acts[1] == ("xp_granted_by_secretary", "✓ 경험치 +10: 꾸민 사유 10", None)
    assert [e.kind for e in ctx.events] == ["xp_granted_by_secretary"] * 3


async def test_grant_xp_is_not_an_action(tmp_path):
    """6.4.2: `grant_xp`는 `/actions`에 없다(경험치 부여는 비서의 일)."""
    async with BeEnv.start(tmp_path, start=SAT_1300) as env:
        status, body = await env.action("grant_xp", {"amount": 10, "reason": "꾸민 사유"})
        status2, _ = await env.action("grant_rest_days", {})
    assert status == 400 and body["error"]["code"] == "invalid_request"
    assert status2 == 400


# --- 레벨 오름 ---


def _seed_xp(env, amount):
    env.conn.execute(
        "INSERT INTO status_xp_ledger (at, logical_date, source_kind, source_ref, amount, label) "
        "VALUES ('2026-10-23T00:00:00.000000+00:00', '2026-10-23', 'rest_day', 'date:2026-10-23', ?, '쉬는 날')",
        (amount,),
    )
    env.conn.commit()


def test_level_up_line():
    assert level_up_line(140, 150) == "레벨 2이 됐어요."
    assert level_up_line(150, 160) == ""
    assert level_up_line(140, 349) == "레벨 2이 됐어요."
    assert level_up_line(140, 350) == "레벨 3이 됐어요."  # 두 단계를 넘으면 새 레벨 한 줄
    assert level_up_line(0, 0) == ""


async def test_level_up_line_once(tmp_path):
    complete = ("complete_task", {"id": 3})
    script = [FakeTurn([complete], "끝냈네요")]
    async with BeEnv.start(tmp_path, start=SAT_1300, script=script) as env:
        _seed_xp(env, 140)
        a, b = await _add(env, "꾸민 운동"), await _add(env, "꾸민 독서")
        _, first = await env.action("complete_task", {"id": a})  # 140 → 150
        _, second = await env.action("complete_task", {"id": b})  # 150 → 160
        # 텔레그램 대화: 두뇌가 완료하면 확인 문구 끝에(160 → 170, 오르지 않음)
        c = await _add(env, "꾸민 산책")
        assert c == 3
        await env.telegram("산책 끝")
        no_level = env.sender.sent[-1].text
        status = await (await env.get("/status")).json()

    assert first["xp"] == {"gained": 10, "level_up": 2}
    assert first["confirmation"] == "✓ 완료: 꾸민 운동\n레벨 2이 됐어요."
    assert second["xp"] == {"gained": 10, "level_up": None}
    assert second["confirmation"] == "✓ 완료: 꾸민 독서"
    assert "레벨" not in no_level
    assert (status["level"], status["xp_total"], status["xp_into_level"], status["xp_for_next"]) == (2, 170, 20, 200)


async def test_level_up_line_in_telegram_reply_and_button(tmp_path):
    complete = ("complete_task", {"id": 1})
    script = [FakeTurn([complete], "끝냈네요")]
    async with BeEnv.start(tmp_path, start=SAT_1300, script=script) as env:
        _seed_xp(env, 145)
        await _add(env, "꾸민 운동")
        await env.telegram("운동 끝")  # 145 → 155
        reply = env.sender.sent[-1].text
        # 버튼(컨디션) 145+10 → +5: 레벨은 그대로
        await env.press("c:2026-10-24:4")
        toast = env.bot.answers[-1][1]
        # 다시 경계 바로 아래로: 345 → 버튼 +5 = 350 → 레벨 3
        env.conn.execute(
            "INSERT INTO status_xp_ledger (at, logical_date, source_kind, source_ref, amount, label) "
            "VALUES ('2026-10-23T00:00:00.000000+00:00', '2026-10-23', 'rest_day', 'date:2026-10-22', 185, '쉬는 날')"
        )
        env.conn.commit()
        env.clock.set(kst(2026, 10, 25, 13, 0))
        await env.press("c:2026-10-25:3")
        toast3 = env.bot.answers[-1][1]

    assert reply.endswith("✓ 완료: 꾸민 운동\n레벨 2이 됐어요.")
    assert toast == "컨디션 4 기록했어요."
    assert toast3 == "컨디션 3 기록했어요.\n레벨 3이 됐어요."


# --- 오르기만 한다 ---


def test_ledger_has_no_update_delete_functions():
    src = Path(__file__).resolve().parents[1] / "src" / "my_planner"
    pattern = re.compile(
        r"(UPDATE|DELETE\s+FROM|REPLACE\s+INTO|INSERT\s+OR\s+REPLACE\s+INTO)\s+status_xp_ledger", re.IGNORECASE
    )
    hits = [p for p in src.rglob("*.py") if pattern.search(p.read_text(encoding="utf-8"))]
    assert hits == []
    public = {n for n in dir(StatusRepo) if not n.startswith("_")}
    assert public == {"grant", "count_secretary_on", "total", "recent", "titles", "add_title", "remove_title"}


def test_ledger_rejects_non_positive_amount(conn):
    for amount in (0, -5):
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO status_xp_ledger (at, logical_date, source_kind, source_ref, amount, label) "
                "VALUES ('2026-10-24T00:00:00Z', '2026-10-24', 'condition', ?, ?, '컨디션 기록')",
                (f"date:{amount}", amount),
            )
