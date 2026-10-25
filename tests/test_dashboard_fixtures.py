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
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from aiohttp.test_utils import TestClient, TestServer
from be_env import TEST_TOKEN, BeEnv
from dashboard_seed import seed_dashboard_db
from fakes import FakePushSender, make_settings

from my_planner.api.health import ErrorCounter
from my_planner.api.models import MODELS, schema_bundle
from my_planner.api.server import ApiDeps, build_app
from my_planner.clock import FakeClock, to_iso
from my_planner.store.db import LATEST_VERSION


def kst(y: int, mo: int, d: int, h: int, mi: int = 0) -> datetime:
    """KST 벽시계 시각을 UTC로(이 파일만 쓴다)."""
    return datetime(y, mo, d, h, mi, tzinfo=UTC) - timedelta(hours=9)


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
    # 티켓 17: (b) 할 일 + 컨디션, (d) 상태창. `-empty`는 설치 직후 빈 DB다.
    "today": ("/today", _seeded, {}),
    "today-empty": ("/today", _quiet, {}),
    "week": ("/week", _seeded, {}),
    "week-empty": ("/week", _quiet, {}),
    "conditions": ("/conditions", _seeded, {}),
    "conditions-empty": ("/conditions", _quiet, {}),
    "status": ("/status", _seeded, {}),
    "status-empty": ("/status", _quiet, {}),
    # 티켓 18: (c) 인생곡선. 화면이 보내는 질의 그대로다(년 확대는 `from`을 준다: `CurveScreen`의 YEAR_FROM).
    "curve-day": ("/curve?zoom=day", _seeded, {}),
    "curve-week": ("/curve?zoom=week", _seeded, {}),
    "curve-month": ("/curve?zoom=month", _seeded, {}),
    "curve-month-sensitive": ("/curve?zoom=month&include_sensitive=true", _seeded, {}),
    "curve-quarter": ("/curve?zoom=quarter", _seeded, {}),
    "curve-year": ("/curve?zoom=year&from=1900-01-01", _seeded, {}),
    "curve-empty": ("/curve?zoom=month", _quiet, {}),
    # SP8-08: 히스토리 탭(SP8 8.2). 기본은 민감 사건을 가린다
    "curve-history": ("/curve/history", _seeded, {}),
    "curve-history-sensitive": ("/curve/history?include_sensitive=true", _seeded, {}),
    "curve-history-empty": ("/curve/history", _quiet, {}),
}
# 경로마다 응답 모델(고정 자료가 계약 모양인지 본다)
PATH_MODELS = {"/health": "Health", "/today": "Today", "/week": "Week", "/conditions": "Conditions",
               "/status": "Status", "/curve": "Curve", "/curve/history": "CurveHistory"}


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
    path = CASES[name][0].split("?")[0]
    MODELS[PATH_MODELS[path]].model_validate(body)
    if path == "/health":
        assert body["version"]["schema"] == LATEST_VERSION
    _compare(name, body, update_dashboard_fixtures)


async def test_safe_mode_fixture(tmp_path, update_dashboard_fixtures):
    body = await _record_safe_mode(tmp_path)
    MODELS["SafeModeHealth"].model_validate(body)
    _compare("health-safe-mode", body, update_dashboard_fixtures)


def test_seed_uses_logical_date_before_four(tmp_path, conn):
    """02:00 KST는 아직 전날이다: 오늘 회차와 사용량은 전날 논리적 날짜에 들어간다."""
    seed_dashboard_db(conn, FakeClock(kst(2026, 10, 25, 2, 0)))
    assert conn.execute("SELECT date FROM usage_state").fetchone()[0] == "2026-10-24"
    assert conn.execute("SELECT scheduled_for FROM runs WHERE loop = 'morning_brief'").fetchone()[0].startswith(
        "2026-10-24T01:00")


def test_seed_is_invented_and_shaped(tmp_path, conn):
    """지난 30일 가운데 21일 컨디션, 오늘 회차 둘, 원장은 양수만."""
    seed_dashboard_db(conn, FakeClock(START))
    since = (date(2026, 10, 24) - timedelta(days=29)).isoformat()
    assert conn.execute("SELECT count(*) FROM conditions WHERE date >= ?", (since,)).fetchone()[0] == 21
    assert conn.execute("SELECT count(*) FROM runs").fetchone()[0] == 2
    assert conn.execute("SELECT min(amount) FROM status_xp_ledger").fetchone()[0] > 0
    titles = [r[0] for r in conn.execute("SELECT title FROM curve_milestones")]
    assert titles and all(t.startswith("꾸민") for t in titles)


async def test_seeded_status_is_level_six_with_one_debuff(tmp_path):
    """대시보드 상태창 테스트가 기대하는 값(Lv. 6, 130 / 400 XP, HP 4/5, 건강 4 ↓ Q3 6)이 원장과 점수에서 나온다."""
    body = await _record(tmp_path, "status")
    assert (body["level"], body["xp_total"], body["xp_into_level"], body["xp_for_next"]) == (6, 1380, 130, 400)
    assert body["hp"]["score"] == 4
    debuffs = [(s["area"], s["score"], s["prev_period"], s["prev_score"]) for s in body["stats"] if s["debuff"]]
    assert debuffs == [("health", 4, "2026-Q3", 6)]
    assert [q["first_steps"] for q in body["main_quests"]] == [{"open": 2, "done": 3}]
    assert len(body["daily_quests"]) == 1


async def test_seeded_week_has_empty_days(tmp_path):
    """`/week`은 할 일이 없는 날도 7칸 모두 준다(대시보드가 빈 날을 같은 칸으로 그린다)."""
    body = await _record(tmp_path, "week")
    assert len(body["days"]) == 7
    assert any(d["todos"] == [] for d in body["days"])
    assert any(d["todos"] for d in body["days"])


def test_schema_json_matches_bundle():
    assert SCHEMA.exists(), "web/dashboard/src/api/schema.json 없음: npm run gen:types"
    assert json.loads(SCHEMA.read_text(encoding="utf-8")) == schema_bundle(), (
        "schema.json이 BE와 다르다: cd web/dashboard && npm run gen:types"
    )


async def test_seeded_curve_covers_every_reassurance_copy(tmp_path):
    """곡선 화면 테스트가 기대하는 것: 안심 보기의 네 갈래(8.3), 빈 달, 5년 뒤만 있는 달, 민감 사건은 켤 때만,
    가장 이른 챕터보다 앞선 사건은 년 확대(`from=1900-01-01`)에만."""
    month = await _record(tmp_path / "m", "curve-month")
    gaps = {r["period"]: r["gap"] for r in month["reassurance"]}
    assert gaps["2026-07"] <= -1.0 and gaps["2026-08"] >= 1.0
    assert -1.0 < gaps["2026-10"] < 1.0 and gaps["2026-09"] is None
    periods = [x["period"] for x in month["ladder"]]
    assert "2026-04" not in periods and {"period": "2026-03", "now": None, "future": 7, "note": None} in month["ladder"]
    assert not any(m["sensitive"] for m in month["milestones"])
    sensitive = await _record(tmp_path / "s", "curve-month-sensitive")
    assert [m["title"] for m in sensitive["milestones"] if m["sensitive"]] == ["꾸민 조용한 겨울"]
    year = await _record(tmp_path / "y", "curve-year")
    assert "꾸민 첫 자전거" in [m["title"] for m in year["milestones"]]
    assert min(c["start"] for c in year["chapters"]) > "2019"
