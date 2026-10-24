"""curve_* 표 (SP3-4 스펙 5.4). 읽기(티켓 03)와 쓰기(티켓 11).

쓰기 함수는 바깥 트랜잭션(`store.db.transaction`)에 합류한다. 초안은 빼거나 만료되면 **행을 지운다**(5.4).
로그에 제목, 메모를 남기지 않는다.
"""

from __future__ import annotations

import calendar
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime

from my_planner.clock import Clock, from_iso, to_iso
from my_planner.store.db import transaction


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


@dataclass
class Question:
    id: int
    text: str
    status: str
    asked_at: datetime | None
    answered_at: datetime | None


def _question(r: sqlite3.Row) -> Question:
    return Question(
        id=r["id"], text=r["text"], status=r["status"],
        asked_at=from_iso(r["asked_at"]) if r["asked_at"] else None,
        answered_at=from_iso(r["answered_at"]) if r["answered_at"] else None,
    )


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


def date_precision(date_text: str) -> tuple[str, date]:
    """`'YYYY'`·`'YYYY-MM'`·`'YYYY-MM-DD'` → (`precision`, `sort_date` = 그 기간의 첫날). 형식이 틀리면 `ValueError`."""
    parts = date_text.split("-")
    if not 1 <= len(parts) <= 3 or len(parts[0]) != 4 or any(len(p) != 2 for p in parts[1:]):
        raise ValueError("date_text")
    if not all(p.isdigit() for p in parts):
        raise ValueError("date_text")
    y = int(parts[0])
    m = int(parts[1]) if len(parts) > 1 else 1
    d = int(parts[2]) if len(parts) > 2 else 1
    return ("year", "month", "day")[len(parts) - 1], date(y, m, d)  # 없는 날짜는 date가 ValueError


class CurveRepo:
    """읽기 함수는 읽기 전용 연결(`open_ro`)로도 쓴다. 쓰기 함수는 즉시 갈래(`Tools`)와 시드 가져오기만 부른다."""

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

    def latest_area_scores(self, up_to_period: str) -> dict[str, AreaScore]:
        """영역마다 `up_to_period`까지(포함) 점수가 있는 가장 최근 분기의 행."""
        rows = self.conn.execute(
            "SELECT s.* FROM curve_area_scores s WHERE s.period <= ? AND s.period = "
            "(SELECT MAX(period) FROM curve_area_scores WHERE area = s.area AND period <= ?)",
            (up_to_period, up_to_period),
        ).fetchall()
        return {r["area"]: _area_score(r) for r in rows}

    def area_score(self, period: str, area: str) -> AreaScore | None:
        r = self.conn.execute(
            "SELECT * FROM curve_area_scores WHERE period = ? AND area = ?", (period, area)
        ).fetchone()
        return _area_score(r) if r else None

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

    def confirmed_chapters(self) -> list[Chapter]:
        rows = self.conn.execute(
            "SELECT * FROM curve_chapters WHERE status = 'confirmed' ORDER BY start_month, id"
        ).fetchall()
        return [_chapter(r) for r in rows]

    def confirmed_milestones(self) -> list[Milestone]:
        rows = self.conn.execute(
            "SELECT * FROM curve_milestones WHERE status = 'confirmed' ORDER BY sort_date, id"
        ).fetchall()
        return [_milestone(r) for r in rows]

    def ladder(self, period: str) -> Ladder | None:
        r = self.conn.execute("SELECT * FROM curve_ladder_scores WHERE period = ?", (period,)).fetchone()
        return _ladder(r) if r else None

    # --- 쓰기: 챕터와 사건 ---

    def _now(self) -> str:
        return to_iso(self.clock.now())

    def add_chapter(
        self, *, title: str, start_month: str, status: str, origin: str, end_month: str | None = None,
        theme: str | None = None, sketch: str | None = None, certainty: str = "fact", seed_key: str | None = None,
        source_ref: str | None = None,
    ) -> Chapter:
        """챕터 한 행. 초안이면 `draft_since` = 지금(만료 시계의 시작)."""
        now = self._now()
        with transaction(self.conn):
            cur = self.conn.execute(
                "INSERT INTO curve_chapters (seed_key, title, theme, start_month, end_month, sketch, certainty, "
                "status, origin, source_ref, draft_since, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (seed_key, title, theme, start_month, end_month, sketch, certainty, status, origin, source_ref,
                 now if status == "draft" else None, now, now),
            )
        got = self.get_chapter(int(cur.lastrowid))  # type: ignore[arg-type]
        assert got is not None
        return got

    def add_milestone(
        self, *, date_text: str, kind: str, title: str, status: str, origin: str, note: str | None = None,
        chapter_id: int | None = None, sensitive: bool = False, certainty: str = "fact",
        kind_certainty: str = "fact", conversation_id: int | None = None, source_ref: str | None = None,
    ) -> Milestone:
        """사건 한 행. `precision`·`sort_date`는 `date_text`에서(형식이 틀리면 `ValueError`). 초안이면 `draft_since` = 지금,
        확정이면 `confirmed_at` = 지금."""
        precision, sort_date = date_precision(date_text)
        now = self._now()
        with transaction(self.conn):
            cur = self.conn.execute(
                "INSERT INTO curve_milestones (chapter_id, date_text, precision, sort_date, kind, kind_certainty, "
                "title, note, sensitive, certainty, status, origin, conversation_id, source_ref, draft_since, "
                "created_at, confirmed_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (chapter_id, date_text, precision, sort_date.isoformat(), kind, kind_certainty, title, note,
                 1 if sensitive else 0, certainty, status, origin, conversation_id, source_ref,
                 now if status == "draft" else None, now, now if status == "confirmed" else None, now),
            )
        got = self.get_milestone(int(cur.lastrowid))  # type: ignore[arg-type]
        assert got is not None
        return got

    def confirm_milestones(self, ids: list[int]) -> list[Milestone]:
        """초안만 확정한다(`confirmed_at` = 지금, `draft_since` = NULL). 확정한 사건을 그 순서로 돌려준다."""
        now = self._now()
        out: list[Milestone] = []
        with transaction(self.conn):
            for i in dict.fromkeys(ids):
                cur = self.conn.execute(
                    "UPDATE curve_milestones SET status = 'confirmed', confirmed_at = ?, draft_since = NULL, "
                    "updated_at = ? WHERE id = ? AND status = 'draft'",
                    (now, now, i),
                )
                if cur.rowcount and (m := self.get_milestone(i)) is not None:
                    out.append(m)
        return out

    def confirm_chapters(self, ids: list[int]) -> list[Chapter]:
        now = self._now()
        out: list[Chapter] = []
        with transaction(self.conn):
            for i in dict.fromkeys(ids):
                cur = self.conn.execute(
                    "UPDATE curve_chapters SET status = 'confirmed', draft_since = NULL, updated_at = ? "
                    "WHERE id = ? AND status = 'draft'",
                    (now, i),
                )
                if cur.rowcount and (c := self.get_chapter(i)) is not None:
                    out.append(c)
        return out

    def unconfirm_milestone(self, id: int, at: datetime) -> bool:
        """확정을 되돌린다: 초안으로, `draft_since` = `at`(3일을 다시 센다, 6.4.3). 확정이 아니었으면 False."""
        with transaction(self.conn):
            cur = self.conn.execute(
                "UPDATE curve_milestones SET status = 'draft', confirmed_at = NULL, draft_since = ?, updated_at = ? "
                "WHERE id = ? AND status = 'confirmed'",
                (to_iso(at), to_iso(at), id),
            )
        return cur.rowcount > 0

    def unconfirm_chapter(self, id: int, at: datetime) -> bool:
        with transaction(self.conn):
            cur = self.conn.execute(
                "UPDATE curve_chapters SET status = 'draft', draft_since = ?, updated_at = ? "
                "WHERE id = ? AND status = 'confirmed'",
                (to_iso(at), to_iso(at), id),
            )
        return cur.rowcount > 0

    def delete_milestone_draft(self, id: int) -> bool:
        """초안 행을 지운다. 확정한 사건이나 없는 번호는 False(지우지 않는다)."""
        with transaction(self.conn):
            cur = self.conn.execute("DELETE FROM curve_milestones WHERE id = ? AND status = 'draft'", (id,))
        return cur.rowcount > 0

    def delete_chapter_draft(self, id: int) -> bool:
        """챕터 초안 행을 지운다. 그 챕터를 가리키던 사건의 `chapter_id`는 `ON DELETE SET NULL`로 비워진다."""
        with transaction(self.conn):
            cur = self.conn.execute("DELETE FROM curve_chapters WHERE id = ? AND status = 'draft'", (id,))
        return cur.rowcount > 0

    def expire_drafts(self, older_than: datetime) -> tuple[list[int], list[int]]:
        """`draft_since`가 `older_than`이거나 그보다 먼저인 초안을 지운다(딱 3일이 된 것도). (사건 id, 챕터 id)."""
        cutoff = to_iso(older_than)
        with transaction(self.conn):
            ms = [r["id"] for r in self.conn.execute(
                "SELECT id FROM curve_milestones WHERE status = 'draft' AND draft_since <= ? ORDER BY id", (cutoff,)
            ).fetchall()]
            cs = [r["id"] for r in self.conn.execute(
                "SELECT id FROM curve_chapters WHERE status = 'draft' AND draft_since <= ? ORDER BY id", (cutoff,)
            ).fetchall()]
            for i in ms:
                self.delete_milestone_draft(i)
            for i in cs:
                self.delete_chapter_draft(i)
        return ms, cs

    # --- 쓰기: 사다리와 영역 점수 ---

    def set_ladder(self, period: str, *, now: int | None, future: int | None, note: str | None) -> Ladder:
        """그 달 사다리. 주지 않은 쪽(`None`)은 기존 값을 둔다(5년 뒤만 먼저 답해도 된다, 10장)."""
        with transaction(self.conn):
            self.conn.execute(
                "INSERT INTO curve_ladder_scores (period, now, future, note, recorded_at) VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT (period) DO UPDATE SET now = COALESCE(excluded.now, curve_ladder_scores.now), "
                "future = COALESCE(excluded.future, curve_ladder_scores.future), "
                "note = COALESCE(excluded.note, curve_ladder_scores.note), recorded_at = excluded.recorded_at",
                (period, now, future, note, self._now()),
            )
        got = self.ladder(period)
        assert got is not None
        return got

    def restore_ladder(self, period: str, before: Ladder | None) -> None:
        """되돌리기: 이전 행 그대로(`recorded_at` 포함). 없었으면 지운다."""
        with transaction(self.conn):
            self.conn.execute("DELETE FROM curve_ladder_scores WHERE period = ?", (period,))
            if before is not None:
                self.conn.execute(
                    "INSERT INTO curve_ladder_scores (period, now, future, note, recorded_at) VALUES (?, ?, ?, ?, ?)",
                    (period, before.now, before.future, before.note, to_iso(before.recorded_at)),
                )

    def set_area_scores(
        self, period: str, scores: dict[str, int], *, notes: dict[str, str] | None = None,
        quests: dict[str, str] | None = None,
    ) -> list[AreaScore]:
        """그 분기의 영역 점수(준 영역만). 메모는 준 것만 바꾸고 없으면 기존 값을 둔다. 회복 퀘스트는 이번 호출에서
        준 값으로 덮어쓴다: 주지 않은 영역은 예전 퀘스트를 지운다(고친 점수에 낡은 퀘스트가 남지 않게)."""
        notes, quests = notes or {}, quests or {}
        now = self._now()
        with transaction(self.conn):
            for area, score in scores.items():
                self.conn.execute(
                    "INSERT INTO curve_area_scores (period, area, score, note, recovery_quest, recorded_at) "
                    "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT (period, area) DO UPDATE SET score = excluded.score, "
                    "note = COALESCE(excluded.note, curve_area_scores.note), "
                    "recovery_quest = excluded.recovery_quest, "
                    "recorded_at = excluded.recorded_at",
                    (period, area, score, notes.get(area), quests.get(area), now),
                )
        return [s for s in self.area_scores(period) if s.area in scores]

    def restore_area_scores(self, period: str, before: dict[str, AreaScore | None]) -> None:
        """되돌리기: 영역마다 이전 행 그대로, 없었으면 지운다."""
        with transaction(self.conn):
            for area, row in before.items():
                self.conn.execute("DELETE FROM curve_area_scores WHERE period = ? AND area = ?", (period, area))
                if row is not None:
                    self.conn.execute(
                        "INSERT INTO curve_area_scores (period, area, score, note, recovery_quest, recorded_at) "
                        "VALUES (?, ?, ?, ?, ?, ?)",
                        (period, area, row.score, row.note, row.recovery_quest, to_iso(row.recorded_at)),
                    )

    def set_area_default(self, area: str, recovery_quest: str) -> None:
        """영역별 기본 회복 퀘스트(시드에서 확인한 것)."""
        with transaction(self.conn):
            self.conn.execute(
                "INSERT INTO curve_area_defaults (area, recovery_quest, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT (area) DO UPDATE SET recovery_quest = excluded.recovery_quest, "
                "updated_at = excluded.updated_at",
                (area, recovery_quest, self._now()),
            )

    # --- 시드 질문 (11.1 5단계) ---

    def add_question(self, text: str) -> int:
        with transaction(self.conn):
            cur = self.conn.execute("INSERT INTO curve_questions (text) VALUES (?)", (text,))
        return int(cur.lastrowid)  # type: ignore[arg-type]

    def next_open_question(self) -> Question | None:
        r = self.conn.execute(
            "SELECT * FROM curve_questions WHERE status = 'open' ORDER BY id LIMIT 1"
        ).fetchone()
        return _question(r) if r else None

    def mark_question(self, id: int, status: str) -> None:
        """`asked`면 `asked_at`, `answered`면 `answered_at`을 지금으로 적는다. `skipped`는 상태만."""
        now = self._now()
        with transaction(self.conn):
            self.conn.execute(
                "UPDATE curve_questions SET status = ?, "
                "asked_at = CASE WHEN ? = 'asked' THEN ? ELSE asked_at END, "
                "answered_at = CASE WHEN ? = 'answered' THEN ? ELSE answered_at END WHERE id = ?",
                (status, status, now, status, now, id),
            )
