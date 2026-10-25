"""API의 읽기 전용 원칙과 안전 모드 (SP3-4 스펙 4.3, 6.1, 15)."""

import sqlite3

import pytest
from aiohttp.test_utils import TestClient, TestServer
from be_env import TEST_TOKEN, BeEnv
from fakes import make_settings
from test_dispatcher_messages import kst

from my_planner.api import health as health_mod
from my_planner.api.health import ErrorCounter
from my_planner.api.models import SafeModeHealth
from my_planner.api.server import READ_ROUTES, WRITE_ROUTES, ApiDeps, build_app
from my_planner.clock import FakeClock
from my_planner.store.db import open_ro

START = kst(2026, 10, 24, 13, 0)
AUTH = {"Authorization": f"Bearer {TEST_TOKEN}"}


async def test_safe_mode_health_only(tmp_path):
    clock = FakeClock(START)
    deps = ApiDeps(
        settings=make_settings(tmp_path), clock=clock, token=TEST_TOKEN, read_conn=None, dispatcher=None,
        errors=ErrorCounter(clock), polling_state=lambda: "stopped", started_at=START, safe_mode=True,
    )
    client = TestClient(TestServer(build_app(deps)))
    await client.start_server()
    try:
        resp = await client.get("/api/v1/health", headers=AUTH)
        assert resp.status == 200
        body = await resp.json()
        SafeModeHealth.model_validate(body)
        assert set(body) == {"status", "version", "now"}
        assert body["status"] == "safe_mode" and body["now"] == "2026-10-24T04:00:00Z"
        for path in ("/api/v1/today", "/api/v1/status", "/api/v1/nope"):
            other = await client.get(path, headers=AUTH)
            assert other.status == 503
            assert (await other.json())["error"]["code"] == "safe_mode"
        assert (await client.get("/api/v1/health")).status == 401  # 안전 모드에서도 토큰은 본다
    finally:
        await client.close()


async def test_get_handlers_receive_mode_ro_connection(tmp_path, monkeypatch):
    seen = []
    real = health_mod.health_view

    def spy(conn, deps):
        seen.append(conn)
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            conn.execute("INSERT INTO app_state (key, value) VALUES ('x', 'y')")
        return real(conn, deps)

    monkeypatch.setattr("my_planner.api.server.health_view", spy)
    async with BeEnv.start(tmp_path, start=START) as env:
        assert (await env.get("/health")).status == 200
        assert (await env.get("/health")).status == 200
        assert env.parts.state.get("x") is None
    assert len(seen) == 2 and seen[0] is not seen[1]  # 요청마다 새 연결
    assert seen[0] is not env.conn
    with pytest.raises(sqlite3.ProgrammingError):  # 요청이 끝나면 닫았다
        seen[0].execute("SELECT 1")


def test_open_ro_uses_file_uri_and_sees_committed_writes(tmp_path, conn):
    db = tmp_path / "state" / "planner.db"
    ro = open_ro(db)
    try:
        conn.execute("INSERT INTO app_state (key, value) VALUES ('k', 'v')")
        conn.commit()
        assert ro.execute("SELECT value FROM app_state WHERE key = 'k'").fetchone()["value"] == "v"
        with pytest.raises(sqlite3.OperationalError):
            ro.execute("DELETE FROM app_state")
    finally:
        ro.close()


async def test_moments_reads_only(tmp_path, monkeypatch):
    """SP8 6.5: `GET /moments`와 `GET /status`(순간 포함)는 읽기 전용 연결만 받는다. `/moments`에 쓰기 경로는 없다
    (숨기기·지우기는 `POST /actions`뿐)."""
    from my_planner.api import read as read_mod

    seen = []
    real = read_mod.MomentsRepo

    def spy(conn, clock):
        seen.append(conn)
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            conn.execute("DELETE FROM status_moments")
        return real(conn, clock)

    monkeypatch.setattr(read_mod, "MomentsRepo", spy)
    assert "/moments" in {p for p, _ in READ_ROUTES}
    assert not any(p.startswith("/moments") for p, _ in WRITE_ROUTES)
    async with BeEnv.start(tmp_path, start=START) as env:
        assert (await env.get("/moments")).status == 200
        assert (await env.get("/status")).status == 200
        assert (await env.post("/moments", json={})).status == 405
    assert len(seen) == 2 and all(c is not env.conn for c in seen)
