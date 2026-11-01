"""`GET /schema`, `python -m my_planner schema`, UI 카탈로그 (SP3-4 스펙 6.4, 6.4.7). 내용은 꾸며 낸 것이다."""

import json
from datetime import date, timedelta

import jsonschema
import pytest
from be_env import BeEnv
from fakes import FakeTurn
from test_api_read import get_json, mk, propose
from test_dispatcher_messages import kst

from my_planner import cli
from my_planner.api.models import MODELS, schema_bundle
from my_planner.domain import Cadence, LoopKey
from my_planner.tools.ui import UI_CATALOG_VERSION, UI_COMPONENTS, validate_props

MON_EVENING = kst(2026, 10, 26, 17, 30) + timedelta(seconds=30)

EXPECTED_MODELS = {
    "Error", "Health", "SafeModeHealth", "Todo", "TodoRef", "TodoRefs", "Today", "Week", "Conditions",
    "Priorities", "Drafts", "Curve", "Status", "CheckinList", "CheckinSummary", "CheckinDetail", "Conversations", "ConversationsClosed", "Messages",
    "UiCatalog", "SchemaBundle", "ActionRequestBody", "ActionApplied", "ActionNeedsConfirm", "ActionRejected",
    "UndoRequestBody", "UndoResponse", "ActivityResponse", "ChatRequestBody",
    "ChatStopBody", "ChatStopped",  # 답 멈추기
    "VapidPublicKey", "PushSubscribeBody", "PushSubscribed", "PushTestResult", "NotifySettings", "NotifyPutBody",
    "Habit", "HabitsList", "Workout", "HabitHistory", "ClientErrorBody", "RecoveryNoticeBody", "RecoveryNoticeSent",
    "CheckinTimes", "CheckinTimePutBody", "CheckinTimesUpdated",  # SP9 8장
    "DigestSlot", "DigestSettings", "DigestSettingPutBody", "DigestSettingsUpdated",  # SP9b 5장
    "Memo", "MemoItem", "MemoList",  # SP9 6.4
    "PhotoRef", "PhotoUploaded", "PhotoRead",  # SP10 5.3
    "Moment", "MomentsList",  # SP8 6.5
    "BodyPostBody", "BodySaved",  # SP8 7.3
    "CurveHistory",  # SP8 8.2
    "PairCreated", "PairStatus", "PairBody", "PairResult", "DeviceList",  # 기기 연결 스펙 4.5
    "EventItem", "EventList", "EventDetail", "MissedReminder",  # SP9 5.6
    "CalendarSettings", "CalendarPutBody",  # SP9 5.7
    "Standing", "StandingMeasures",  # SP13 12장
    "InboxCount", "AgentNotes", "AgentNoteOut",  # SP14 스펙 9장
}


async def test_schema_lists_all_models(tmp_path):
    async with BeEnv.start(tmp_path, start=MON_EVENING) as env:
        body = await get_json(env, "/schema")
        assert (await env.get("/schema", token=None)).status == 401
    assert body["api"] == "v1"
    assert set(body["models"]) == EXPECTED_MODELS == set(MODELS)
    for name, schema in body["models"].items():
        jsonschema.Draft202012Validator.check_schema(schema)
        assert schema["type"] == "object", name
    assert body == json.loads(json.dumps(schema_bundle()))
    # 필드 이름은 별칭(`from`, `schema`)으로 나간다
    assert "from" in body["models"]["Conditions"]["properties"]
    assert "schema" in json.dumps(body["models"]["UiCatalog"])
    todo_ref = body["models"]["TodoRef"]
    assert set(todo_ref["properties"]) == {"id", "title", "cadence", "area", "status", "planned_for", "scheduled_at"}
    assert set(todo_ref["required"]) == set(todo_ref["properties"])  # 값이 없으면 null(SP6 10.2)


async def test_every_read_response_validates_against_schema(tmp_path):
    script = [FakeTurn([propose("가벼운 스트레칭")], "오늘 어떠셨어요?"), FakeTurn([], "네")]
    async with BeEnv.start(tmp_path, start=MON_EVENING, script=script) as env:
        a = mk(env, "수채화 연습", planned_for="2026-10-26", scheduled_at=kst(2026, 10, 26, 20, 0))
        mk(env, "내일 할 일", planned_for="2026-10-27")
        for cadence, period in ((Cadence.day, "2026-10-26"), (Cadence.week, "2026-W44"), (Cadence.quarter, "2026-Q4")):
            env.parts.tasks.set_priorities(cadence, period, [a.id])
        env.parts.conditions.upsert(date(2026, 10, 25), 4, "산책함")
        env.parts.conditions.upsert(date(2026, 10, 26), 2, None)
        await env.tick()
        await env.telegram("저녁 루틴 도와 줘")
        runs = env.parts.runs
        morning = runs.ensure(LoopKey.morning_brief, kst(2026, 10, 26, 9, 0))
        runs.save_outbound(morning.id, "좋은 아침")
        runs.mark_done(morning.id)
        checkin = next(
            i for i in (await get_json(env, "/checkins?date=2026-10-26"))["items"] if i["loop"] == "evening_checkin"
        )
        convs = await get_json(env, "/conversations")
        cid = convs["items"][0]["id"]
        paths = [
            "/health", "/today", "/week", "/conditions", "/priorities?cadence=week", "/priorities?cadence=quarter",
            "/drafts", "/checkins", f"/checkins/{checkin['id']}", "/conversations", f"/conversations/{cid}/messages",
            "/ui/catalog", "/schema", "/standing", "/standing/measures",
        ]
        bodies = {p: await get_json(env, p) for p in paths}
        err = await (await env.get("/checkins/abc")).json()

    schemas = schema_bundle()["models"]
    by_path = {
        "/health": "Health", "/today": "Today", "/week": "Week", "/conditions": "Conditions",
        "/priorities?cadence=week": "Priorities", "/priorities?cadence=quarter": "Priorities", "/drafts": "Drafts",
        "/checkins": "CheckinList", f"/checkins/{checkin['id']}": "CheckinDetail", "/conversations": "Conversations",
        f"/conversations/{cid}/messages": "Messages", "/ui/catalog": "UiCatalog", "/schema": "SchemaBundle",
        "/standing": "Standing", "/standing/measures": "StandingMeasures",
    }
    for path, model in by_path.items():
        jsonschema.Draft202012Validator(schemas[model]).validate(bodies[path])
    jsonschema.Draft202012Validator(schemas["Error"]).validate(err)
    # 시험이 빈 응답만 검사하지 않았는지
    assert bodies["/today"]["todos"] and bodies["/today"]["checkins"] and bodies["/week"]["priorities"]
    assert bodies["/drafts"]["items"] and bodies["/conditions"]["items"] and bodies["/priorities?cadence=quarter"]["items"]
    assert bodies[f"/checkins/{checkin['id']}"]["cards"] and bodies[f"/conversations/{cid}/messages"]["items"]


def test_schema_includes_habit_models():
    """SP7 5.5: `Habit`, `HabitsList`, `HabitHistory`(`from` 별칭), `Today.habits`. 앱 타입은 이 스키마로 다시 만든다."""
    models = schema_bundle()["models"]
    habit = models["Habit"]
    assert set(habit["properties"]) == set(habit["required"]) == {
        "id", "title", "area", "kind", "target_per_week", "status", "checked", "week_count",
    }
    assert habit["properties"]["kind"]["enum"] == ["daily", "weekly"]
    assert habit["properties"]["status"]["enum"] == ["active", "paused", "archived"]
    assert habit["additionalProperties"] is False
    assert set(models["HabitsList"]["properties"]) == {"date", "week", "items"}
    history = models["HabitHistory"]
    assert set(history["properties"]) == {"habit", "from", "to", "checked_dates", "weeks"}
    assert set(history["$defs"]["HabitWeek"]["properties"]) == {"week", "count"}
    assert "habits" in models["Today"]["required"]
    assert models["Today"]["properties"]["habits"]["items"] == {"$ref": "#/$defs/Habit"}


def test_today_sp9_fields_not_required():
    """스펙 14: 앱이 BE보다 먼저 배포되거나 BE가 되돌아가도 `/today`가 모양 검사를 넘도록 SP9 칸은 required가 아니다."""
    from my_planner.api.models import Today

    today = schema_bundle()["models"]["Today"]
    assert {"events", "missed_reminders"} <= set(today["properties"])
    assert not {"events", "missed_reminders"} & set(today["required"])
    old = Today.model_validate({
        "date": "2026-10-26", "weekday": "월", "day_boundary": "04:00", "brief": None, "condition": None,
        "todos": [], "checkins": [], "cards": [], "habits": [],
    })
    assert (old.events, old.missed_reminders) == ([], [])


def test_cli_schema_prints_bundle(capsys):
    assert cli.main(["schema"]) == 0
    out = capsys.readouterr().out
    assert json.loads(out) == json.loads(json.dumps(schema_bundle()))
    assert set(json.loads(out)["models"]) == EXPECTED_MODELS
    assert cli.main(["nope"]) == cli.EXIT_USAGE


async def test_ui_catalog_version_and_components(tmp_path):
    async with BeEnv.start(tmp_path, start=MON_EVENING) as env:
        body = await get_json(env, "/ui/catalog")
        health = await get_json(env, "/health")
    assert body["version"] == UI_CATALOG_VERSION == "2026-11-01.1"
    assert health["version"]["ui_catalog"] == body["version"]
    assert list(body["components"]) == [
        "ui_todo_list", "ui_choice", "ui_summary_card", "ui_date_choice", "ui_result", "ui_period_list", "ui_block", "ui_habit_check",
        "ui_events", "ui_todo_draft", "ui_condition_picker", "ui_ladder_picker", "ui_area_scores", "ui_milestone_draft",
        "ui_chapter_draft", "ui_confirm", "ui_measure_confirm",
    ]
    assert len(body["components"]) == 17 == len(UI_COMPONENTS)
    origins = {name: c["origin"] for name, c in body["components"].items()}
    assert [n for n, o in origins.items() if o == "brain"] == [
        "ui_todo_list", "ui_choice", "ui_summary_card", "ui_date_choice", "ui_result", "ui_period_list", "ui_block", "ui_habit_check",
        "ui_events",
    ]
    for name, c in body["components"].items():
        jsonschema.Draft202012Validator.check_schema(c["schema"])
        assert c["schema"]["additionalProperties"] is False, name
    s = {n: c["schema"]["properties"] for n, c in body["components"].items()}
    assert s["ui_milestone_draft"]["milestone_ids"]["minItems"] == 1 and s["ui_milestone_draft"]["milestone_ids"]["maxItems"] == 10
    assert s["ui_chapter_draft"]["chapter_ids"]["minItems"] == 1 and s["ui_chapter_draft"]["chapter_ids"]["maxItems"] == 5
    assert s["ui_todo_list"]["task_ids"]["maxItems"] == 30
    assert (s["ui_choice"]["options"]["minItems"], s["ui_choice"]["options"]["maxItems"]) == (2, 4)
    assert s["ui_summary_card"]["lines"]["maxItems"] == 8 and s["ui_summary_card"]["lines"]["items"]["maxLength"] == 120
    assert s["ui_ladder_picker"]["field"]["enum"] == ["now", "future"]


@pytest.mark.parametrize(
    ("component", "props", "ok"),
    [
        ("ui_todo_list", {"title": "오늘", "task_ids": list(range(30))}, True),
        ("ui_todo_list", {"title": "오늘", "task_ids": list(range(31))}, False),
        ("ui_choice", {"question": "어느 쪽?", "options": [{"id": "a", "label": "산책"}, {"id": "b", "label": "독서"}]}, True),
        ("ui_choice", {"question": "어느 쪽?", "options": [{"id": "a", "label": "산책"}]}, False),
        ("ui_choice", {"question": "?", "options": [{"id": str(i), "label": "x"} for i in range(5)]}, False),
        ("ui_summary_card", {"title": "정리", "lines": ["가" * 120] * 8}, True),
        ("ui_summary_card", {"title": "정리", "lines": ["가" * 121]}, False),
        ("ui_summary_card", {"title": "정리", "lines": ["가"] * 9}, False),
        ("ui_condition_picker", {"date": "2026-10-24"}, True),
        ("ui_condition_picker", {"date": "10/24"}, False),
        ("ui_milestone_draft", {"milestone_ids": list(range(1, 11))}, True),
        ("ui_milestone_draft", {"milestone_ids": list(range(1, 12))}, False),
        ("ui_milestone_draft", {"milestone_ids": []}, False),
        ("ui_chapter_draft", {"chapter_ids": [1, 2, 3, 4, 5]}, True),
        ("ui_chapter_draft", {"chapter_ids": [1, 2, 3, 4, 5, 6]}, False),
        ("ui_chapter_draft", {"chapter_ids": ["1"]}, False),
        ("ui_todo_draft", {"task_ids": [1, 2], "extra": 1}, False),
        ("ui_area_scores", {"period": "2026-Q4", "previous": {"health": 7}}, True),
        ("ui_area_scores", {"period": "2026-Q4", "previous": {"health": 11}}, False),
        ("ui_nope", {}, False),
        ("ui_todo_draft", "문자열", False),
    ],
)
def test_validate_props(component, props, ok):
    assert (validate_props(component, props) is None) is ok


def test_validate_props_error_never_echoes_values():
    secret = "비밀스러운 제목"
    msg = validate_props("ui_todo_list", {"title": secret, "task_ids": "no"})
    assert msg is not None and secret not in msg and "no" not in msg
    assert secret not in (validate_props("ui_summary_card", {"title": secret, "lines": [secret * 100]}) or "")


