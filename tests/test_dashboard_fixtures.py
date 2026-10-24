"""대시보드 고정 자료가 BE의 실제 응답과 같다 (SP3-4 티켓 16, 스펙 13장·16장).

`dashboard_seed.seed_dashboard_db`로 채운 DB에 `BeEnv`(가짜 두뇌 + 가짜 시계)로 `GET`을 보내 그 본문이
`web/dashboard/src/test/fixtures/<이름>.json`과 같은지 본다. `web/dashboard/src/api/schema.json`은
`schema_bundle()`과 같아야 한다(`cd web/dashboard && npm run gen:types`가 다시 쓴다).
`python -m pytest tests/test_dashboard_fixtures.py --update-dashboard-fixtures`가 고정 자료를 다시 쓴다.
티켓 17·18은 `CASES`에 행만 더한다. 내용은 모두 꾸며 낸 것이다.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from aiohttp.test_utils import TestClient, TestServer
from be_env import TEST_TOKEN, BeEnv
from dashboard_seed import seed_dashboard_db
from fakes import FakePushSender, make_settings
from test_dispatcher_messages import kst

from my_planner.api.health import ErrorCounter
from my_planner.api.models import MODELS, schema_bundle
from my_planner.api.server import ApiDeps, build_app
from my_planner.clock import FakeClock, to_iso
from my_planner.store.db import LATEST_VERSION

DASHBOARD = Path(__file__).parent.parent / "web" / "dashboard"
FIXTURES = DASHBOARD / "src" / "test" / "fixtures"
SCHEMA = DASHBOARD / "src" / "api" / "schema.json"
START = kst(2026, 10, 24, 17, 0) + timedelta(seconds=5)  # 2026-10-24T08:00:05Z, 토요일 저녁 전


def _warn(env: BeEnv, *events: str) -> None:
    """`ErrorCounter`에 경고 이벤트를 센다(로그 파일 없이)."""
    for name in events:
        env.deps.errors.emit(logging.makeLogRecord({"name": "my_planner.test", "msg": name, "levelno": 30}))


async def _seeded(env: BeEnv) -> None:
    seed_dashboard_db(env.conn, env.clock)
    _warn(env, "send_error", "tick_error")


async def _degraded(env: BeEnv) -> None:
    """로그인 문제와 사용 한도, 건너뛴 회차와 전송 안 된 회차."""
    seed_dashboard_db(env.conn, env.clock)
    now = env.clock.now()
    c = env.conn
    c.execute("UPDATE app_state SET value = 'login' WHERE key = 'brain_auth_state'")
    c.execute("INSERT OR REPLACE INTO app_state (key, value) VALUES ('limited_until', ?)",
              (to_iso(now + timedelta(hours=1, minutes=30)),))
    c.execute("UPDATE runs SET status = 'skipped', skip_reason = 'auth' WHERE loop = 'evening_checkin'")
    c.execute(
        "INSERT INTO runs (loop, cadence, scheduled_for, status, skip_reason, created_at) "
        "VALUES ('review', 'week', ?, 'skipped', 'late', ?)", (to_iso(kst(2026, 10, 24, 6, 0)), to_iso(now)),
    )
    c.execute(
        "INSERT INTO runs (loop, cadence, scheduled_for, status, error, created_at) "
        "VALUES ('return', 'day', ?, 'failed', 'send_error', ?)", (to_iso(kst(2026, 10, 24, 8, 30)), to_iso(now)),
    )
    c.commit()
    _warn(env, "send_error", "send_error", "brain_auth_error")


async def _quiet(env: BeEnv) -> None:
    """설치 직후: 오늘 회차 없음, 경고 없음."""


CASES: dict[str, tuple[str, Callable[[BeEnv], Awaitable[None]], dict[str, Any]]] = {
    # 이름: (경로, 준비, BeEnv.start 인자)
    "health": ("/health", _seeded, {"push": True}),
    "health-degraded": ("/health", _degraded, {"push": True}),
    "health-quiet": ("/health", _quiet, {}),
}


async def _record(tmp_path: Path, name: str) -> Any:
    path, prepare, opts = CASES[name]
    push = FakePushSender() if opts.get("push") else None
    async with BeEnv.start(tmp_path, start=START, push=push) as env:
        await prepare(env)
        resp = await env.get(path)
        assert resp.status == 200, await resp.text()
        return await resp.json()


async def _record_safe_mode(tmp_path: Path) -> Any:
    clock = FakeClock(START)
    deps = ApiDeps(
        settings=make_settings(tmp_path), clock=clock, token=TEST_TOKEN, read_conn=None, dispatcher=None,
        errors=ErrorCounter(clock), polling_state=lambda: "stopped", started_at=START, safe_mode=True,
    )
    client = TestClient(TestServer(build_app(deps)))
    await client.start_server()
    try:
        resp = await client.get("/api/v1/health", headers={"Authorization": f"Bearer {TEST_TOKEN}"})
        assert resp.status == 200
        return await resp.json()
    finally:
        await client.close()


def _compare(name: str, body: Any, update: bool) -> None:
    target = FIXTURES / f"{name}.json"
    text = json.dumps(body, ensure_ascii=False, indent=2) + "\n"
    if update:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    assert target.exists(), f"{target} 없음: --update-dashboard-fixtures로 만든다"
    assert json.loads(target.read_text(encoding="utf-8")) == body, f"{name}.json이 BE 응답과 다르다"


@pytest.mark.parametrize("name", list(CASES))
async def test_fixture_matches_be_response(tmp_path, name, update_dashboard_fixtures):
    body = await _record(tmp_path, name)
    model = MODELS["Health"] if CASES[name][0] == "/health" else None
    if model is not None:
        model.model_validate(body)
        assert body["version"]["schema"] == LATEST_VERSION
    _compare(name, body, update_dashboard_fixtures)


async def test_safe_mode_fixture(tmp_path, update_dashboard_fixtures):
    body = await _record_safe_mode(tmp_path)
    MODELS["SafeModeHealth"].model_validate(body)
    _compare("health-safe-mode", body, update_dashboard_fixtures)


def test_seed_is_invented_and_shaped(tmp_path, conn):
    """30일 가운데 21일 컨디션, 오늘 회차 둘, 원장은 양수만."""
    seed_dashboard_db(conn, FakeClock(START))
    assert conn.execute("SELECT count(*) FROM conditions").fetchone()[0] == 21
    assert conn.execute("SELECT count(*) FROM runs").fetchone()[0] == 2
    assert conn.execute("SELECT min(amount) FROM status_xp_ledger").fetchone()[0] > 0
    titles = [r[0] for r in conn.execute("SELECT title FROM curve_milestones")]
    assert titles and all(t.startswith("꾸민") for t in titles)


def test_schema_json_matches_bundle():
    assert SCHEMA.exists(), "web/dashboard/src/api/schema.json 없음: npm run gen:types"
    assert json.loads(SCHEMA.read_text(encoding="utf-8")) == schema_bundle(), (
        "schema.json이 BE와 다르다: cd web/dashboard && npm run gen:types"
    )
