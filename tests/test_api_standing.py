"""`GET /standing`, `GET /standing/measures`, 대시보드 기기 403 (SP13-06, 스펙 12장). 자료는 Task 3의 가짜 사람이다."""

import json
import logging
from datetime import date
from pathlib import Path

import jsonschema
import pytest
from be_env import TEST_TOKEN, BeEnv
from test_api_devices import _device
from test_api_read import get_json
from test_dispatcher_messages import kst

from my_planner.api.models import schema_bundle
from my_planner.standing.score import AXES, round_half_up
from my_planner.standing.service import write_snapshot
from my_planner.store.db import transaction
from my_planner.store.repos.standing import StandingRepo

FIX = Path(__file__).parent / "fixtures"
START = kst(2026, 11, 1, 14, 0)
AREAS = ("career", "finance", "health", "relationships", "learning", "quality_of_life")
QOL_HINT = "삶의 질은 객관적 기준표가 없어요. 만족 점수와 생활 지표(잠, 걸음, 쉬는 저녁)로 봐요."
FORBIDDEN = {"error": {"code": "forbidden", "message": "이 화면에서는 볼 수 없어요."}}


def _sample() -> list[dict]:
    return json.loads((FIX / "standing_sample.json").read_text(encoding="utf-8"))["measures"]


def put(env, rows, *, source="import"):
    repo = StandingRepo(env.conn, env.clock)
    now = env.clock.now()
    with transaction(env.conn):
        for m in rows:
            repo.add(m["metric"], m["value"], date.fromisoformat(m["measured_on"]), source, None, "mid", now)


def seed_sample(env, drop=(), extra=()):
    put(env, [m for m in _sample() if m["metric"] not in drop] + list(extra))


def _valid(model, body):
    jsonschema.Draft202012Validator(schema_bundle()["models"][model]).validate(body)


async def test_standing_shape_with_sample(tmp_path):
    async with BeEnv.start(tmp_path, start=START) as env:
        seed_sample(env)
        body = await get_json(env, "/standing")
    _valid("Standing", body)
    exp = json.loads((FIX / "standing_sample_expected.json").read_text(encoding="utf-8"))
    assert body["profile_missing"] is False
    assert body["bench"] == {"version": "2026.1", "effective_from": "2026-11-01"}
    assert [a["axis"] for a in body["axes"]] == list(AXES)
    by_axis = {a["axis"]: a for a in body["axes"]}
    for axis in AXES:
        assert by_axis[axis]["national"]["score"] == exp["national"][axis], axis
        assert by_axis[axis]["peer"]["score"] == exp["peer"][axis], axis
    health = by_axis["health"]
    assert (health["label"], health["area"], health["innate"]) == ("건강", "health", False)
    assert by_axis["looks"]["area"] == "health"
    assert by_axis["height"] == {**by_axis["height"], "area": None, "innate": True}
    nat = health["national"]
    assert nat["measured_on"] == "2026-10-01"
    assert "shuttle_run_laps" in nat["inputs"] and nat["low"] <= nat["score"] <= nat["high"]
    assert nat["reliability"] in ("high", "mid", "low") and isinstance(nat["estimate"], bool)

    areas = body["areas"]
    assert list(areas) == list(AREAS)
    assert areas["health"]["score"] == 70  # round_half_up(0.6 × health.raw + 0.4 × looks.raw)
    assert areas["career"] == {
        "score": exp["national"]["career"], "peer_score": exp["peer"]["career"],
        "reliability": by_axis["career"]["national"]["reliability"], "drift": [], "debuff": False,
        "recovery_quest": None, "hint": None,
    }
    rel = {by_axis[a]["national"]["reliability"] for a in ("health", "looks")}
    order = ("high", "mid", "low")
    assert areas["health"]["reliability"] == max(rel, key=order.index)  # 가장 낮은 것
    assert areas["quality_of_life"] == {
        "score": None, "peer_score": None, "reliability": None, "drift": [], "debuff": False,
        "recovery_quest": None, "hint": QOL_HINT,
    }
    assert body["innate"] == [
        {"axis": "height", "label": "키", "score": exp["national"]["height"]},
        {"axis": "education", "label": "학벌", "score": exp["national"]["education"]},
        {"axis": "family", "label": "집안", "score": exp["national"]["family"]},
    ]
    assert body["markets"]["marriage"] == {"national": 65, "peer": exp["peer"]["markets"]["marriage"], "excluded": []}
    assert body["markets"]["career"]["national"] == exp["national"]["markets"]["career"]
    assert body["measures_count"] == 43


async def test_area_score_is_rounded_weighted_raw(tmp_path):
    from my_planner.standing.service import current

    async with BeEnv.start(tmp_path, start=START) as env:
        seed_sample(env)
        body = await get_json(env, "/standing")
        now = current(env.conn, env.clock, date(2026, 11, 1))
    s = now.scores["national"]
    assert body["areas"]["health"]["score"] == round_half_up(0.6 * s["health"].raw + 0.4 * s["looks"].raw) == 70


async def test_empty_standing(tmp_path):
    async with BeEnv.start(tmp_path, start=START) as env:
        body = await get_json(env, "/standing")
        measures = await get_json(env, "/standing/measures")
    _valid("Standing", body)
    assert body["profile_missing"] is True and body["measures_count"] == 0
    assert all(a["national"] is None and a["peer"] is None for a in body["axes"])
    for area, row in body["areas"].items():
        assert row["score"] is None and row["hint"], area
    assert body["areas"]["career"]["hint"] == "태어난 해를 넣으면 생겨요."
    assert body["areas"]["quality_of_life"]["hint"] == QOL_HINT
    assert [i["score"] for i in body["innate"]] == [None, None, None]
    assert body["markets"]["marriage"]["national"] is None
    assert measures == {"measures": []}


async def test_hint_names_first_missing_metric(tmp_path):
    async with BeEnv.start(tmp_path, start=START) as env:
        seed_sample(env, drop=("salary_krw",))
        body = await get_json(env, "/standing")
    assert body["areas"]["career"]["score"] is None
    assert body["areas"]["career"]["hint"] == "연봉(세전)을 넣으면 생겨요."  # 받침 있음 → 을
    assert body["areas"]["finance"]["hint"] == "연봉(세전)을 넣으면 생겨요."
    assert body["areas"]["health"]["hint"] is None


async def test_hint_particle_without_batchim(tmp_path):
    async with BeEnv.start(tmp_path, start=START) as env:
        seed_sample(env, drop=("company_tier",))
        body = await get_json(env, "/standing")
    assert body["areas"]["career"]["hint"] == "회사 등급을 넣으면 생겨요."
    from my_planner.api.standing import with_object_particle

    assert with_object_particle("왕복오래달리기") == "왕복오래달리기를"
    assert with_object_particle("ALT(간 수치)") == "ALT(간 수치)를"
    assert with_object_particle("스쿼트 1RM") == "스쿼트 1RM을"


async def test_female_profile_hint(tmp_path):
    async with BeEnv.start(tmp_path, start=START) as env:
        sample = [m for m in _sample() if m["metric"] != "profile_sex"]
        put(env, [*sample, {"metric": "profile_sex", "value": "f", "measured_on": "2026-10-01"}])
        body = await get_json(env, "/standing")
    for area in ("career", "finance", "health", "relationships", "learning"):
        assert body["areas"][area]["score"] is None
        assert body["areas"][area]["hint"] == "지금 기준표는 남성 표만 있어요.", area
    assert body["areas"]["quality_of_life"]["hint"] == QOL_HINT
    innate = {i["axis"]: i["score"] for i in body["innate"]}
    assert innate["height"] is None and innate["education"] is not None


async def test_drift_debuff_and_recovery_quest(tmp_path):
    async with BeEnv.start(tmp_path, start=START) as env:
        sep = [{**m, "measured_on": "2026-09-01"} for m in _sample()]
        put(env, sep)
        with transaction(env.conn):
            assert write_snapshot(env.conn, env.clock, "2026-Q3", as_of=date(2026, 9, 30))
        put(env, [
            {"metric": "shuttle_run_laps", "value": 5, "measured_on": "2026-10-20"},
            {"metric": "grip_rel_pct", "value": 20.0, "measured_on": "2026-10-20"},
            {"metric": "smoking", "value": "current", "measured_on": "2026-10-20"},
            {"metric": "bp_sys", "value": 150, "measured_on": "2026-10-20"},
        ])
        body = await get_json(env, "/standing")
        status = await get_json(env, "/status")
    health = body["areas"]["health"]
    assert health["debuff"] is True and health["recovery_quest"] == "20분 걷기"
    assert health["drift"] and health["drift"][0]["kind"] == "me" and health["drift"][0]["delta"] <= -5
    assert body["areas"]["career"]["drift"] == [] and body["areas"]["career"]["debuff"] is False
    stat = next(s for s in status["stats"] if s["area"] == "health")
    assert stat["standing"] == health


async def test_measures_list(tmp_path):
    async with BeEnv.start(tmp_path, start=START) as env:
        put(env, [
            {"metric": "height_cm", "value": 176, "measured_on": "2026-10-01"},
            {"metric": "cert", "value": "toeic:900", "measured_on": "2026-09-01"},
        ])
        body = await get_json(env, "/standing/measures")
    _valid("StandingMeasures", body)
    assert [m["metric"] for m in body["measures"]] == ["cert", "height_cm"]  # `active()` 순서
    h = body["measures"][1]
    assert h == {
        "id": h["id"], "metric": "height_cm", "label": "키", "value_num": 176.0, "value_text": None, "unit": "cm",
        "measured_on": "2026-10-01", "source_kind": "import", "reliability": "mid", "created_at": h["created_at"],
    }
    assert h["created_at"].endswith("Z")
    assert body["measures"][0]["value_text"] == "toeic:900" and body["measures"][0]["unit"] is None


async def test_dashboard_device_forbidden(tmp_path):
    async with BeEnv.start(tmp_path, start=START) as env:
        seed_sample(env)
        dash, _ = await _device(env, client="dashboard", label="Windows · 대시보드")
        app, _ = await _device(env, client="app", label="iPhone · 앱")
        for path in ("/standing", "/standing/measures"):
            resp = await env.get(path, token=dash)
            assert resp.status == 403
            assert await resp.json() == FORBIDDEN
            _valid("Error", await resp.json())
            assert (await env.get(path, token=app)).status == 200
            assert (await env.get(path, token=TEST_TOKEN)).status == 200
            assert (await env.get(path, token=None)).status == 401


async def test_logs_have_no_values(tmp_path, caplog):
    caplog.set_level(logging.DEBUG)
    async with BeEnv.start(tmp_path, start=START) as env:
        seed_sample(env)
        caplog.clear()
        for path in ("/standing", "/standing/measures", "/status"):
            await get_json(env, path)
    text = "\n".join(
        f"{r.getMessage()} {json.dumps({k: str(v) for k, v in r.__dict__.items()}, ensure_ascii=False)}"
        for r in caplog.records
    )
    assert "api_request" in text
    for needle in ("62000000", "180000000", "1500000", "4500000", "250000000", "1992", "toeic:900", "monthly_binge"):
        assert needle not in text, needle


@pytest.mark.parametrize("path", ["/standing", "/standing/measures"])
async def test_standing_routes_are_read_only(tmp_path, path):
    """읽기 전용 연결로만 읽는다: 응답 뒤 표가 그대로다."""
    async with BeEnv.start(tmp_path, start=START) as env:
        seed_sample(env)
        before = env.conn.execute("SELECT COUNT(*) FROM standing_snapshots").fetchone()[0]
        await get_json(env, path)
        assert env.conn.execute("SELECT COUNT(*) FROM standing_snapshots").fetchone()[0] == before == 0
