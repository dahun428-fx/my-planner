"""`GET /health`의 내용 (SP3-4 스펙 6.3.1)과 오류 수 세기(`ErrorCounter`).

`health_view`는 읽기 전용 연결 하나만 받는다(스펙 4.3). DB에 쓰지 않는다.
"""

from __future__ import annotations

import importlib.metadata
import logging
import sqlite3
from collections import Counter, deque
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from my_planner.api.models import api_time, to_api_times
from my_planner.clock import Clock, from_iso, logical_date
from my_planner.harness.checkins import runs_today
from my_planner.logging_setup import THIRD_PARTY_MSG
from my_planner.store.repos.channels import DeliveriesRepo
from my_planner.store.repos.push import PushRepo
from my_planner.store.repos.runs import RunsRepo
from my_planner.store.repos.state import (
    BRAIN_AUTH_CHECKED_AT_KEY,
    BRAIN_AUTH_STATE_KEY,
    LIMITED_UNTIL_KEY,
    NOTIFY_PRIMARY_KEY,
    PAUSE_UNTIL_KEY,
    StateRepo,
)
from my_planner.tools.ui import UI_CATALOG_VERSION

if TYPE_CHECKING:
    from my_planner.api.server import ApiDeps

API_VERSION = "v1"
_OWN_PREFIX = "my_planner"


def app_version() -> str:
    try:
        return importlib.metadata.version("my-planner")
    except importlib.metadata.PackageNotFoundError:  # 설치하지 않고 소스에서 돌릴 때
        return "0.0.0"


class ErrorCounter(logging.Handler):
    """루트 로거에 붙여 WARNING 이상 기록을 이벤트 이름(`record.msg`)으로만 센다. 메모리에만, 24시간 창.

    `my_planner` 밖의 로거는 메시지에 본문이 들어 있을 수 있어 `third_party_log` 하나로 센다(로그 규칙과 같다).
    재시작하면 0부터다(`since`는 이 처리기를 만든 때).
    """

    def __init__(self, clock: Clock, *, window: timedelta = timedelta(hours=24)) -> None:
        super().__init__(level=logging.WARNING)
        self.clock = clock
        self.window = window
        self.started_at = clock.now()
        self._events: deque[tuple[datetime, str]] = deque()

    def emit(self, record: logging.LogRecord) -> None:
        own = record.name == _OWN_PREFIX or record.name.startswith(_OWN_PREFIX + ".")
        name = record.msg if own and isinstance(record.msg, str) else THIRD_PARTY_MSG
        now = self.clock.now()
        self._prune(now)  # 아무도 /health를 읽지 않아도 창 밖 기록은 쌓이지 않는다
        self._events.append((now, name))

    def _prune(self, now: datetime) -> None:
        cutoff = now - self.window
        while self._events and self._events[0][0] < cutoff:
            self._events.popleft()

    def snapshot(self) -> dict[str, Any]:
        now = self.clock.now()
        cutoff = now - self.window
        self._prune(now)
        by_event = Counter(name for _, name in self._events)
        return {
            "window_hours": int(self.window.total_seconds() // 3600),
            "since": api_time(max(self.started_at, cutoff)),
            "total": sum(by_event.values()),
            "by_event": dict(sorted(by_event.items())),
        }


def _future(v: str | None, now: datetime) -> str | None:
    if not v:
        return None
    t = from_iso(v)
    return api_time(t) if t > now else None


def _plan_open(conn: sqlite3.Connection, now: datetime, idle: timedelta) -> bool:
    """열린 계획 대화가 유휴 만료 전인가(디스패처처럼 닫지는 않는다: 읽기 전용)."""
    r = conn.execute(
        "SELECT last_message_at FROM conversations WHERE kind = 'plan' AND closed_at IS NULL "
        "ORDER BY last_message_at DESC, id DESC LIMIT 1"
    ).fetchone()
    return r is not None and now - from_iso(r[0]) <= idle


def safe_mode_view(deps: ApiDeps) -> dict[str, Any]:
    return {"status": "safe_mode", "version": _version(None), "now": api_time(deps.clock.now())}


def _version(schema: int | None) -> dict[str, Any]:
    return {"app": app_version(), "api": API_VERSION, "schema": schema, "ui_catalog": UI_CATALOG_VERSION}


def health_view(conn: sqlite3.Connection, deps: ApiDeps) -> dict[str, Any]:
    s = deps.settings
    now = deps.clock.now()
    state = StateRepo(conn, deps.clock)
    runs = RunsRepo(conn, deps.clock)
    push = PushRepo(conn)
    usage = state.usage(logical_date(now, s.timezone, s.day_boundary))
    auth = state.get(BRAIN_AUTH_STATE_KEY) or "unknown"
    limited_until = _future(state.get(LIMITED_UNTIL_KEY), now)
    polling = deps.polling_state()
    primary = state.get(NOTIFY_PRIMARY_KEY) or s.notify.default_primary
    degraded = polling == "down" or auth in ("login", "billing") or limited_until is not None
    last_success = push.last_success_at()
    body = {
        "status": "degraded" if degraded else "ok",
        "version": _version(conn.execute("PRAGMA user_version").fetchone()[0]),
        "now": api_time(now),
        "started_at": api_time(deps.started_at),
        "last_tick_at": state.get("last_seen_at"),
        "polling": polling,
        "brain": {
            "auth": auth,
            "checked_at": state.get(BRAIN_AUTH_CHECKED_AT_KEY),
            "limited_until": limited_until,
            "calls_today": usage.brain_calls,
            "calls_cap": s.limits.daily_brain_calls,
        },
        "proactive": {"sent_today": usage.proactive_messages, "cap": s.limits.daily_proactive_messages},
        "paused_until": _future(state.get(PAUSE_UNTIL_KEY), now),
        "plan_open": _plan_open(conn, now, timedelta(hours=s.limits.plan_idle_hours)),
        # 앱 통로(푸시) 전달은 티켓 08이다. 그때까지 실제 통로는 언제나 텔레그램(7.3 D1a)
        "notify": {"primary": primary, "effective": "telegram"},
        "runs_today": runs_today(runs=runs, deliveries=DeliveriesRepo(conn, deps.clock), now=now, settings=s),
        "errors": deps.errors.snapshot(),
        "push": {"subscriptions": push.count_active(), "last_success_at": last_success},
    }
    return to_api_times(body)
