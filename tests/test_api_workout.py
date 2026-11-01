"""운동 API (SP12 스펙 11.3): `GET /workout`, 새 동작 `drop_body_note`·`delete_workout_log`, `GET /health`의 `features`.
내용은 모두 꾸며 낸 것이다."""

from datetime import timedelta

import jsonschema
from be_env import BeEnv
from test_api_read import get_json
from test_dispatcher_messages import kst

from my_planner.api.models import schema_bundle
from my_planner.store.repos.workout import LogItem, PlanItem

SAT = kst(2026, 10, 24, 13, 0)  # 토요일, 논리적 날짜 2026-10-24


def _validate(model, body):
    jsonschema.Draft202012Validator(schema_bundle()["models"][model]).validate(body)


async def test_get_workout_empty(tmp_path):
    async with BeEnv.start(tmp_path, start=SAT) as env:
        body = await get_json(env, "/workout")
    _validate("Workout", body)
    assert body == {"plan": None, "logs": [], "notes": []}


async def test_get_workout_shapes(tmp_path):
    async with BeEnv.start(tmp_path, start=SAT) as env:
        wk = env.parts.tools.workout
        now = env.clock.now()
        today = env.parts.tools.today()
        _, plan_id = wk.replace_plan(
            "꾸민 플랜", "가볍게",
            [("하체", (0, 3), [PlanItem("고블릿 스쿼트", 3, "8-10", 16.0, None, "천천히")]),
             ("걷기", None, [PlanItem("걷기", None, None, None, 30, None)])],
            now,
        )
        kept = wk.add_log(
            today - timedelta(days=1), "하체", None, 3, "괜찮았다",
            [LogItem("스쿼트", 5, 5, 60.0, None, None), LogItem("러닝", None, None, None, 20, 3.5)], now,
        )
        wk.add_log(today - timedelta(days=29), "너무 옛날", None, None, None, [], now)  # 28일 창 밖
        note = wk.add_note("injury", "꾸민 무릎 메모", now)
        env.conn.commit()
        body = await get_json(env, "/workout")

    _validate("Workout", body)
    plan = body["plan"]
    assert (plan["id"], plan["title"], plan["note"]) == (plan_id, "꾸민 플랜", "가볍게")
    assert [(s["position"], s["label"], s["weekdays"]) for s in plan["sessions"]] == [
        (1, "하체", [0, 3]), (2, "걷기", None),
    ]
    assert plan["sessions"][0]["items"] == [
        {"name": "고블릿 스쿼트", "sets": 3, "reps": "8-10", "weight_kg": 16.0, "minutes": None, "note": "천천히"}
    ]
    assert [lg["id"] for lg in body["logs"]] == [kept.id]
    assert body["logs"][0] == {
        "id": kept.id, "date": "2026-10-23", "title": "하체", "session_id": None, "effort": 3, "note": "괜찮았다",
        "items": [
            {"name": "스쿼트", "sets": 5, "reps": 5, "weight_kg": 60.0, "minutes": None, "distance_km": None},
            {"name": "러닝", "sets": None, "reps": None, "weight_kg": None, "minutes": 20, "distance_km": 3.5},
        ],
    }
    assert [(n["id"], n["kind"], n["text"]) for n in body["notes"]] == [(note.id, "injury", "꾸민 무릎 메모")]
    assert body["notes"][0]["updated_at"].endswith("Z")


async def test_actions_drop_note_and_delete_log(tmp_path):
    async with BeEnv.start(tmp_path, start=SAT) as env:
        wk = env.parts.tools.workout
        now = env.clock.now()
        note = wk.add_note("equipment", "꾸민 장비", now)
        log = wk.add_log(env.parts.tools.today(), "꾸민 운동", None, None, None, [], now)

        status, dropped = await env.action("drop_body_note", {"id": note.id})
        status2, ask = await env.action("delete_workout_log", {"id": log.id})
        status3, done = await env.action("delete_workout_log", {"id": log.id}, confirm_token=ask["confirm_token"])
        after = await get_json(env, "/workout")

    assert status == 200 and dropped["status"] == "applied" and dropped["undo_id"] == dropped["activity_id"]
    assert status2 == 200 and ask["status"] == "needs_confirm" and ask["confirm_token"].startswith("ct_")
    assert status3 == 200 and done["status"] == "applied"
    assert after["notes"] == [] and after["logs"] == []


async def test_health_features_has_mate(tmp_path):
    async with BeEnv.start(tmp_path, start=SAT) as env:
        body = await get_json(env, "/health")
    assert body["features"] == ["mate"]
