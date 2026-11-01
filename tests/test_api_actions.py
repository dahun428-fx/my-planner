"""`POST /actions` (SP3-4 스펙 6.4.2): 즉시 갈래 `apply_action`, 확인 토큰, 중복 방지. 내용은 꾸며 낸 것이다."""

import jsonschema
import pytest
from be_env import BeEnv
from test_dispatcher_messages import kst

from my_planner.api.models import schema_bundle
from my_planner.store.db import transaction
from my_planner.store.exports import export_tasks
from my_planner.tools.actions import ACTIONS

SAT_1300 = kst(2026, 10, 24, 13, 0)  # 토요일 낮: 예정된 회차가 없다


def _validate(model, body):
    jsonschema.Draft202012Validator(schema_bundle()["models"][model]).validate(body)


async def _add(env, title="운동", **extra):
    status, body = await env.action("add_task", {"title": title, "areas": ["health"], **extra})
    assert status == 200, body
    return body["result"]["id"]


def _token_row(env, token):
    return env.conn.execute("SELECT * FROM pending_confirms WHERE token = ?", (token,)).fetchone()


async def test_complete_task_applied_shape(tmp_path):
    async with BeEnv.start(tmp_path, start=SAT_1300) as env:
        tid = await _add(env, planned_for="2026-10-24")
        env.clock.advance(minutes=5)
        status, body = await env.action("complete_task", {"id": tid})
        (row,) = [r for r in env.activity() if r["kind"] == "task_completed"]

    assert status == 200
    _validate("ActionApplied", body)
    assert body["status"] == "applied"
    assert body["activity_id"] == row["id"] and body["undo_id"] == row["id"]
    assert body["confirmation"] == "✓ 완료: 운동"
    assert body["xp"] == {"gained": 10, "level_up": None}  # X1
    assert body["result"]["id"] == tid and body["result"]["status"] == "done"
    assert body["result"]["completed_at"] == "2026-10-24T04:05:00Z"  # 도구 결과의 +09:00 → UTC
    assert (row["actor"], row["channel"], row["target"], row["risk"]) == ("user", "app", f"task:{tid}", "low")
    assert row["summary"] == "✓ 완료: 운동"


CARD = {"title": "꾸민 요약", "lines": ["한 줄"]}


def _public_cases(ids, card, curve=(None, None, None, None), habits=(None, None), memos=(None, None, None), moments=(None, None, None),
                  events=(None, None), photos=(None, None), workout=(None, None), measure=None,
                  panel=(None, None, None)):
    """공개 동작마다 적용되는 args 한 벌. `ids`는 미리 만든 할 일 번호(열림 a, b, 완료 c, 초안 d), `card`는 고정 카드,
    `curve`는 사건 초안 둘과 챕터 초안 둘(확정용, 빼기용)."""
    a, b, c, d = ids
    m1, m2, h1, h2 = curve
    hb, hc = habits  # 습관 둘(체크 안 함, 오늘 체크함)
    mo, mp, mu = memos  # 메모 셋(고정 안 함, 고정함은 `mp`), `mu`는 `updated_at`
    mv, mh, md = moments  # 이룬 순간 셋(보임, 숨김, 지울 것)
    ev, er = events  # 매일 일정 하나, 놓친 알림 행이 있는 일정
    pf, pa = photos  # 사진 둘(붙지 않음, `mp`에 붙음)
    wn, wl = workout  # 몸 메모 하나, 운동 기록 하나
    return {
        "add_task": {"title": "새 일", "areas": ["learning"]},
        "update_task": {"id": a, "note": "꾸민 메모"},
        "move_task": {"id": a, "planned_for": "2026-10-25"},
        "complete_task": {"id": b},
        "reopen_task": {"id": c},
        "drop_task": {"id": a},
        "confirm_tasks": {"ids": [d]},
        "set_priorities": {"cadence": "week", "period": "2026-W43", "task_ids": [a]},
        "record_condition": {"score": 4},
        "pin_card": {"component": "ui_summary_card", "props": CARD},
        "unpin_card": {"id": card},
        "reorder_cards": {"ids": [card]},
        "record_ladder_score": {"now": 6},
        "record_area_scores": {"scores": {"health": 7}},
        "confirm_milestones": {"ids": [m1]},
        "drop_milestone": {"id": m2},
        "confirm_chapters": {"ids": [h1]},
        "drop_chapter": {"id": h2},
        "decline_confirm": None,  # 토큰을 따로 만든다
        # 습관(SP7 5.5). 그만두기는 앱에서 확인을 받으므로 쉬어 가기로
        "add_habit": {"title": "새 습관", "area": "health", "kind": "daily"},
        "update_habit": {"id": hb, "title": "고친 습관"},
        "set_habit_status": {"id": hb, "status": "paused"},
        "check_habit": {"id": hb},
        "uncheck_habit": {"id": hc},
        # 체크인 시간(SP9 8장): 앱에서는 바로 적용
        "set_checkin_time": {"loop": "evening_checkin", "day_type": "weekend", "time": "19:00"},
        # 메모(SP9 6.4)
        "create_memo": {"body": "새 메모"},
        "update_memo": {"id": mo, "body": "고친 메모", "updated_at": mu},
        "pin_memo": {"id": mo},
        "unpin_memo": {"id": mp},
        "delete_memo": {"id": mo},
        # 사진(SP10 5.3)
        "attach_photo": {"memo_id": mo, "photo_id": pf},
        "detach_photo": {"memo_id": mp, "photo_id": pa},
        # 이룬 순간(SP8 6.4). 지우기는 앱에서 늘 확인을 받으므로 토큰을 따로 만든다
        "hide_moment": {"id": mv},
        "unhide_moment": {"id": mh},
        "delete_moment": {"id": md},
        # 스케줄(SP9 5.6): 앱에서 누른 것은 확인 없이
        "create_event": {"title": "치과", "date": "2026-10-27", "time": "14:00"},
        "update_event": {"id": ev, "time": "15:00"},
        "delete_event": {"id": ev, "scope": "one", "date": "2026-10-25"},
        "dismiss_missed_reminder": {"event_id": er, "date": "2026-10-24"},  # 활동은 남기지 않는다
        # 운동 화면(SP12 6.3, 8.2). 기록 지우기는 앱에서 늘 확인을 받으므로 토큰을 따로 만든다
        "drop_body_note": {"id": wn},
        "delete_workout_log": {"id": wl},
        # 객관적 위치(SP13 6.5): 카드의 "저장"과 상세 화면의 지우기. 값은 꾸며 낸 것이다
        "save_measures": {"rows": [{"metric": "weight_kg", "value": 72.0, "measured_on": "2026-10-24"}],
                          "source_kind": "manual", "source_ref": None},
        "delete_measure": {"id": measure},
        # 라이프 매니저(SP15 7.1, 5.4): 제안 둘(받기, 버리기)과 내가 한 말 하나
        "accept_suggestion": {"id": panel[0]},
        "dismiss_suggestion": {"id": panel[1], "reason": "too_big"},
        "retire_statement": {"id": panel[2]},
    }


@pytest.mark.parametrize("action", sorted(n for n, s in ACTIONS.items() if s.public))
async def test_every_public_action_applies(tmp_path, action):
    async with BeEnv.start(tmp_path, start=SAT_1300) as env:
        a, b, c = [await _add(env, t) for t in ("가", "나", "다")]
        await env.action("complete_task", {"id": c})
        d = env.parts.tools.propose_tasks(_ctx(), tasks=[{"title": "초안", "areas": ["health"]}])["proposed"][0]["id"]
        card = env.parts.tools.pin_card(_ctx(), component="ui_summary_card", props=CARD)["id"]
        cv = env.parts.curve
        curve = (
            *(cv.add_milestone(date_text="2019", kind="high", title=t, status="draft", origin="chat").id
              for t in ("꾸민 사건", "꾸민 사건 둘")),
            *(cv.add_chapter(title=t, start_month="2019-01", status="draft", origin="review").id
              for t in ("꾸민 챕터", "꾸민 챕터 둘")),
        )
        hs = env.parts.habits
        hb, hc = (hs.add(t, "health", "daily", None, env.clock.now()).id for t in ("꾸민 습관", "꾸민 습관 둘"))
        hs.check(hc, env.parts.tools.today(), env.clock.now())
        ms = env.parts.memos
        mo, mp = (ms.create(t, None, "user", env.clock.now()) for t in ("꾸민 메모", "꾸민 메모 둘"))
        ms.pin(mp.id, env.clock.now())
        mv, mh, md = (m.id for m in env.parts.moments.save_day(
            env.parts.tools.today(), [(f"꾸민 순간 {i}", None, ["chat"]) for i in (1, 2, 3)], env.clock.now()))
        with transaction(env.conn):
            env.parts.moments.hide(mh, env.clock.now())
        from datetime import date, time

        evs = env.parts.events
        now = env.clock.now()
        ev = evs.create({"title": "꾸민 일정", "start_date": date(2026, 10, 24), "start_time": time(9, 0),
                         "repeat": "daily", "remind_min": 10, "origin": "user"}, now).id
        er = evs.create({"title": "놓친 일정", "start_date": date(2026, 10, 24), "start_time": time(10, 0),
                         "remind_min": 10, "origin": "user"}, now).id
        env.conn.execute(
            "INSERT INTO event_reminders (event_id, occurrence_date, remind_at, outcome, decided_at) "
            "VALUES (?, '2026-10-24', '2026-10-24T00:50:00+00:00', 'missed', '2026-10-24T03:00:00+00:00')", (er,),
        )
        ps = env.parts.tools.photos
        pf, pa = (ps.insert(env.conn, sha256=f"{i:064x}", path=f"2026/10/{i}.jpg", thumb_path=f"2026/10/{i}-t.jpg",
                            bytes=10, width=10, height=10, origin="memo", now=now).id for i in (1, 2))
        ps.attach(env.conn, mp.id, pa)
        env.conn.commit()
        wk = env.parts.tools.workout
        with transaction(env.conn):
            wn = wk.add_note("equipment", "꾸민 장비", now).id
            wl = wk.add_log(env.parts.tools.today(), "꾸민 운동", None, None, None, [], now).id
            measure = env.parts.tools.standing.add("waist_cm", 82.0, date(2026, 10, 24), "manual", None, "mid", now)
            pn = env.parts.panel
            sa, sd = (pn.add_suggestion(
                conversation_id=None, kind="task", title=t, area="career", size_min=30, per_week=None, due_hint=None,
                experts=["career"], evidence=[{"type": "record", "ref": f"task:{a}", "note": "꾸민 근거"}],
                week="2026-W43", now=now,
            ) for t in ("꾸민 제안", "꾸민 제안 둘"))
            st = pn.add_statement("fact", "career", "꾸민 사실", now=now)
        cases = _public_cases((a, b, c, d), card, curve, (hb, hc), (mo.id, mp.id, mo.updated_at.isoformat()),
                              (mv, mh, md), (ev, er), (pf, pa), (wn, wl), measure, (sa, sd, st))
        assert set(cases) == {n for n, s in ACTIONS.items() if s.public}
        args = cases[action]
        token = None
        if action in ("delete_moment", "delete_workout_log"):
            _, ask = await env.action(action, args)
            token = ask["confirm_token"]
        if action == "decline_confirm":
            await env.action("set_priorities", {"cadence": "quarter", "period": "2026-Q4", "task_ids": [a]})
            _, nc = await env.action("set_priorities", {"cadence": "quarter", "period": "2026-Q4", "task_ids": [b]})
            args = {"confirm_token": nc["confirm_token"]}
        before = len(env.activity())
        status, body = await env.action(action, args, confirm_token=token)
        after = env.activity()

    assert status == 200, body
    _validate("ActionApplied", body)
    assert body["status"] == "applied"
    if action == "dismiss_missed_reminder":  # 줄 닫기는 데이터를 바꾸지 않는 표시라 활동이 없다
        assert len(after) == before and body["result"]["dismissed"] is True
        return
    assert len(after) == before + 1 and body["activity_id"] == after[-1]["id"]
    assert (after[-1]["actor"], after[-1]["channel"]) == ("user", "app")


def _ctx():
    from my_planner.domain import RunContext

    return RunContext(conversation_id=None, run_id=None)


async def test_rejected_422_uses_tool_message(tmp_path):
    async with BeEnv.start(tmp_path, start=SAT_1300) as env:
        status, body = await env.action("complete_task", {"id": 999})
        status2, body2 = await env.action("set_priorities", {"cadence": "week", "period": "2026-W43",
                                                             "task_ids": [1, 2, 3, 4]})
        rows = env.activity()

    assert status == 422
    _validate("ActionRejected", body)
    assert body == {"status": "rejected", "activity_id": None,
                    "error": {"code": "rejected", "message": "999번 할 일을 찾을 수 없어요."}}
    assert status2 == 422 and body2["error"]["message"] == "우선순위는 3개까지 정할 수 있어요."
    assert rows == []


async def test_needs_confirm_drop_priority_task_then_apply_with_token(tmp_path):
    async with BeEnv.start(tmp_path, start=SAT_1300) as env:
        tid = await _add(env)
        await env.action("set_priorities", {"cadence": "day", "period": "2026-10-24", "task_ids": [tid]})
        n_before = len(env.activity())
        status, body = await env.action("drop_task", {"id": tid})
        still_open = env.parts.tasks.get(tid).status.value
        n_mid = len(env.activity())
        env.clock.advance(minutes=1)
        status2, body2 = await env.action("drop_task", {"id": tid}, confirm_token=body["confirm_token"])
        row = env.activity()[-1]
        token = _token_row(env, body["confirm_token"])
        dropped = env.parts.tasks.get(tid).status.value

    assert status == 200
    _validate("ActionNeedsConfirm", body)
    assert body["status"] == "needs_confirm" and body["confirm_token"].startswith("ct_")
    assert body["summary"] == "우선순위 할 일을 내려놓아요: 운동"
    assert body["expires_at"] == "2026-10-24T04:10:00Z"  # 10분
    assert still_open == "open" and n_mid == n_before  # 아무것도 바꾸지 않았다
    assert status2 == 200 and body2["status"] == "applied" and dropped == "dropped"
    assert "undo_id" not in body2  # 확인으로 적용한 변경은 되돌릴 수 없다
    assert (row["kind"], row["risk"]) == ("task_dropped", "confirm")
    assert (token["resolution"], token["origin"]) == ("applied", "actions")


async def test_drop_task_without_priority_applies_directly(tmp_path):
    async with BeEnv.start(tmp_path, start=SAT_1300) as env:
        tid = await _add(env)
        status, body = await env.action("drop_task", {"id": tid})
    assert status == 200 and body["status"] == "applied" and body["undo_id"] == body["activity_id"]


async def test_set_priorities_quarter_replacing_nonempty_needs_confirm(tmp_path):
    async with BeEnv.start(tmp_path, start=SAT_1300) as env:
        ids = [await _add(env, t) for t in ("가", "나", "다", "라")]
        q = {"cadence": "quarter", "period": "2026-Q4"}
        await env.action("set_priorities", {**q, "task_ids": ids[:3]})
        status, body = await env.action("set_priorities", {**q, "task_ids": [ids[3]]})
        _, same = await env.action("set_priorities", {**q, "task_ids": ids[:3]})  # 같은 목록은 바로
        _, year = await env.action("set_priorities", {"cadence": "year", "period": "2026", "task_ids": [1]})
        week = [await env.action("set_priorities", {"cadence": "week", "period": "2026-W43", "task_ids": x})
                for x in ([1], [2])]
        kept = [t.id for t in env.parts.tasks.priorities("quarter", "2026-Q4")]

    assert status == 200 and body["status"] == "needs_confirm"
    assert body["summary"] == "이번 분기 우선순위 3개를 바꿔요"
    assert kept == ids[:3]
    assert same["status"] == "applied"
    assert year["status"] == "applied"  # 올해 목록은 비어 있었다
    assert [b["status"] for _, b in week] == ["applied", "applied"]  # 주는 늘 바로


async def test_set_priorities_quarter_first_time_applies(tmp_path):
    async with BeEnv.start(tmp_path, start=SAT_1300) as env:
        tid = await _add(env)
        status, body = await env.action("set_priorities", {"cadence": "quarter", "period": "2026-Q4",
                                                           "task_ids": [tid]})
    assert status == 200 and body["status"] == "applied"
    assert body["confirmation"] == "✓ 우선순위(이번 분기): 1. 운동"


async def _priority_token(env):
    a, b = await _add(env, "가"), await _add(env, "나")
    q = {"cadence": "quarter", "period": "2026-Q4"}
    await env.action("set_priorities", {**q, "task_ids": [a]})
    _, body = await env.action("set_priorities", {**q, "task_ids": [b]})
    return {**q, "task_ids": [b]}, body["confirm_token"]


async def test_confirm_token_used_or_expired_409(tmp_path):
    async with BeEnv.start(tmp_path, start=SAT_1300) as env:
        args, token = await _priority_token(env)
        ok, _ = await env.action("set_priorities", args, confirm_token=token)
        used, used_body = await env.action("set_priorities", args, confirm_token=token)

        other = {**args, "task_ids": [1]}  # 지금 목록 [2]를 바꾼다: 다시 확인이 필요하다
        _, nc = await env.action("set_priorities", other)
        env.clock.advance(minutes=10)
        late, late_body = await env.action("set_priorities", other, confirm_token=nc["confirm_token"])
        expired = _token_row(env, nc["confirm_token"])["resolution"]
        unknown, _ = await env.action("set_priorities", other, confirm_token="ct_nope")
        _, nc2 = await env.action("set_priorities", other)
        mismatch, mismatch_body = await env.action("set_priorities", {**args, "task_ids": [1, 2]},
                                                   confirm_token=nc2["confirm_token"])

    assert ok == 200
    assert used == 409 and used_body == {"error": {"code": "conflict", "message": "이미 정리된 제안이에요."}}
    assert late == 409 and late_body["error"]["code"] == "conflict" and expired == "expired"
    assert unknown == 409
    assert mismatch == 409 and mismatch_body["error"]["message"] == "확인한 제안과 요청이 달라요."


async def test_confirm_token_stale_409(tmp_path):
    async with BeEnv.start(tmp_path, start=SAT_1300) as env:
        tid = await _add(env)
        await env.action("set_priorities", {"cadence": "day", "period": "2026-10-24", "task_ids": [tid]})
        _, nc = await env.action("drop_task", {"id": tid})
        env.clock.advance(minutes=1)
        await env.action("update_task", {"id": tid, "title": "아침 운동"})  # 토큰 뒤에 대상이 바뀌었다
        env.clock.advance(minutes=1)
        status, body = await env.action("drop_task", {"id": tid}, confirm_token=nc["confirm_token"])
        token = _token_row(env, nc["confirm_token"])
        state = env.parts.tasks.get(tid).status.value

    assert status == 409 and body["error"] == {"code": "conflict", "message": "이미 정리된 제안이에요."}
    assert token["resolution"] == "stale" and state == "open"


async def test_decline_confirm_closes_token_changes_nothing(tmp_path):
    async with BeEnv.start(tmp_path, start=SAT_1300) as env:
        args, token = await _priority_token(env)
        before = [t.id for t in env.parts.tasks.priorities("quarter", "2026-Q4")]
        status, body = await env.action("decline_confirm", {"confirm_token": token})
        after = [t.id for t in env.parts.tasks.priorities("quarter", "2026-Q4")]
        row = env.activity()[-1]
        resolution = _token_row(env, token)["resolution"]
        again, _ = await env.action("decline_confirm", {"confirm_token": token})
        apply_after, _ = await env.action("set_priorities", args, confirm_token=token)

    assert status == 200 and body["status"] == "applied" and "undo_id" not in body
    assert before == after
    assert row["kind"] == "confirm_declined" and row["undo_json"] is None and token not in row["summary"]
    assert row["summary"] == "✗ 그대로 뒀어요 (이번 분기 우선순위 1개를 바꿔요)"
    assert resolution == "declined"
    assert again == 409 and apply_after == 409


async def test_duplicate_client_msg_id_returns_first_response(tmp_path):
    async with BeEnv.start(tmp_path, start=SAT_1300) as env:
        tid = await _add(env)
        first = await env.action("complete_task", {"id": tid}, client_msg_id="dup-1")
        env.clock.advance(minutes=1)
        second = await env.action("complete_task", {"id": tid}, client_msg_id="dup-1")
        rejected = await env.action("complete_task", {"id": tid}, client_msg_id="dup-2")  # 이미 완료: 422
        rejected_again = await env.action("complete_task", {"id": tid}, client_msg_id="dup-2")
        n = len([r for r in env.activity() if r["kind"] == "task_completed"])

    assert first == second and first[0] == 200
    assert n == 1
    assert rejected == rejected_again and rejected[0] == 422


async def test_missing_client_msg_id_400(tmp_path):
    async with BeEnv.start(tmp_path, start=SAT_1300) as env:
        tid = await _add(env)
        missing = await env.post("/actions", json={"action": "complete_task", "args": {"id": tid}})
        not_json = await env.post("/actions", data=b"{not json", headers={"Content-Type": "application/json"})
        not_object = await env.post("/actions", json=[1, 2])
        no_token = await env.post("/actions", token=None, json={"action": "complete_task", "args": {"id": tid},
                                                                 "client_msg_id": "x"})
        bodies = [await r.json() for r in (missing, not_json, not_object)]
        state = env.parts.tasks.get(tid).status.value

    assert [r.status for r in (missing, not_json, not_object)] == [400, 400, 400]
    for b in bodies:
        _validate("Error", b)
        assert b["error"]["code"] == "invalid_request"
    assert no_token.status == 401
    assert state == "open"


@pytest.mark.parametrize(
    ("action", "args"),
    [("propose_tasks", {"tasks": []}), ("grant_xp", {}), ("expire_drafts", {}), ("prune_api_state", {}),
     ("complete_task", {"id": 1, "extra": True})],
)
async def test_unknown_or_internal_action_400(tmp_path, action, args):
    async with BeEnv.start(tmp_path, start=SAT_1300) as env:
        await _add(env)
        status, body = await env.action(action, args, client_msg_id="cm-x")
        stored = env.conn.execute("SELECT count(*) FROM api_idempotency WHERE client_msg_id = 'cm-x'").fetchone()[0]

    assert status == 400 and body["error"]["code"] == "invalid_request"
    assert stored == 0


async def test_actions_result_and_idempotency_atomic(tmp_path, monkeypatch):
    async with BeEnv.start(tmp_path, start=SAT_1300) as env:
        tid = await _add(env)
        n_activity = len(env.activity())
        n_idem = env.conn.execute("SELECT count(*) FROM api_idempotency").fetchone()[0]

        def boom(*a, **kw):
            raise RuntimeError("boom")

        real_put = env.parts.idempotency.put
        monkeypatch.setattr(env.parts.idempotency, "put", boom)
        status, body = await env.action("complete_task", {"id": tid}, client_msg_id="atomic-1")
        state = env.parts.tasks.get(tid).status.value
        rows = (len(env.activity()), env.conn.execute("SELECT count(*) FROM api_idempotency").fetchone()[0])
        events = env.conn.execute("SELECT count(*) FROM tool_events_log WHERE kind = 'task_completed'").fetchone()[0]
        export = env.parts.tools.export_path.read_text(encoding="utf-8")
        expected = tmp_path / "expected.md"
        export_tasks(env.parts.tasks, expected, env.parts.tools.today())  # 되돌린 DB에서 다시 만든 모양
        monkeypatch.setattr(env.parts.idempotency, "put", real_put)
        retry, retry_body = await env.action("complete_task", {"id": tid}, client_msg_id="atomic-1")
        state_after = env.parts.tasks.get(tid).status.value

    assert status == 500 and body["error"]["code"] == "internal"
    assert state == "open" and rows == (n_activity, n_idem) and events == 0
    assert export == expected.read_text(encoding="utf-8")  # tasks.md도 DB와 같다(완료로 남지 않았다)
    assert retry == 200 and retry_body["status"] == "applied" and state_after == "done"


async def test_actions_log_has_no_title_args_or_token(tmp_path, caplog):
    import logging

    caplog.set_level(logging.DEBUG)
    async with BeEnv.start(tmp_path, start=SAT_1300) as env:
        tid = await _add(env, "꾸민제목문장")
        await env.action("set_priorities", {"cadence": "day", "period": "2026-10-24", "task_ids": [tid]})
        _, nc = await env.action("drop_task", {"id": tid})
        await env.action("drop_task", {"id": tid}, confirm_token=nc["confirm_token"])
        await env.action("record_condition", {"score": 3, "note": "꾸민메모문장"})

    text = "\n".join(f"{r.getMessage()} {r.__dict__}" for r in caplog.records)
    assert "action_handled" in text
    for secret in ("꾸민제목문장", "꾸민메모문장", nc["confirm_token"]):
        assert secret not in text


@pytest.mark.parametrize("which", ["old", "new"])
async def test_priorities_token_stale_when_listed_task_dropped(tmp_path, which):
    """분기 우선순위 토큰 뒤에 지금 목록이나 새 목록의 할 일을 내려놓으면 그 토큰은 stale(409)이다."""
    async with BeEnv.start(tmp_path, start=SAT_1300) as env:
        old, new = await _add(env, "가"), await _add(env, "나")
        q = {"cadence": "quarter", "period": "2026-Q4"}
        await env.action("set_priorities", {**q, "task_ids": [old]})
        _, nc = await env.action("set_priorities", {**q, "task_ids": [old, new]})
        env.clock.advance(minutes=1)
        victim = old if which == "old" else new
        st, body = await env.action("drop_task", {"id": victim})
        if body["status"] == "needs_confirm":  # 지금 분기 우선순위인 할 일은 내려놓기도 확인을 받는다
            st, body = await env.action("drop_task", {"id": victim}, confirm_token=body["confirm_token"])
        assert (st, body["status"]) == (200, "applied")
        env.clock.advance(minutes=1)
        status, err = await env.action("set_priorities", {**q, "task_ids": [old, new]},
                                       confirm_token=nc["confirm_token"])
        resolution = _token_row(env, nc["confirm_token"])["resolution"]
        kept = [t.id for t in env.parts.tasks.priorities("quarter", "2026-Q4")]

    assert status == 409 and err["error"]["code"] == "conflict"
    assert resolution == "stale"
    assert kept == ([] if which == "old" else [old])


def test_needs_confirm_without_confirms_repo_never_applies(tmp_path, conn):
    from test_activity import ActivityEnv

    from my_planner.tools.actions import ActionDeps, ActionRequest, apply_action

    env = ActivityEnv(tmp_path, conn)
    tid = env.tools.add_task(env.ctx(), title="운동", areas=["health"])["id"]
    env.tools.set_priorities(env.ctx(), cadence="day", period="2026-10-24", task_ids=[tid])
    deps = ActionDeps(tools=env.tools, clock=env.clock, activity=env.activity, confirms=None)
    with pytest.raises(RuntimeError):
        apply_action(deps, ActionRequest("drop_task", {"id": tid}, actor="user", channel="app"))
    assert env.repo.get(tid).status.value == "open"


@pytest.mark.parametrize("which", ["old", "new"])
async def test_drop_token_stale_after_set_priorities_touches_task(tmp_path, which):
    """`drop_task` 토큰 뒤에 그 할 일이 든(빠지거나 들어온) 목록을 바꾸면 그 토큰은 stale(409)이다."""
    async with BeEnv.start(tmp_path, start=SAT_1300) as env:
        a, b = await _add(env, "가"), await _add(env, "나")
        day = {"cadence": "day", "period": "2026-10-24"}
        await env.action("set_priorities", {**day, "task_ids": [a]})
        await env.action("set_priorities", {"cadence": "week", "period": "2026-W43", "task_ids": [b]})
        victim = a if which == "old" else b
        _, nc = await env.action("drop_task", {"id": victim})
        assert nc["status"] == "needs_confirm"
        env.clock.advance(minutes=1)
        # 오늘 목록을 바꾼다: old는 a가 빠지고, new는 b가 들어온다
        await env.action("set_priorities", {**day, "task_ids": [b] if which == "old" else [a, b]})
        row = env.activity()[-1]
        targets = env.parts.activity.targets(row["id"])
        env.clock.advance(minutes=1)
        status, err = await env.action("drop_task", {"id": victim}, confirm_token=nc["confirm_token"])
        resolution = _token_row(env, nc["confirm_token"])["resolution"]
        state = env.parts.tasks.get(victim).status.value

    assert row["kind"] == "priorities_set" and row["target"] == "priorities:day:2026-10-24"
    assert set(targets) == {"priorities:day:2026-10-24", f"task:{a}", f"task:{b}"}
    assert status == 409 and err["error"]["code"] == "conflict"
    assert resolution == "stale" and state == "open"


# --- SP6 G-BE2: 앱 통로 `move_task` (SP6 8장, Review Focus 3). 시각 있는 할 일의 옮기기 확인은 SP9-05에서 없어졌다 ---


async def test_app_move_task_unscheduled_applies(tmp_path):
    async with BeEnv.start(tmp_path, start=SAT_1300) as env:
        tid = await _add(env, "꾸민 산책")
        status, body = await env.action("move_task", {"id": tid, "planned_for": "2026-10-27"})
        planned = env.parts.tasks.get(tid).planned_for.isoformat()
    assert status == 200 and body["status"] == "applied" and body["undo_id"] == body["activity_id"]
    assert planned == "2026-10-27"


@pytest.mark.parametrize("state", ["done", "dropped"])
async def test_move_task_rejects_non_open(tmp_path, state):
    """그린 뒤 다른 곳에서 끝내거나 뺀 할 일의 날짜 후보 누름: `rejected`이고 할 일은 그대로다. 두뇌도 같다."""
    from my_planner.domain import RunContext

    async with BeEnv.start(tmp_path, start=SAT_1300) as env:
        tid = await _add(env, "꾸민 할 일")
        await env.action("complete_task" if state == "done" else "drop_task", {"id": tid})
        n_before = len(env.activity())
        status, body = await env.action("move_task", {"id": tid, "planned_for": "2026-10-27"})
        brain = env.parts.tools.move_task(RunContext(conversation_id=1, run_id=None, channel="app"),
                                          id=tid, planned_for="2026-10-27")
        t = env.parts.tasks.get(tid)
        n_after = len(env.activity())

    assert status == 422
    _validate("ActionRejected", body)
    assert body["error"]["message"] == "열린 할 일만 날짜를 옮길 수 있어요."
    assert brain == {"error": "열린 할 일만 날짜를 옮길 수 있어요."}
    assert t.status.value == state and t.planned_for is None and n_after == n_before
