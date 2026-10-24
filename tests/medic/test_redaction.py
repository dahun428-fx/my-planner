from __future__ import annotations

from pathlib import Path, PureWindowsPath

import pytest

from my_planner_medic.redact import (
    OUTSIDE,
    allowed_health,
    allowed_log_row,
    issue_body,
    relpath,
)
from my_planner_medic.store import Incident

ROOT = Path("/home/dahun/my-planner")
WIN_ROOT = PureWindowsPath(r"C:\Users\dahun\my-planner")


@pytest.mark.parametrize(
    ("frame", "expected"),
    [
        ("/home/dahun/my-planner/src/my_planner/x.py:12 fn", "src/my_planner/x.py:12 fn"),
        (
            "/home/dahun/my-planner/.venv/lib/python3.12/site-packages/aiohttp/x.py:3 fn",
            "site-packages/aiohttp/x.py:3 fn",
        ),
        (r"C:\Users\dahun\AppData\x.py:3 fn", f"{OUTSIDE}:3 fn"),
    ],
)
def test_relpath_rules(frame: str, expected: str) -> None:
    assert relpath(frame, ROOT) == expected


def test_relpath_windows_root_ignores_case() -> None:
    frame = r"c:\users\Dahun\My-Planner\src\my_planner\tools\todos.py:40 list_todos"
    assert relpath(frame, WIN_ROOT) == "src/my_planner/tools/todos.py:40 list_todos"
    venv = r"C:\Users\dahun\my-planner\.venv\Lib\Site-Packages\aiohttp\web.py:9 handle"
    assert relpath(venv, WIN_ROOT) == "site-packages/aiohttp/web.py:9 handle"
    assert relpath(r"C:\Python312\Lib\asyncio\events.py:84 _run", WIN_ROOT) == f"{OUTSIDE}:84 _run"


def test_relpath_unparseable_frame_is_outside() -> None:
    assert relpath("garbage", ROOT) == OUTSIDE


def test_allowed_log_row_keeps_only_allowlisted_keys() -> None:
    rec = {
        "ts": "2026-10-26T08:00:00.000+00:00", "level": "ERROR", "logger": "my_planner.tools",
        "msg": "tool_failed", "exc_type": "KeyError", "title": "치과 예약",
        "exc_where": ["/home/dahun/my-planner/src/my_planner/x.py:12 fn", "/opt/py/lib/os.py:1 g"],
    }
    assert allowed_log_row(rec, ROOT) == {
        "ts": "2026-10-26T08:00:00.000+00:00", "level": "ERROR", "logger": "my_planner.tools",
        "msg": "tool_failed", "exc_type": "KeyError",
        "exc_where": ["src/my_planner/x.py:12 fn", f"{OUTSIDE}:1 g"],
    }


def test_allowed_health_whitelists_fields() -> None:
    h = {
        "status": "ok", "polling": "running", "plan_open": True,
        "version": {"app": "1.2.0", "api": "v1", "schema": 12, "ui_catalog": 3},
        "brain": {"auth": "ok", "calls_today": 7, "limited_until": None},
        "runs_today": [{"id": 3, "loop": "morning_brief", "status": "done",
                        "scheduled_for": "2026-10-26T00:00:00Z", "skip_reason": "개인 사유"}],
        "errors": {"total": 3, "by_event": {"tool_failed": 3}},
        "inbound_pending_oldest_at": None,
    }
    assert allowed_health(h) == {
        "status": "ok", "polling": "running",
        "version": {"app": "1.2.0", "api": "v1", "schema": 12, "ui_catalog": 3},
        "brain": {"auth": "ok"},
        "runs_today": [{"loop": "morning_brief", "status": "done", "scheduled_for": "2026-10-26T00:00:00Z"}],
        "errors": {"by_event": {"tool_failed": 3}},
    }


def _incident(detail: dict) -> Incident:
    return Incident(
        fingerprint="be:KeyError src/my_planner/tools/todos.py:list_todos", part="be", state="open",
        issue_number=None, first_seen="2026-10-26T08:00:00+00:00", last_seen="2026-10-26T08:04:00+00:00",
        count=2, synced_count=None, last_synced_at=None, failures=0, resolved_at=None, detail=detail,
    )


PERSONAL = ["치과 예약", "회의 메모", "비밀 제목", "인자값", "dahun", "AppData", "개인 사유", "calls_today", "memo"]


def test_issue_body_contains_no_personal_strings() -> None:
    win_frame = r"C:\Users\dahun\AppData\Local\x.py:3 fn"
    rec = {
        "ts": "2026-10-26T08:00:00.000+00:00", "level": "ERROR", "logger": "my_planner.tools.todos",
        "msg": "tool_failed", "exc_type": "KeyError", "text": "치과 예약", "title": "비밀 제목",
        "memo": "회의 메모", "args": {"q": "인자값"},
        "exc_where": [win_frame, "/home/dahun/my-planner/src/my_planner/tools/todos.py:40 list_todos"],
    }
    health = {
        "status": "ok", "polling": "running", "brain": {"auth": "ok", "calls_today": 7},
        "runs_today": [{"loop": "evening_checkin", "status": "skipped",
                        "scheduled_for": "2026-10-26T08:30:00Z", "skip_reason": "개인 사유"}],
        "errors": {"by_event": {"tool_failed": 1}}, "version": {"app": "1.2.0"},
    }
    detail = {"exc_type": "KeyError", "exc_where": [win_frame], "memo": "회의 메모", "text": "치과 예약"}
    for rows in ([rec], [allowed_log_row(rec, ROOT)]):
        body = issue_body(_incident(detail), rows, health, "a792f21")
        for s in PERSONAL:
            assert s not in body, s
        assert "be:KeyError src/my_planner/tools/todos.py:list_todos" in body
        assert "KeyError" in body
        assert "a792f21" in body
        assert "evening_checkin" in body


def test_issue_body_redacted_row_keeps_repo_frame() -> None:
    rec = {"ts": "t", "level": "ERROR", "logger": "my_planner.x", "msg": "boom", "exc_type": "KeyError",
           "exc_where": ["/home/dahun/my-planner/src/my_planner/x.py:12 fn"]}
    body = issue_body(_incident({}), [allowed_log_row(rec, ROOT)], None, "abc")
    assert "src/my_planner/x.py:12 fn" in body
    assert "/home/" not in body
