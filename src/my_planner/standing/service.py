"""지금 위치, 하락 이유, 분기 스냅숏 (SP13-04). 쓰기는 모두 부르는 쪽 트랜잭션 안에서 `conn.execute`로만 한다."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from my_planner.clock import Clock, local, logical_date, period_bounds, period_of
from my_planner.standing import drift as drift_mod
from my_planner.standing.bench import Bench, load_bench, load_bench_version
from my_planner.standing.drift import Drift
from my_planner.standing.markets import Market, market_scores
from my_planner.standing.score import (
    AREAS,
    Axis,
    AxisScore,
    Cohort,
    Values,
    area_positions,
    score_all,
    values_from,
)
from my_planner.store.repos.standing import StandingRepo
from my_planner.store.repos.workout import WorkoutRepo

TZ = "Asia/Seoul"
BOUNDARY = time(4, 0)
COHORTS: tuple[Cohort, ...] = ("national", "peer")


@dataclass
class StandingNow:
    values: Values
    ids: dict[str, int]
    bench: Bench
    scores: dict[Cohort, dict[Axis, AxisScore]]
    areas: dict[Cohort, dict[str, float | None]]
    markets: dict[Cohort, dict[str, Market]]
    profile_missing: bool


def with_derived(values: Values, workout: WorkoutRepo | None, today: date) -> Values:
    """지난 56일에 운동 기록이 있으면 최근 28일 기록 일수로 주당 운동일을 바꾼다."""
    if workout is None or not workout.log_days(today - timedelta(days=55), today):
        return values
    days = len(workout.log_days(today - timedelta(days=27), today))
    return {**values, "exercise_days_week": days / 4}


def current(conn: sqlite3.Connection, clock: Clock, today: date, bench_dir: Path | None = None) -> StandingNow:
    latest = StandingRepo(conn, clock).latest()
    values, ids = values_from(latest)
    values = with_derived(values, WorkoutRepo(conn, clock), today)
    bench = load_bench(today, bench_dir)
    scores: dict[Cohort, dict[Axis, AxisScore]] = {}
    areas: dict[Cohort, dict[str, float | None]] = {}
    markets: dict[Cohort, dict[str, Market]] = {}
    for cohort in COHORTS:
        scores[cohort] = score_all(values, bench, cohort, today)
        areas[cohort] = area_positions(scores[cohort])
        markets[cohort] = market_scores(scores[cohort], bench)
    return StandingNow(values, ids, bench, scores, areas, markets, "profile_birth_year" not in values)


def base_snapshot(repo: StandingRepo, period: str) -> tuple[Values, str, date] | None:
    """비교 기준: 직전 스냅숏 분기, 없으면 이 분기 스냅숏. `national` 줄의 입력값·기준표 버전·찍은 현지 날짜."""
    base = repo.latest_period_before(period) or period
    for row in repo.snapshots_for(base):
        if row.cohort == "national":
            values: Values = row.inputs.get("values", {})
            return values, row.bench_version, local(row.taken_at, TZ).date()
    return None


def area_drifts(conn: sqlite3.Connection, clock: Clock, today: date, now: StandingNow) -> dict[str, Drift | None]:
    base = base_snapshot(StandingRepo(conn, clock), period_of("quarter", today))
    if base is None:
        return {a: None for a in AREAS}
    before_values, version, before_day = base
    before_bench = load_bench_version(version) or load_bench(before_day)
    return {
        a: drift_mod.split(before_values, before_bench, before_day, now.values, now.bench, today, a) for a in AREAS
    }


def _end_of_day(d: date) -> datetime:
    return datetime.combine(d, time(23, 59), tzinfo=ZoneInfo(TZ))


def write_snapshot(
    conn: sqlite3.Connection,
    clock: Clock,
    period: str,
    *,
    as_of: date | None = None,
    today: date | None = None,
    source: str = "review",
) -> int:
    """그 분기 스냅숏 줄을 (다시) 쓴다. 쓴 줄 수. 태어난 해가 없으면 0."""
    repo = StandingRepo(conn, clock)
    now = clock.now()
    day = as_of or today or logical_date(now, TZ, BOUNDARY)
    values, ids = values_from(repo.latest(as_of))
    if "profile_birth_year" not in values:
        return 0
    values = with_derived(values, WorkoutRepo(conn, clock), day)
    bench = load_bench(day)
    taken_at = _end_of_day(as_of) if as_of else now
    inputs = json.dumps({"values": values, "ids": ids, "source": source}, ensure_ascii=False, sort_keys=True)
    rows = [(axis, cohort, s.score) for cohort in COHORTS for axis, s in score_all(values, bench, cohort, day).items()]
    if not rows:
        return 0
    conn.execute("DELETE FROM standing_snapshots WHERE period = ?", (period,))
    for axis, cohort, score in rows:
        repo.put_snapshot(period, axis, cohort, score, bench.version, inputs, taken_at)
    return len(rows)


def snapshot_if_first(conn: sqlite3.Connection, clock: Clock, today: date) -> str | None:
    """스냅숏이 하나도 없을 때만 지금 분기 스냅숏을 쓰고 그 분기를 돌려준다(첫 기준선). 안 썼으면 None."""
    if conn.execute("SELECT 1 FROM standing_snapshots LIMIT 1").fetchone():
        return None
    period = period_of("quarter", today)
    return period if write_snapshot(conn, clock, period, today=today, source="first") else None


def catch_up_snapshots(conn: sqlite3.Connection, clock: Clock, today: date) -> int:
    """지난 분기 스냅숏이 없거나(또는 분기 중간에 찍은 첫 기준선뿐이면) 분기 끝 값으로 쓴다."""
    prev = period_of("quarter", period_bounds("quarter", period_of("quarter", today))[0] - timedelta(days=1))
    end = period_bounds("quarter", prev)[1]
    repo = StandingRepo(conn, clock)
    if not repo.latest(end):
        return 0
    rows = repo.snapshots_for(prev)
    if rows:
        national = [r for r in rows if r.cohort == "national"] or rows
        r = national[0]
        if r.inputs.get("source") == "review" or local(r.taken_at, TZ).date() >= end:
            return 0
    return write_snapshot(conn, clock, prev, as_of=end, source="catch_up")
