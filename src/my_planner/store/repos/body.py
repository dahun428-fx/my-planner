"""body_days 표 (SP8 스펙 7.1, 7.5). 날짜는 아이폰의 달력 날짜, 시각은 UTC ISO 8601.

걸음 수와 잠(분) 두 값만 둔다. 이 모듈은 로그를 남기지 않는다(숫자가 로그에 없다, 7.3).
읽기(`between`, `summary`)는 읽기 전용 연결로도 된다. 쓰기(`upsert`, `prune`)는 즉시 갈래의 도구만 부른다.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from my_planner.clock import Clock, to_iso
from my_planner.store.db import transaction

BODY_KEEP_DAYS = 56  # 보관(7.1). 하루 한 번 작업 `prune_records`가 지운다(계획 결정 17)
SUMMARY_DAYS = 7  # `GET /status`의 `body`: 오늘을 포함한 지난 7일(7.5)


@dataclass(frozen=True)
class BodyDay:
    date: date
    steps: int | None
    sleep_minutes: int | None


def _day(r: sqlite3.Row) -> BodyDay:
    return BodyDay(date=date.fromisoformat(r["date"]), steps=r["steps"], sleep_minutes=r["sleep_minutes"])


def _avg(values: list[int]) -> int | None:
    """정수 평균(반올림 half up). 값이 없으면 None."""
    if not values:
        return None
    return (2 * sum(values) + len(values)) // (2 * len(values))


class BodyRepo:
    def __init__(self, conn: sqlite3.Connection, clock: Clock) -> None:
        self.conn = conn
        self.clock = clock

    def upsert(self, days: list[BodyDay], now: datetime) -> int:
        """날짜마다 넣거나 보낸 값만 바꾼다(`None`은 보내지 않은 값: 그대로 둔다). 한 트랜잭션(바깥에 합류한다)."""
        with transaction(self.conn):
            for d in days:
                self.conn.execute(
                    "INSERT INTO body_days (date, steps, sleep_minutes, updated_at) VALUES (?, ?, ?, ?) "
                    "ON CONFLICT(date) DO UPDATE SET "
                    "steps = COALESCE(excluded.steps, body_days.steps), "
                    "sleep_minutes = COALESCE(excluded.sleep_minutes, body_days.sleep_minutes), "
                    "updated_at = excluded.updated_at",
                    (d.date.isoformat(), d.steps, d.sleep_minutes, to_iso(now)),
                )
        return len(days)

    def between(self, from_: date, to: date) -> list[BodyDay]:
        """`from_..to`(양끝 포함), 오래된 날부터."""
        return [
            _day(r) for r in self.conn.execute(
                "SELECT date, steps, sleep_minutes FROM body_days WHERE date >= ? AND date <= ? ORDER BY date",
                (from_.isoformat(), to.isoformat()),
            ).fetchall()
        ]

    def summary(self, today: date) -> dict[str, Any] | None:
        """`GET /status`의 `body`(7.5). 지난 56일에 행이 없으면 None. 평균은 그 값이 있는 날만의 정수 평균."""
        kept = self.between(today - timedelta(days=BODY_KEEP_DAYS - 1), today)
        if not kept:
            return None
        week = [d for d in kept if d.date >= today - timedelta(days=SUMMARY_DAYS - 1)]
        return {
            "last_date": kept[-1].date.isoformat(),
            "days_7": len(week),
            "steps_avg_7": _avg([d.steps for d in week if d.steps is not None]),
            "sleep_avg_7": _avg([d.sleep_minutes for d in week if d.sleep_minutes is not None]),
        }

    def prune(self, older_than: date) -> int:
        """`older_than`보다 오래된 행을 지운다(7.1 보관)."""
        with transaction(self.conn):
            cur = self.conn.execute("DELETE FROM body_days WHERE date < ?", (older_than.isoformat(),))
        return cur.rowcount
