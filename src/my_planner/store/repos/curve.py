"""curve_* 표 읽기 (SP3-4 스펙 5.4). 쓰기는 이 티켓 밖이다."""

from __future__ import annotations

import calendar
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime

from my_planner.clock import Clock, from_iso


@dataclass
class Chapter:
    id: int
    seed_key: str | None
    title: str
    theme: str | None
    start_month: str
    end_month: str | None
    sketch: str | None
    certainty: str
    status: str
    origin: str
    source_ref: str | None
    draft_since: str | None
    created_at: datetime
    updated_at: datetime


@dataclass
class Milestone:
    id: int
    chapter_id: int | None
    date_text: str
    precision: str
    sort_date: date
    kind: str
    kind_certainty: str
    title: str
    note: str | None
    sensitive: bool
    certainty: str
    status: str
    origin: str
    title_label: str | None
    conversation_id: int | None
    source_ref: str | None
    draft_since: str | None
    created_at: datetime
    confirmed_at: datetime | None
    updated_at: datetime

    @property
    def end_date(self) -> date:
        """그 기간의 마지막 날(`precision`이 year면 12/31, month면 말일, day면 그날)."""
        d = self.sort_date
        if self.precision == "year":
            return date(d.year, 12, 31)
        if self.precision == "month":
            return date(d.year, d.month, calendar.monthrange(d.year, d.month)[1])
        return d


@dataclass
class Ladder:
    period: str
    now: int | None
    future: int | None
    note: str | None
    recorded_at: datetime


@dataclass
class AreaScore:
    period: str
    area: str
    score: int
    note: str | None
    recovery_quest: str | None
    recorded_at: datetime


def _chapter(r: sqlite3.Row) -> Chapter:
    return Chapter(
        id=r["id"], seed_key=r["seed_key"], title=r["title"], theme=r["theme"], start_month=r["start_month"],
        end_month=r["end_month"], sketch=r["sketch"], certainty=r["certainty"], status=r["status"],
        origin=r["origin"], source_ref=r["source_ref"], draft_since=r["draft_since"],
        created_at=from_iso(r["created_at"]), updated_at=from_iso(r["updated_at"]),
    )


def _milestone(r: sqlite3.Row) -> Milestone:
    return Milestone(
        id=r["id"], chapter_id=r["chapter_id"], date_text=r["date_text"], precision=r["precision"],
        sort_date=date.fromisoformat(r["sort_date"]), kind=r["kind"], kind_certainty=r["kind_certainty"],
        title=r["title"], note=r["note"], sensitive=bool(r["sensitive"]), certainty=r["certainty"],
        status=r["status"], origin=r["origin"], title_label=r["title_label"],
        conversation_id=r["conversation_id"], source_ref=r["source_ref"], draft_since=r["draft_since"],
        created_at=from_iso(r["created_at"]),
        confirmed_at=from_iso(r["confirmed_at"]) if r["confirmed_at"] else None,
        updated_at=from_iso(r["updated_at"]),
    )


def _ladder(r: sqlite3.Row) -> Ladder:
    return Ladder(period=r["period"], now=r["now"], future=r["future"], note=r["note"],
                  recorded_at=from_iso(r["recorded_at"]))


def _area_score(r: sqlite3.Row) -> AreaScore:
    return AreaScore(period=r["period"], area=r["area"], score=r["score"], note=r["note"],
                     recovery_quest=r["recovery_quest"], recorded_at=from_iso(r["recorded_at"]))


class CurveRepo:
    """읽기만 한다. 그래서 읽기 전용 연결(`open_ro`)로도 쓴다."""

    def __init__(self, conn: sqlite3.Connection, clock: Clock) -> None:
        self.conn = conn
        self.clock = clock

    def chapters_overlapping(self, from_month: str, to_month: str) -> list[Chapter]:
        """`YYYY-MM` 범위(포함)와 겹치는 **확정** 챕터, 시작 달순. `end_month`가 NULL이면 지금까지."""
        rows = self.conn.execute(
            "SELECT * FROM curve_chapters WHERE status = 'confirmed' AND start_month <= ? "
            "AND (end_month IS NULL OR end_month >= ?) ORDER BY start_month, id",
            (to_month, from_month),
        ).fetchall()
        return [_chapter(r) for r in rows]

    def milestones_between(self, from_: date, to: date, *, include_sensitive: bool) -> list[Milestone]:
        """범위와 겹치는 **확정** 사건, 날짜순. 연·월 단위로 기억한 사건은 그 기간이 범위에 걸치면 넣는다."""
        sql = "SELECT * FROM curve_milestones WHERE status = 'confirmed' AND sort_date <= ?"
        if not include_sensitive:
            sql += " AND sensitive = 0"
        sql += " ORDER BY sort_date, id"
        found = [_milestone(r) for r in self.conn.execute(sql, (to.isoformat(),)).fetchall()]
        return [m for m in found if m.end_date >= from_]

    def ladder_between(self, from_month: str, to_month: str) -> list[Ladder]:
        rows = self.conn.execute(
            "SELECT * FROM curve_ladder_scores WHERE period >= ? AND period <= ? ORDER BY period",
            (from_month, to_month),
        ).fetchall()
        return [_ladder(r) for r in rows]

    def area_scores_between(self, from_period: str, to_period: str) -> list[AreaScore]:
        """`YYYY-Qn` 범위(포함)의 영역 점수, 분기순."""
        rows = self.conn.execute(
            "SELECT * FROM curve_area_scores WHERE period >= ? AND period <= ? ORDER BY period, area",
            (from_period, to_period),
        ).fetchall()
        return [_area_score(r) for r in rows]

    def latest_area_periods(self, n: int = 2) -> list[str]:
        """점수가 있는 분기 가운데 가장 최근 `n`개, 최근 것이 먼저."""
        rows = self.conn.execute(
            "SELECT DISTINCT period FROM curve_area_scores ORDER BY period DESC LIMIT ?", (n,)
        ).fetchall()
        return [r["period"] for r in rows]

    def area_scores(self, period: str) -> list[AreaScore]:
        rows = self.conn.execute(
            "SELECT * FROM curve_area_scores WHERE period = ? ORDER BY area", (period,)
        ).fetchall()
        return [_area_score(r) for r in rows]

    def area_default(self, area: str) -> str | None:
        r = self.conn.execute("SELECT recovery_quest FROM curve_area_defaults WHERE area = ?", (area,)).fetchone()
        return r["recovery_quest"] if r else None

    def earliest_chapter_start(self) -> date | None:
        """가장 이른 **확정** 챕터의 시작 달 1일. 없으면 None."""
        r = self.conn.execute(
            "SELECT MIN(start_month) AS m FROM curve_chapters WHERE status = 'confirmed'"
        ).fetchone()
        if r is None or r["m"] is None:
            return None
        return date.fromisoformat(r["m"] + "-01")

    def get_milestone(self, id: int) -> Milestone | None:
        r = self.conn.execute("SELECT * FROM curve_milestones WHERE id = ?", (id,)).fetchone()
        return _milestone(r) if r else None

    def get_chapter(self, id: int) -> Chapter | None:
        r = self.conn.execute("SELECT * FROM curve_chapters WHERE id = ?", (id,)).fetchone()
        return _chapter(r) if r else None
