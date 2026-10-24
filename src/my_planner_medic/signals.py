"""신호 모델과 감지 규칙 (스펙 3.1). 입출력 없는 함수만 둔다."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import PurePath
from typing import Any, Literal

from .config import MedicConfig
from .redact import relpath, safe_token
from .schedule import next_slot

Part = Literal["be", "app", "dashboard", "vercel", "ci"]
Kind = Literal["exception", "warn_burst", "client_error", "health", "late_run", "no_reply", "record"]


@dataclass(frozen=True)
class Signal:
    fingerprint: str
    part: Part
    kind: Kind
    at: datetime


# --- 로그 신호 (3.1 표 1~3행) ------------------------------------------------

THIRD_PARTY_MSG = "third_party_log"  # BE logging_setup.THIRD_PARTY_MSG
CLIENT_ERROR_MSG = "client_error"  # BE api/recovery.py
BIND_ERROR_MSG = "api_bind_error"  # BE api/server.py
_NOT_BURST = frozenset({THIRD_PARTY_MSG, CLIENT_ERROR_MSG})
_OWN = "my_planner"
_CLIENT_APPS = ("app", "dashboard")
WARN_WINDOW = timedelta(hours=1)
WARN_BURST = 20


def _is_own_logger(name: Any) -> bool:
    return isinstance(name, str) and (name == _OWN or name.startswith(_OWN + "."))


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        t = datetime.fromisoformat(value)
    except ValueError:
        return None
    return t if t.tzinfo is not None else None


def _split_frame(rel: str) -> tuple[str, str]:
    """가린 프레임 `path:12 fn` → (`path`, `fn`)."""
    loc, _, func = rel.rpartition(" ")
    return loc.rpartition(":")[0] or loc, func


def exception_fingerprint(exc_type: str, exc_where: Any, root: PurePath | str) -> str:
    """`be:<Exc> <relpath>:<func>`. `my_planner` 안 가장 깊은 프레임, 없으면 마지막 프레임."""
    frames = [relpath(f, root) for f in exc_where if isinstance(f, str)] if isinstance(exc_where, list) else []
    exc = safe_token(exc_type)
    if not frames:
        return f"be:{exc}"
    split = [_split_frame(f) for f in frames]
    own = [s for s in split if _OWN in s[0].split("/")[:-1]]
    path, func = (own or split)[-1]  # extract_tb 순서: 마지막이 가장 깊다
    return f"be:{exc} {path}:{func}"


def has_bind_error(records: list[dict[str, Any]]) -> bool:
    return any(r.get("msg") == BIND_ERROR_MSG and _is_own_logger(r.get("logger")) for r in records)


def log_signals(
    records: list[dict[str, Any]],
    root: PurePath | str,
    *,
    now: datetime,
    warn_window: dict[str, list[datetime]],
) -> list[Signal]:
    """로그 레코드 → 신호. `warn_window`(이벤트 → 최근 1시간 WARNING 시각)는 제자리에서 고친다."""
    out: list[Signal] = []
    burst_events: list[str] = []
    for rec in records:
        at = _parse_time(rec.get("ts")) or now
        level = rec.get("level")
        msg = rec.get("msg")
        own = _is_own_logger(rec.get("logger"))
        if own and msg == CLIENT_ERROR_MSG:
            app = rec.get("app")
            if app in _CLIENT_APPS:
                fp = f"{app}:{safe_token(rec.get('error_name'))} {safe_token(rec.get('route'))}"
                out.append(Signal(fp, app, "client_error", at))
        elif level in ("ERROR", "CRITICAL") and rec.get("exc_type"):
            fp = exception_fingerprint(rec["exc_type"], rec.get("exc_where"), root)
            out.append(Signal(fp, "be", "exception", at))
        elif level == "WARNING" and own and isinstance(msg, str) and msg not in _NOT_BURST:
            warn_window.setdefault(msg, []).append(at)
            if msg not in burst_events:
                burst_events.append(msg)
    cutoff = now - WARN_WINDOW
    for event in list(warn_window):
        kept = [t for t in warn_window[event] if t > cutoff]
        if kept:
            warn_window[event] = kept
        else:
            del warn_window[event]
    for event in burst_events:
        if len(warn_window.get(event, [])) >= WARN_BURST:
            out.append(Signal(f"be-warn:{safe_token(event)}", "be", "warn_burst", now))
    return out


# --- 헬스 (3.1 표 4~6행) -----------------------------------------------------


@dataclass(frozen=True)
class HealthProbe:
    status: int | None  # None = 연결 안 됨·10초 초과
    body: dict[str, Any] | None


def outside_reasons(health: dict[str, Any], now: datetime) -> list[str]:
    """코드 밖 사유(3.1): 이 중 하나라도 있으면 헬스 실패·회차 지연·무응답을 세지 않는다."""
    reasons: list[str] = []
    brain = health.get("brain") if isinstance(health.get("brain"), dict) else {}
    if health.get("polling") == "down":
        reasons.append("polling_down")
    if brain.get("auth") in ("login", "billing"):
        reasons.append("auth")
    limited = _parse_time(brain.get("limited_until"))
    if limited is not None and limited > now:
        reasons.append("limited")
    paused = _parse_time(health.get("paused_until"))
    if paused is not None and paused > now:
        reasons.append("paused")
    return reasons


def normal_delay_reasons(health: dict[str, Any]) -> list[str]:
    """SP1 따라잡기가 일부러 회차를 `pending`으로 두는 경우(`loop/catchup.py`). 회차 지연만 세지 않는다."""
    reasons: list[str] = []
    if health.get("plan_open") is True:
        reasons.append("plan_open")
    proactive = health.get("proactive")
    if isinstance(proactive, dict):
        sent, cap = proactive.get("sent_today"), proactive.get("cap")
        if isinstance(sent, int) and isinstance(cap, int) and sent >= cap:
            reasons.append("proactive_cap")
    return reasons


def _failure(probe: HealthProbe, bind_error: bool) -> str | None:
    if probe.status is None:
        return "bind" if bind_error else "unreachable"
    if probe.status == 401:
        return "auth"
    if probe.status != 200 or not isinstance(probe.body, dict):
        return "unreachable"  # 5xx 등: 헬스 응답을 못 받은 것과 같다
    if probe.body.get("status") == "safe_mode":
        return "safe_mode"
    return None


def _late_runs(health: dict[str, Any], now: datetime, cfg: MedicConfig) -> list[str]:
    grace = timedelta(minutes=cfg.late_run_grace_minutes)
    rows = [r for r in health.get("runs_today") or [] if isinstance(r, dict)]
    late: list[str] = []
    for r in rows:
        at = _parse_time(r.get("scheduled_for"))
        if r.get("status") == "pending" and at is not None and now > at + grace:
            loop = safe_token(r.get("loop"))
            if loop not in late:
                late.append(loop)
    # 행 없는 지연: runs 행은 tick만 만든다. 마지막 tick 뒤 첫 회차 + 15분이 지났는데 그 행이 없으면 tick이 멈췄다
    last_tick = _parse_time(health.get("last_tick_at"))
    if last_tick is not None:
        slot_at, slot_loop = next_slot(cfg, last_tick)
        has_row = any(
            r.get("loop") == slot_loop and _parse_time(r.get("scheduled_for")) == slot_at for r in rows
        )
        if now > slot_at + grace and not has_row:
            late.append("tick_stalled")
    return late


def _no_reply(health: dict[str, Any], now: datetime, cfg: MedicConfig) -> bool:
    oldest = _parse_time(health.get("inbound_pending_oldest_at"))
    return oldest is not None and now - oldest > timedelta(minutes=cfg.no_reply_minutes)


def health_signals(
    probe: HealthProbe,
    now: datetime,
    *,
    streak: int,
    suppress: bool,
    cfg: MedicConfig,
    bind_error: bool = False,
) -> tuple[list[Signal], int]:
    """헬스 한 번 → (신호, 새 연속 실패 수).

    - `suppress`(절전 직후 유예·배포 중)면 아무것도 세지 않고 연속 수를 0으로 되돌린다.
    - 실패(연결 안 됨, 401, safe_mode, 그 밖의 비 200)가 `health_fail_streak`(3)번째부터 `health:*`.
      `safe_mode`는 `kind="record"`. `bind_error`(로그에 `api_bind_error`)면 연결 실패를 `health:bind`로.
    - 성공 응답에 코드 밖 사유가 있으면 회차 지연·무응답도 없다. `plan_open`·`proactive_cap`은 회차 지연만 막는다.
    """
    if suppress:
        return [], 0
    failure = _failure(probe, bind_error)
    if failure is not None:
        streak += 1
        if streak < cfg.health_fail_streak:
            return [], streak
        kind: Kind = "record" if failure == "safe_mode" else "health"
        return [Signal(f"health:{failure}", "be", kind, now)], streak
    assert probe.body is not None
    health = probe.body
    if outside_reasons(health, now):
        return [], 0
    out: list[Signal] = []
    if not normal_delay_reasons(health):
        out += [Signal(f"late_run:{loop}", "be", "late_run", now) for loop in _late_runs(health, now, cfg)]
    if _no_reply(health, now, cfg):
        out.append(Signal("no_reply", "be", "no_reply", now))
    return out, 0
