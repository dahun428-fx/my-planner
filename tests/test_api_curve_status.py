"""`GET /curve`, `GET /status` (SP3-4 스펙 6.3.5, 6.3.6). 고정 자료는 SQL, 내용은 모두 꾸며 낸 것이다."""

import jsonschema
import pytest
from be_env import BeEnv
from curve_sql import area_scores, chapter, ladder, milestone, title, xp
from test_api_read import get_json, mk
from test_dispatcher_messages import kst

from my_planner.api.models import schema_bundle
from my_planner.domain import Area, Cadence, TaskStatus

SAT = kst(2026, 10, 24, 13, 0)


async def test_curve_excludes_drafts_and_sensitive_by_default(tmp_path):
    async with BeEnv.start(tmp_path, start=SAT) as env:
        c = env.conn
        ch = chapter(c, "꾸민 챕터", "2025-01", sketch="↑", certainty="estimate")
        chapter(c, "초안 챕터", "2025-06", status="draft")
        chapter(c, "옛 챕터", "2010-01", "2012-12")  # 범위 밖
        milestone(c, "보이는 사건", "2026-03", kind="turning_point", chapter_id=ch, note="꾸민 메모")
        milestone(c, "민감 사건", "2026-04-02", kind="low", sensitive=1)
        milestone(c, "초안 사건", "2026-05-01", status="draft")
        milestone(c, "범위 밖 사건", "2020")
        milestone(c, "연 단위 사건", "2024", precision="year")  # 2024-11-01~ 범위와 겹친다
        ladder(c, "2026-09", now=5, future=7)
        ladder(c, "2026-10", future=8)
        ladder(c, "2020-01", now=3)
        area_scores(c, "2026-Q3", career=6, health=4)
        area_scores(c, "2026-Q4", career=7)
        area_scores(c, "2019-Q1", career=2)
        c.commit()
        body = await get_json(env, "/curve")

    assert (body["zoom"], body["from"], body["to"]) == ("month", "2024-11-01", "2026-10-31")
    assert [x["title"] for x in body["chapters"]] == ["꾸민 챕터"]
    assert body["chapters"][0] == {
        "id": ch, "title": "꾸민 챕터", "theme": "꾸민 주제", "start": "2025-01", "end": None, "sketch": "↑",
        "certainty": "estimate",
    }
    assert [m["title"] for m in body["milestones"]] == ["연 단위 사건", "보이는 사건"]
    assert body["milestones"][1] == {
        "id": body["milestones"][1]["id"], "date": "2026-03", "precision": "month", "kind": "turning_point",
        "title": "보이는 사건", "note": "꾸민 메모", "chapter_id": ch, "sensitive": False, "certainty": "fact",
    }
    assert body["ladder"] == [
        {"period": "2026-09", "now": 5, "future": 7, "note": None},
        {"period": "2026-10", "now": None, "future": 8, "note": None},
    ]
    assert body["areas"] == [
        {"period": "2026-Q3", "scores": {"career": 6, "health": 4}},
        {"period": "2026-Q4", "scores": {"career": 7}},
    ]
    assert len(body["condition"]) == 24 and body["condition"][-1]["bucket"] == "2026-10"
    assert [r["period"] for r in body["reassurance"]] == ["2026-09"]  # 5년 뒤만 있는 달은 뺀다


async def test_include_sensitive_true_marks_flag(tmp_path):
    async with BeEnv.start(tmp_path, start=SAT) as env:
        milestone(env.conn, "민감 사건", "2026-04-02", kind="low", sensitive=1)
        sens_hi = milestone(env.conn, "민감 고점", "2026-05-02", kind="high", sensitive=1)
        title(env.conn, sens_hi)
        env.conn.commit()
        off = await get_json(env, "/curve?include_sensitive=false&zoom=quarter")
        on = await get_json(env, "/curve?include_sensitive=true&zoom=quarter")
        status_off = await get_json(env, "/status")
        status_on = await get_json(env, "/status?include_sensitive=true")
    assert off["milestones"] == [] and off["zoom"] == "quarter"
    assert [(m["title"], m["sensitive"]) for m in on["milestones"]] == [("민감 사건", True), ("민감 고점", True)]
    assert status_off["titles"] == [] and [t["milestone_id"] for t in status_on["titles"]] == [sens_hi]


@pytest.mark.parametrize(
    "query",
    [
        "zoom=decade", "zoom=", "include_sensitive=1", "include_sensitive=True", "from=2026-1-1", "to=내일",
        "from=2026-13-01", "from=2026-10-02&to=2026-10-01", "zoom=day&from=2025-01-01&to=2026-10-24",
        "from=0001-01-01&to=9999-12-31&zoom=day", "zoom=month&to=0001-06-01", "zoom=week&to=0001-01-03",
        "zoom=quarter&to=0001-02-01", "zoom=day&to=0001-01-05",
    ],
)
async def test_curve_bad_query_400(tmp_path, query):
    async with BeEnv.start(tmp_path, start=SAT) as env:
        resp = await env.get(f"/curve?{query}")
        body = await resp.json()
        status = await env.get("/status?include_sensitive=yes")
    assert resp.status == 400 and body["error"]["code"] == "invalid_request"
    assert status.status == 400
    # 요청 값을 되돌려 주지 않는다
    for pair in query.split("&"):
        value = pair.split("=", 1)[1]
        assert not value or value not in body["error"]["message"]
    if query in ("zoom=day&from=2025-01-01&to=2026-10-24", "from=0001-01-01&to=9999-12-31&zoom=day"):
        assert body["error"]["message"] == "범위를 줄이거나 확대 단위를 키워 주세요"


async def test_curve_from_to_and_year_zoom(tmp_path):
    async with BeEnv.start(tmp_path, start=SAT) as env:
        chapter(env.conn, "꾸민 시작", "2019-03")
        env.conn.commit()
        year = await get_json(env, "/curve?zoom=year")
        day = await get_json(env, "/curve?zoom=day&from=2026-10-01&to=2026-10-03")
        only_to = await get_json(env, "/curve?zoom=quarter&to=2024-12-31")
    assert (year["from"], year["to"], len(year["condition"])) == ("2019-01-01", "2026-12-31", 8)
    assert [c["bucket"] for c in day["condition"]] == ["2026-10-01", "2026-10-02", "2026-10-03"]
    assert (only_to["from"], only_to["to"], len(only_to["condition"])) == ("2020-01-01", "2024-12-31", 20)


async def test_status_endpoint_shape(tmp_path):
    async with BeEnv.start(tmp_path, start=SAT) as env:
        t = mk(env, "꾸민 분기 목표", planned_for=None)
        env.parts.tasks.set_priorities(Cadence.quarter, "2026-Q4", [t.id])
        env.parts.tasks.create("첫 걸음", [Area.career], TaskStatus.open, None, None, t.id, "")
        area_scores(env.conn, "2026-Q3", health=6)
        area_scores(env.conn, "2026-Q4", health=4)
        xp(env.conn, "task:1", 10, "2026-10-24T01:00:00.000000+00:00")
        env.conn.commit()
        body = await get_json(env, "/status")
        unauth = await env.get("/status", token=None)
    assert unauth.status == 401
    assert (body["level"], body["xp_total"], body["xp_into_level"], body["xp_for_next"]) == (1, 10, 10, 150)
    assert body["recent_xp"] == [{"at": "2026-10-24T01:00:00Z", "label": "할 일 완료", "amount": 10}]
    health = next(s for s in body["stats"] if s["area"] == "health")
    assert health["debuff"] is True and health["recovery_quest"] == "20분 걷기" and health["label"] == "건강"
    assert body["main_quests"][0]["first_steps"] == {"open": 1, "done": 0}
    assert body["daily_quests"][0]["parent_title"] == "꾸민 분기 목표"


async def test_curve_and_status_validate_against_schema(tmp_path):
    async with BeEnv.start(tmp_path, start=SAT) as env:
        c = env.conn
        ch = chapter(c, "꾸민 챕터", "2025-01", sketch="↑")
        hi = milestone(c, "꾸민 고점", "2026-03", chapter_id=ch)
        title(c, hi)
        for d in range(1, 11):
            c.execute(
                "INSERT INTO conditions (date, score, note, recorded_at) VALUES (?, ?, NULL, ?)",
                (f"2026-09-{d:02d}", 3 + d % 2, "2026-09-30T00:00:00.000000+00:00"),
            )
        ladder(c, "2026-09", now=5, future=7)
        area_scores(c, "2026-Q3", career=6, health=6)
        area_scores(c, "2026-Q4", career=5, health=7)
        xp(c, "task:1", 10, "2026-10-24T01:00:00.000000+00:00")
        c.commit()
        t = mk(env, "꾸민 분기 목표")
        env.parts.tasks.set_priorities(Cadence.quarter, "2026-Q4", [t.id])
        bodies = {m: await get_json(env, p) for m, p in (("Curve", "/curve"), ("Status", "/status"))}
        quarter = await get_json(env, "/curve?zoom=quarter")
        schema = await get_json(env, "/schema")
    schemas = schema_bundle()["models"]
    assert {"Curve", "Status"} <= set(schema["models"])
    for model, body in {**bodies, "Curve2": quarter}.items():
        jsonschema.Draft202012Validator(schemas[model.rstrip("2")]).validate(body)
    assert bodies["Curve"]["reassurance"][0]["condition_average"] == 3.5
    assert bodies["Status"]["titles"][0]["title"] == "「꾸민 고점」의 순간"
