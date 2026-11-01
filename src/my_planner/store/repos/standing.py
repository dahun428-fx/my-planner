"""standing_measures, standing_snapshots 표 (SP13 스펙 6.1).

검사는 부르는 쪽이 먼저 하고, 여기서는 `validate`를 한 번 더 불러 `ValueError`를 낸다.
쓰기는 모두 부르는 쪽 `transaction` 안에서 한다.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from my_planner.clock import Clock, from_iso, to_iso
from my_planner.standing.metrics import METRICS, validate


@dataclass(frozen=True)
class Measure:
    id: int
    metric: str
    value_num: float | None
    value_text: str | None
    measured_on: date
    source_kind: str
    source_ref: str | None
    reliability: str
    created_at: datetime


@dataclass(frozen=True)
class SnapshotRow:
    period: str
    axis: str
    cohort: str
    score: int
    bench_version: str
    inputs: dict[str, Any]
    taken_at: datetime


_COLS = "id, metric, value_num, value_text, measured_on, source_kind, source_ref, reliability, created_at"


def _measure(r: sqlite3.Row) -> Measure:
    return Measure(
        id=r["id"],
        metric=r["metric"],
        value_num=r["value_num"],
        value_text=r["value_text"],
        measured_on=date.fromisoformat(r["measured_on"]),
        source_kind=r["source_kind"],
        source_ref=r["source_ref"],
        reliability=r["reliability"],
        created_at=from_iso(r["created_at"]),
    )


def _snap(r: sqlite3.Row) -> SnapshotRow:
    return SnapshotRow(
        period=r["period"],
        axis=r["axis"],
        cohort=r["cohort"],
        score=r["score"],
        bench_version=r["bench_version"],
        inputs=json.loads(r["inputs_json"]),
        taken_at=from_iso(r["taken_at"]),
    )


class StandingRepo:
    def __init__(self, conn: sqlite3.Connection, clock: Clock) -> None:
        self._conn = conn
        self._clock = clock

    @property
    def conn(self) -> sqlite3.Connection:
        """부르는 쪽 `transaction(repo.conn)`용(다른 저장소와 같은 이름)."""
        return self._conn

    def add(
        self,
        metric: str,
        value: float | str,
        measured_on: date,
        source_kind: str,
        source_ref: str | None,
        reliability: str,
        now: datetime,
    ) -> int:
        # 저장소는 현지 시간대를 모른다: UTC 날짜 + 1일(가장 앞선 시간대)까지 받고, 엄격한 미래 검사는 부르는 쪽이 한다.
        err = validate(metric, value, measured_on, self._clock.now().date() + timedelta(days=1))
        if err:
            raise ValueError(err)
        num = None if isinstance(value, str) else float(value)
        text = value if isinstance(value, str) else None
        cur = self._conn.execute(
            "INSERT INTO standing_measures (metric, value_num, value_text, measured_on, source_kind, source_ref,"
            " reliability, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (metric, num, text, measured_on.isoformat(), source_kind, source_ref, reliability, to_iso(now)),
        )
        assert cur.lastrowid is not None
        return cur.lastrowid

    def get(self, id: int) -> Measure | None:
        r = self._conn.execute(f"SELECT {_COLS} FROM standing_measures WHERE id = ?", (id,)).fetchone()
        return _measure(r) if r else None

    def delete(self, id: int, now: datetime) -> bool:
        cur = self._conn.execute(
            "UPDATE standing_measures SET deleted_at = ? WHERE id = ? AND deleted_at IS NULL", (to_iso(now), id)
        )
        return cur.rowcount > 0

    def restore(self, id: int) -> bool:
        cur = self._conn.execute(
            "UPDATE standing_measures SET deleted_at = NULL WHERE id = ? AND deleted_at IS NOT NULL", (id,)
        )
        return cur.rowcount > 0

    def active(self) -> list[Measure]:
        rows = self._conn.execute(
            f"SELECT {_COLS} FROM standing_measures WHERE deleted_at IS NULL"
            " ORDER BY metric, measured_on DESC, id DESC"
        ).fetchall()
        return [_measure(r) for r in rows]

    def latest(self, as_of: date | None = None) -> dict[str, Measure | list[Measure]]:
        """지표마다 최신 하나(측정일, 다음 id가 큰 것). `cert`는 ':' 앞 키마다 최신 하나씩의 목록."""
        out: dict[str, Measure | list[Measure]] = {}
        certs: dict[str, Measure] = {}
        for m in reversed(self.active()):  # 오래된 것부터 덮어쓴다
            if as_of is not None and m.measured_on > as_of:
                continue
            if METRICS.get(m.metric) and METRICS[m.metric].kind == "multi":
                certs[(m.value_text or "").split(":")[0]] = m
            else:
                out[m.metric] = m
        if certs:
            out["cert"] = list(certs.values())
        return out

    def has_import(self, metric: str, measured_on: date, value_text: str | None = None) -> bool:
        sql = (
            "SELECT 1 FROM standing_measures WHERE metric = ? AND measured_on = ? AND source_kind = 'import'"
            " AND deleted_at IS NULL"
        )
        args: list[Any] = [metric, measured_on.isoformat()]
        if value_text is not None:
            sql += " AND value_text = ?"
            args.append(value_text)
        return self._conn.execute(sql + " LIMIT 1", args).fetchone() is not None

    def snapshot(self, period: str, axis: str, cohort: str) -> SnapshotRow | None:
        r = self._conn.execute(
            "SELECT * FROM standing_snapshots WHERE period = ? AND axis = ? AND cohort = ?", (period, axis, cohort)
        ).fetchone()
        return _snap(r) if r else None

    def snapshots_for(self, period: str) -> list[SnapshotRow]:
        rows = self._conn.execute(
            "SELECT * FROM standing_snapshots WHERE period = ? ORDER BY axis, cohort", (period,)
        ).fetchall()
        return [_snap(r) for r in rows]

    def latest_period_before(self, period: str) -> str | None:
        r = self._conn.execute("SELECT MAX(period) FROM standing_snapshots WHERE period < ?", (period,)).fetchone()
        return r[0]

    def delete_snapshots(self, period: str) -> None:
        self._conn.execute("DELETE FROM standing_snapshots WHERE period = ?", (period,))

    def put_snapshot(
        self,
        period: str,
        axis: str,
        cohort: str,
        score: int,
        bench_version: str,
        inputs_json: str,
        taken_at: datetime,
    ) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO standing_snapshots (period, axis, cohort, score, bench_version, inputs_json,"
            " taken_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (period, axis, cohort, score, bench_version, inputs_json, to_iso(taken_at)),
        )
