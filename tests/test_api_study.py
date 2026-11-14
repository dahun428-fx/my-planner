"""공부 진도 `GET`·`PUT /api/v1/study/progress` (ADR 0024). 공부 앱(AI 듀오링고)이 `STUDY_TOKEN`으로 진도를 맞춘다.

`BeEnv` + 가짜 시계. 토큰, 기기 키, 진도는 모두 꾸며 낸 것이다.
"""

from __future__ import annotations

import json
import logging

import pytest
from be_env import TEST_TOKEN, BeEnv
from hypothesis import given, settings
from hypothesis import strategies as st
from test_dispatcher_messages import kst

from my_planner import study
from my_planner.api.body import BODY_PATH
from my_planner.api.server import LIMITER_KEY, PAIR_PATH
from my_planner.api.study import STUDY_PATH
from my_planner.app import _study_token
from my_planner.study import StudyProgress
from my_planner.tools.actions import ActionRequest

START = kst(2026, 11, 14, 13, 0)
STUDY = "study-token-" + "s" * 40  # 꾸며 낸 값(52자). API 토큰과 다르다
BODY = "body-token-" + "y" * 40
ORIGIN = "https://study.example"
PHONE, LAPTOP = "phone0001", "laptop0001"

A = {"v": 1, "done": ["day01", "day02"], "days": ["2026-11-13"], "best": {"day01": 80}, "spoke": {"day01": 1},
     "xp_by": {PHONE: 120}}
B = {"v": 1, "done": ["day02", "day03"], "days": ["2026-11-14", "2026-11-13"], "best": {"day01": 100, "day03": 70},
     "spoke": {}, "xp_by": {LAPTOP: 60, PHONE: 90}}
MERGED = {"v": 1, "done": ["day01", "day02", "day03"], "days": ["2026-11-13", "2026-11-14"],
          "best": {"day01": 100, "day03": 70}, "spoke": {"day01": 1}, "xp_by": {LAPTOP: 60, PHONE: 120}}
EMPTY = {"v": 1, "done": [], "days": [], "best": {}, "spoke": {}, "xp_by": {}}


@pytest.fixture
async def env(tmp_path):
    async with BeEnv.start(tmp_path, start=START, study_token=STUDY, overrides={"api": {"cors_origins": [ORIGIN]}}) as e:
        yield e


async def put(env, payload, *, token=STUDY, **kw):
    data = payload if isinstance(payload, (str, bytes)) else json.dumps(payload)
    resp = await env.put(STUDY_PATH, token=token, data=data, headers={"Content-Type": "application/json"}, **kw)
    return resp.status, await resp.json()


async def get(env, *, token=STUDY):
    resp = await env.get(STUDY_PATH, token=token)
    return resp.status, await resp.json()


# --- 합치기 (순수 함수) ---


def _p(d):
    p = study.parse(d)
    assert p is not None
    return p


def test_merge_example():
    assert study.dump(study.merge(_p(A), _p(B))) == MERGED


_lesson = st.sampled_from(["day01", "day02", "day03", "day10", "w3-lstm"])
_device = st.sampled_from([PHONE, LAPTOP, "tablet0001"])
_day = st.dates(min_value=kst(2026, 1, 1, 0, 0).date(), max_value=kst(2026, 12, 31, 0, 0).date()).map(str)
_progress = st.builds(
    lambda done, days, best, spoke, xp: _p({"v": 1, "done": sorted(done), "days": sorted(days), "best": best,
                                           "spoke": spoke, "xp_by": xp}),
    st.sets(_lesson), st.sets(_day, max_size=5), st.dictionaries(_lesson, st.integers(0, 100)),
    st.dictionaries(_lesson, st.integers(0, 50)), st.dictionaries(_device, st.integers(0, 5000)),
)


@settings(max_examples=150, deadline=None)
@given(_progress, _progress, _progress)
def test_merge_is_commutative_associative_idempotent(a, b, c):
    """어느 기기가 먼저 보내든, 같은 것을 몇 번 보내든 결과가 같다. 합친 뒤에 줄어드는 값은 없다."""
    ab = study.merge(a, b)
    assert ab == study.merge(b, a)
    assert study.merge(ab, c) == study.merge(a, study.merge(b, c))
    assert study.merge(a, a) == a and study.merge(ab, b) == ab
    assert set(a.done) <= set(ab.done) and set(a.days) <= set(ab.days)
    assert all(ab.xp_by[k] >= v for k, v in a.xp_by.items())
    assert sum(ab.xp_by.values()) >= max(sum(a.xp_by.values()), sum(b.xp_by.values()))


@pytest.mark.parametrize("bad", [
    {"v": 2}, {"extra": 1}, {"done": ["Day01"]}, {"done": ["../x"]}, {"done": "day01"},
    {"days": ["2026-02-30"]}, {"days": ["20261114"]}, {"best": {"day01": 101}}, {"best": {"day01": 80.0}},
    {"best": {"day01": True}}, {"spoke": {"day01": -1}}, {"xp_by": {"short": 1}}, {"xp_by": {PHONE: -5}},
    {"xp_by": {PHONE: study.XP_MAX + 1}}, {"xp_by": {"UPPER00001": 1}}, [], "x", None,
    {"done": [f"l{i}" for i in range(study.LESSONS_MAX + 1)]},
    {"xp_by": {f"device{i:04d}": 1 for i in range(study.DEVICES_MAX + 1)}},
])
def test_parse_rejects(bad):
    assert study.parse(bad) is None


def test_load_bad_stored_value_is_empty():
    assert study.dump(study.load(None)) == EMPTY
    assert study.dump(study.load("not json")) == EMPTY
    assert study.dump(study.load('{"v": 9}')) == EMPTY


def test_merge_over_device_limit_is_none():
    a = _p({"xp_by": {f"aaaa{i:04d}": 1 for i in range(study.DEVICES_MAX)}})
    assert study.merge(a, _p({"xp_by": {"bbbb0000": 1}})) is None


# --- HTTP ---


async def test_get_empty_then_put_merges_and_persists(env):
    assert await get(env) == (200, EMPTY)
    assert await put(env, A) == (200, {**A, "days": ["2026-11-13"]})
    assert await put(env, B) == (200, MERGED)
    assert await put(env, B) == (200, MERGED)  # 같은 본문을 다시 보내도 같다
    assert await put(env, EMPTY) == (200, MERGED)  # 빈 진도(새 기기)를 보내도 지워지지 않는다
    assert await get(env) == (200, MERGED)
    row = env.conn.execute("SELECT value FROM app_state WHERE key = 'study_progress'").fetchone()
    assert json.loads(row["value"]) == MERGED


async def test_put_leaves_no_activity_xp_or_idempotency(env):
    await put(env, A)
    assert env.activity() == []
    assert env.conn.execute("SELECT COUNT(*) FROM api_idempotency").fetchone()[0] == 0
    assert env.conn.execute("SELECT COUNT(*) FROM status_xp_ledger").fetchone()[0] == 0


@pytest.mark.parametrize("payload", ["not json", "[]", '{"v": 2}', '{"done": ["Day01"]}', '{"xp_by": {"x": 1}}', ""])
async def test_put_bad_body_400_and_nothing_saved(env, payload):
    status, body = await put(env, payload)
    assert status == 400 and body["error"]["code"] == "invalid_request"
    assert await get(env) == (200, EMPTY)


async def test_put_over_device_limit_422_and_nothing_changes(env):
    full = {"xp_by": {f"aaaa{i:04d}": 1 for i in range(study.DEVICES_MAX)}}
    assert (await put(env, full))[0] == 200
    status, body = await put(env, {"xp_by": {"bbbb0000": 1}})
    assert status == 422 and body["error"]["code"] == "rejected"
    assert (await get(env))[1]["xp_by"] == full["xp_by"]


async def test_over_64kb_413(env):
    big = json.dumps({"done": [], "pad": "x" * 70_000})
    resp = await env.put(STUDY_PATH, token=STUDY, data=big, headers={"Content-Type": "application/json"})
    assert resp.status == 413


# --- 토큰: `STUDY_TOKEN`은 이 경로만, 이 경로는 `STUDY_TOKEN`만 ---


async def test_study_path_rejects_api_token_device_token_and_no_token(env):
    for token in (TEST_TOKEN, None, "wrong-" + "z" * 40):
        assert (await get(env, token=token))[0] == 401
        assert (await put(env, A, token=token))[0] == 401
        env.client.app[LIMITER_KEY]._failures.clear()
    code = (await (await env.post("/devices/pair", json={})).json())["code"]
    paired = await env.post(PAIR_PATH, token=None, json={"code": code, "client": "app", "label": "폰"})
    device_token = (await paired.json())["token"]
    assert (await env.get("/today", token=device_token)).status == 200
    assert (await get(env, token=device_token))[0] == 401
    assert await get(env) == (200, EMPTY)


async def test_study_token_rejected_on_every_other_route(tmp_path):
    """등록된 모든 경로(틀의 `{id}`는 숫자로)에 `STUDY_TOKEN`을 보내면 401."""
    async with BeEnv.start(tmp_path, start=START, study_token=STUDY, body_token=BODY) as env:
        routes = sorted({
            (r.method, r.resource.canonical) for r in env.client.app.router.routes()
            if r.resource is not None and r.method != "HEAD"
        })
        assert ("GET", STUDY_PATH) in routes and ("PUT", STUDY_PATH) in routes and ("POST", BODY_PATH) in routes
        for method, path in routes:
            if (method, path) == ("POST", PAIR_PATH) or path == STUDY_PATH:
                continue
            url = path.replace("{id}", "1").replace("{agent}", "secretary")
            resp = await env.request(method, url, token=STUDY, json={})
            assert resp.status == 401, (method, path)
            env.client.app[LIMITER_KEY]._failures.clear()
        assert (await env.put(STUDY_PATH, token=BODY, json=A)).status == 401
        assert (await env.put(STUDY_PATH, token=STUDY, json=A)).status == 200


async def test_route_absent_without_token(tmp_path):
    async with BeEnv.start(tmp_path, start=START) as env:
        assert (await env.get(STUDY_PATH)).status == 404
        assert (await env.put(STUDY_PATH, json=A)).status == 404


async def test_study_merge_not_callable_from_actions(env):
    status, body = await env.action("study_merge", {"progress": A})
    assert status == 400 and body["error"]["code"] == "invalid_request"
    res = env.parts.dispatcher.apply_action(
        ActionRequest("study_merge", {"progress": A}, actor="user", channel="app", endpoint="actions")
    )
    assert res.http_status == 400
    assert await get(env) == (200, EMPTY)


def test_study_token_rules(tmp_path, caplog):
    from fakes import make_settings

    def build(value, body=None):
        s = make_settings(tmp_path, api_token=TEST_TOKEN, **({"study_token": value} if value is not None else {}))
        return _study_token(s, TEST_TOKEN, body)

    with caplog.at_level(logging.WARNING):
        assert build(None) is None and build("") is None
        assert caplog.records == []  # 공부 앱을 쓰지 않는 설치는 경고가 없다
        assert build("short") is None and build(TEST_TOKEN) is None and build(BODY, BODY) is None
        assert build(STUDY, BODY) == STUDY
    assert [r.reason for r in caplog.records] == ["too_short", "same_as_api", "same_as_body"]
    assert all(STUDY not in r.getMessage() and TEST_TOKEN not in r.getMessage() for r in caplog.records)


# --- CORS와 로그 ---


async def test_cors_headers_for_allowed_origin_only(env):
    pre = await env.client.options(STUDY_PATH, headers={
        "Origin": ORIGIN, "Access-Control-Request-Method": "PUT", "Access-Control-Request-Headers": "authorization",
    })
    assert pre.status == 204 and pre.headers["Access-Control-Allow-Origin"] == ORIGIN
    assert "PUT" in pre.headers["Access-Control-Allow-Methods"]
    ok = await env.put(STUDY_PATH, token=STUDY, json=A, headers={"Origin": ORIGIN})
    assert ok.status == 200 and ok.headers["Access-Control-Allow-Origin"] == ORIGIN
    other = await env.put(STUDY_PATH, token=STUDY, json=A, headers={"Origin": "https://evil.example"})
    assert "Access-Control-Allow-Origin" not in other.headers


async def test_log_has_counts_only(env, caplog):
    with caplog.at_level(logging.INFO):
        await put(env, MERGED)
    rec = [r for r in caplog.records if r.getMessage() == "study_synced"]
    assert len(rec) == 1 and (rec[0].lessons, rec[0].devices) == (3, 2)
    text = " ".join(str(r.__dict__) for r in caplog.records)
    assert STUDY not in text and PHONE not in text and "2026-11-13" not in text


def test_model_matches_dump_shape():
    assert set(StudyProgress.model_fields) == set(EMPTY)
