"""시계와 논리적 날짜 (스펙 5.3: 시간대 Asia/Seoul, 하루 경계 04:00)."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta, tzinfo
from typing import Protocol
from zoneinfo import ZoneInfo

from my_planner.domain import Cadence


class Clock(Protocol):
    def now(self) -> datetime:
        """지금 시각(UTC aware)."""
        ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class FakeClock:
    """테스트용 시계. `start`는 시간대가 있는 시각이어야 한다."""

    def __init__(self, start: datetime) -> None:
        self._now = _require_aware(start).astimezone(UTC)

    def now(self) -> datetime:
        return self._now

    def advance(self, delta: timedelta | None = None, **kwargs: float) -> datetime:
        self._now += delta if delta is not None else timedelta(**kwargs)
        return self._now

    def set(self, dt: datetime) -> None:
        self._now = _require_aware(dt).astimezone(UTC)


def _require_aware(dt: datetime) -> datetime:
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError("시간대가 없는 datetime은 쓰지 않는다")
    return dt


def _zone(tz: str | tzinfo) -> tzinfo:
    return ZoneInfo(tz) if isinstance(tz, str) else tz


def local(dt: datetime, tz: str | tzinfo) -> datetime:
    return _require_aware(dt).astimezone(_zone(tz))


def logical_date(dt: datetime, tz: str | tzinfo, boundary: time) -> date:
    """하루 경계(`boundary`) 전의 시각은 전날로 센다."""
    lt = local(dt, tz)
    d = lt.date()
    return d - timedelta(days=1) if lt.time() < boundary else d


def period_of(cadence: Cadence | str, d: date) -> str:
    """주기별 기간 이름: 2026-10-23, 2026-W43(ISO 주), 2026-10, 2026-Q4, 2026."""
    c = Cadence(cadence)
    if c is Cadence.day:
        return d.isoformat()
    if c is Cadence.week:
        iso_year, iso_week, _ = d.isocalendar()
        return f"{iso_year}-W{iso_week:02d}"
    if c is Cadence.month:
        return f"{d.year}-{d.month:02d}"
    if c is Cadence.quarter:
        return f"{d.year}-Q{(d.month - 1) // 3 + 1}"
    return f"{d.year}"


def period_bounds(cadence: Cadence | str, period: str) -> tuple[date, date]:
    """`period_of`의 거꾸로: 기간 이름의 첫날과 마지막 날(둘 다 포함). 없는 기간(`2025-W53`)은 ValueError."""
    c = Cadence(cadence)
    if c is Cadence.day:
        d = date.fromisoformat(period)
        return d, d
    if c is Cadence.week:
        y, w = period.split("-W")
        start = date.fromisocalendar(int(y), int(w), 1)
        return start, start + timedelta(days=6)
    if c is Cadence.month:
        y, m = (int(x) for x in period.split("-"))
        start, first_months = date(y, m, 1), 1
    elif c is Cadence.quarter:
        y, q = period.split("-Q")
        start, first_months = date(int(y), (int(q) - 1) * 3 + 1, 1), 3
    else:
        start, first_months = date(int(period), 1, 1), 12
    m = start.month - 1 + first_months
    return start, date(start.year + m // 12, m % 12 + 1, 1) - timedelta(days=1)


def is_weekend(d: date) -> bool:
    return d.weekday() >= 5


def to_iso(dt: datetime) -> str:
    """저장용 UTC ISO 8601 문자열. 같은 형식이라 문자열 비교로 순서를 정할 수 있다."""
    return _require_aware(dt).astimezone(UTC).isoformat(timespec="microseconds")


def from_iso(s: str) -> datetime:
    return datetime.fromisoformat(s).astimezone(UTC)
