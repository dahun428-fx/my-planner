"""events, event_skips, event_reminders 표와 그날 일정 펼치기 (SP9 스펙 5.1, 5.2, ADR 0015).

일정은 정의 한 행(반복 규칙 포함) + 건너뛴 날만 저장한다. 날짜별 일정(그날 일정, `Occurrence`)은 순수 함수 `expand`가
읽을 때 펼친다. 날짜는 현지 날짜(`settings.timezone`, 논리적 날짜가 아니다), 시각은 현지 "HH:MM"이고, 펼친 그날
일정의 시각은 UTC다. 이 모듈은 로그를 남기지 않는다(제목·메모가 로그에 남지 않게).
"""

from __future__ import annotations

import calendar
import sqlite3
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, time, timedelta, tzinfo
from typing import Literal, TypedDict
from zoneinfo import ZoneInfo

from my_planner.clock import Clock, from_iso, local, logical_date, to_iso
from my_planner.domain import Area
from my_planner.store.db import transaction

Repeat = Literal["none", "daily", "weekly", "monthly"]
EventOrigin = Literal["user", "chat", "migrated"]

RANGE_MAX_DAYS = 62  # 기간 조회 최대(5.2, 시작·끝 포함)
EVENTS_MAX = 300  # 살아 있는 일정(5.1 `too_many_events`)
REMIND_CHOICES = (0, 10, 30, 60, 1440)  # `remind_min`. None = 알림 없음
ALL_DAY_REMIND_CHOICES = (0, 1440)  # 하루 종일은 그날 09:00 또는 전날 09:00(5.1)
ALL_DAY_REMIND_AT = time(9, 0)
WEEKDAY_NAMES = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")  # `weekdays` 비트: 월=1, 화=2, … 일=64
TIMING_FIELDS = frozenset(
    {"all_day", "start_date", "start_time", "duration_min", "repeat", "weekdays", "repeat_until", "remind_min"}
)


@dataclass(frozen=True)
class Event:
    """017 `events` 한 행. `start_time`은 현지 벽시계 시각(하루 종일이면 None)."""

    id: int
    title: str
    all_day: bool
    start_date: date
    start_time: time | None
    duration_min: int | None
    repeat: Repeat
    weekdays: int | None
    repeat_until: date | None
    remind_min: int | None
    area: Area | None
    note: str
    origin: EventOrigin
    from_task_id: int | None
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None


class EventFields(TypedDict, total=False):
    """만들기(전부, `title`·`start_date`·`origin` 필수)와 고치기(바꿀 칸만)의 칸. 검증은 부르는 쪽(`tools/events.py`)."""

    title: str
    all_day: bool
    start_date: date
    start_time: time | None
    duration_min: int | None
    repeat: Repeat
    weekdays: int | None
    repeat_until: date | None
    remind_min: int | None
    area: Area | None
    note: str
    origin: EventOrigin
    from_task_id: int | None


@dataclass(frozen=True)
class Occurrence:
    """그날 일정 하나. 시각은 UTC(`start`·`end`·`remind_at`), 하루 종일이면 `start`·`end`는 None."""

    event_id: int
    date: date
    start: datetime | None
    end: datetime | None
    all_day: bool
    title: str
    area: Area | None
    repeat: str
    origin: str
    remind_min: int | None
    remind_at: datetime | None
    skipped: bool = False


def _zone(tz: str | tzinfo) -> tzinfo:
    return ZoneInfo(tz) if isinstance(tz, str) else tz


def weekday_bit(d: date) -> int:
    return 1 << d.weekday()


def weekdays_mask(names: list[str]) -> int:
    """`["mon", "wed"]` → 5. 모르는 이름은 `ValueError`."""
    mask = 0
    for n in names:
        mask |= 1 << WEEKDAY_NAMES.index(n)
    return mask


def weekday_names(mask: int | None) -> list[str] | None:
    if mask is None:
        return None
    return [n for i, n in enumerate(WEEKDAY_NAMES) if mask & (1 << i)]


def _monthly_day(year: int, month: int, day: int) -> date:
    """그 달에 그 날짜가 없으면(31일, 2월 29·30일) 그 달 마지막 날(5.1)."""
    return date(year, month, min(day, calendar.monthrange(year, month)[1]))


def _dates(event: Event, start: date, end: date) -> list[date]:
    """`[start, end]`(포함) 안의 그날 일정 날짜. 첫 날 앞과 `repeat_until` 뒤는 없다."""
    lo = max(start, event.start_date)
    hi = end if event.repeat_until is None else min(end, event.repeat_until)
    if lo > hi:
        return []
    if event.repeat == "none":
        return [event.start_date] if lo <= event.start_date <= hi else []
    if event.repeat == "daily":
        return [lo + timedelta(days=i) for i in range((hi - lo).days + 1)]
    if event.repeat == "weekly":
        mask = event.weekdays or weekday_bit(event.start_date)
        return [d for i in range((hi - lo).days + 1) if mask & weekday_bit(d := lo + timedelta(days=i))]
    out: list[date] = []  # monthly
    y, m = lo.year, lo.month
    while True:
        d = _monthly_day(y, m, event.start_date.day)
        if d > hi:
            break
        if d >= lo:
            out.append(d)
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def occurrence_at(event: Event, d: date, tz: str | tzinfo) -> Occurrence:
    """그 날짜의 그날 일정(반복 규칙은 보지 않는다: `d`가 그 일정의 날이라고 본다)."""
    z = _zone(tz)
    start = end = None
    remind_at = None
    if event.all_day:
        if event.remind_min is not None:
            remind_at = (datetime.combine(d, ALL_DAY_REMIND_AT, z) - timedelta(minutes=event.remind_min)).astimezone(UTC)
    else:
        assert event.start_time is not None
        start = datetime.combine(d, event.start_time, z).astimezone(UTC)
        end = start + timedelta(minutes=event.duration_min) if event.duration_min is not None else None
        if event.remind_min is not None:
            remind_at = start - timedelta(minutes=event.remind_min)
    return Occurrence(
        event_id=event.id, date=d, start=start, end=end, all_day=event.all_day, title=event.title, area=event.area,
        repeat=event.repeat, origin=event.origin, remind_min=event.remind_min, remind_at=remind_at,
    )


def check_range(start: date, end: date) -> None:
    """기간(포함)이 거꾸로이거나 62일을 넘으면 `ValueError`."""
    if end < start:
        raise ValueError("end_before_start")
    if (end - start).days + 1 > RANGE_MAX_DAYS:
        raise ValueError("range_too_long")


def expand(event: Event, start: date, end: date, *, tz: str | tzinfo, skips: set[date]) -> list[Occurrence]:
    """`[start, end]`(현지 날짜, 포함) 안의 그날 일정(날짜순). 건너뛴 날(`skips`)은 뺀다. 순수 함수.

    매달 반복의 날짜가 없는 달은 그 달 마지막 날로 옮긴다(1월 31일 → 2월 28일 → 3월 31일). 기간이 62일을 넘거나
    거꾸로면 `ValueError`."""
    check_range(start, end)
    return [occurrence_at(event, d, tz) for d in _dates(event, start, end) if d not in skips]


def sort_key(o: Occurrence) -> tuple[date, bool, datetime, int]:
    """날짜, 하루 종일 먼저, 시작 시각, 일정 번호(9.2 그날 목록)."""
    return (o.date, not o.all_day, o.start or datetime.min.replace(tzinfo=UTC), o.event_id)


def _hhmm(v: str | None) -> time | None:
    return time.fromisoformat(v) if v else None


def _event(r: sqlite3.Row) -> Event:
    return Event(
        id=r["id"],
        title=r["title"],
        all_day=bool(r["all_day"]),
        start_date=date.fromisoformat(r["start_date"]),
        start_time=_hhmm(r["start_time"]),
        duration_min=r["duration_min"],
        repeat=r["repeat"],
        weekdays=r["weekdays"],
        repeat_until=date.fromisoformat(r["repeat_until"]) if r["repeat_until"] else None,
        remind_min=r["remind_min"],
        area=Area(r["area"]) if r["area"] is not None else None,
        note=r["note"],
        origin=r["origin"],
        from_task_id=r["from_task_id"],
        created_at=from_iso(r["created_at"]),
        updated_at=from_iso(r["updated_at"]),
        deleted_at=from_iso(r["deleted_at"]) if r["deleted_at"] else None,
    )


def _db(field: str, v: object) -> object:
    """칸 값 → 저장 값."""
    if v is None:
        return None
    if field == "all_day":
        return 1 if v else 0
    if field in ("start_date", "repeat_until"):
        return v.isoformat()  # type: ignore[attr-defined]
    if field == "start_time":
        return f"{v:%H:%M}"
    if field == "area":
        return Area(v).value  # type: ignore[arg-type]
    return v


_COLUMNS = (
    "title", "all_day", "start_date", "start_time", "duration_min", "repeat", "weekdays", "repeat_until",
    "remind_min", "area", "note", "origin", "from_task_id",
)


class EventsRepo:
    def __init__(self, conn: sqlite3.Connection, clock: Clock, tz: str | tzinfo) -> None:
        self.conn = conn
        self.clock = clock
        self.tz = _zone(tz)

    # --- 읽기 ---

    def get(self, id: int, *, include_deleted: bool = False) -> Event | None:
        """살아 있는 일정. 지운 일정은 `include_deleted`일 때만."""
        sql = "SELECT * FROM events WHERE id = ?" + ("" if include_deleted else " AND deleted_at IS NULL")
        r = self.conn.execute(sql, (id,)).fetchone()
        return _event(r) if r else None

    def count_live(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM events WHERE deleted_at IS NULL").fetchone()[0]

    def live(self) -> list[Event]:
        rows = self.conn.execute("SELECT * FROM events WHERE deleted_at IS NULL ORDER BY start_date, id").fetchall()
        return [_event(r) for r in rows]

    def skips(self) -> dict[int, set[date]]:
        """살아 있는 일정마다 건너뛴 날."""
        out: dict[int, set[date]] = {}
        for r in self.conn.execute(
            "SELECT s.event_id, s.occurrence_date FROM event_skips s JOIN events e ON e.id = s.event_id "
            "WHERE e.deleted_at IS NULL"
        ):
            out.setdefault(r[0], set()).add(date.fromisoformat(r[1]))
        return out

    def skipped_dates(self, id: int) -> list[date]:
        rows = self.conn.execute(
            "SELECT occurrence_date FROM event_skips WHERE event_id = ? ORDER BY occurrence_date", (id,)
        ).fetchall()
        return [date.fromisoformat(r[0]) for r in rows]

    def occurrences(self, start: date, end: date, include_skipped: bool = False) -> list[Occurrence]:
        """기간(현지 날짜, 포함, 최대 62일) 안의 살아 있는 일정의 그날 일정: 날짜, 하루 종일 먼저, 시작 시각순.
        건너뛴 날은 빼고, `include_skipped`이면 `skipped=True`로 넣는다. 기간이 틀리면 `ValueError`."""
        check_range(start, end)
        skips = self.skips()
        out: list[Occurrence] = []
        for e in self.live():
            mine = skips.get(e.id, set())
            for o in expand(e, start, end, tz=self.tz, skips=set()):
                if o.date in mine:
                    if include_skipped:
                        out.append(replace(o, skipped=True))
                else:
                    out.append(o)
        return sorted(out, key=sort_key)

    def on_logical_date(self, d: date, boundary: time) -> list[Occurrence]:
        """논리적 날짜 `d`의 그날 일정(오늘 화면, 앞머리 "## 오늘 일정", Review Focus 1). 하루 종일은 현지 날짜 `d`,
        시각 있는 것은 시작 시각의 논리적 날짜가 `d`인 것: 현지 `d`의 경계(04:00) 뒤 + 현지 `d+1`의 경계 전."""
        got = self.occurrences(d, d + timedelta(days=1))
        return [
            o for o in got
            if (o.date == d if o.all_day else logical_date(o.start, self.tz, boundary) == d)  # type: ignore[arg-type]
        ]

    def has_occurrence(self, e: Event, d: date) -> bool:
        """`d`가 그 일정의 날인가(건너뛴 날도 날이다)."""
        return bool(expand(e, d, d, tz=self.tz, skips=set()))

    # --- 쓰기 (`transaction`: 바깥 트랜잭션에 합류하고, 혼자 부르면 커밋한다. 상한은 부르는 쪽이 본다) ---

    def create(self, fields: EventFields, now: datetime) -> Event:
        at = to_iso(now)
        values = {c: _db(c, fields.get(c)) for c in _COLUMNS}
        values["all_day"] = values["all_day"] or 0
        values["repeat"] = values["repeat"] or "none"
        values["note"] = values["note"] or ""
        cols = [*_COLUMNS, "created_at", "updated_at"]
        with transaction(self.conn):
            eid = self.conn.execute(
                f"INSERT INTO events ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})",
                [*(values[c] for c in _COLUMNS), at, at],
            ).lastrowid
        got = self.get(int(eid))  # type: ignore[arg-type]
        assert got is not None
        return got

    def update(self, id: int, fields: EventFields, now: datetime) -> Event:
        """바꿀 칸만. 시각·반복·알림 칸이 바뀌면 그 일정의 앞으로의 `event_reminders` 행(아직 시작 전인 날, 바꾸기 전
        규칙으로 본다)을 지운다(5.3: 새 시각으로 다시 판정한다)."""
        before = self.get(id)
        assert before is not None
        sets = [c for c in _COLUMNS if c in fields]
        with transaction(self.conn):
            if sets:
                self.conn.execute(
                    f"UPDATE events SET {', '.join(f'{c} = ?' for c in sets)}, updated_at = ? WHERE id = ?",
                    [*(_db(c, fields[c]) for c in sets), to_iso(now), id],  # type: ignore[literal-required]
                )
            if TIMING_FIELDS & set(sets):
                self.clear_future_reminders(before, now)
        got = self.get(id)
        assert got is not None
        return got

    def clear_future_reminders(self, before: Event, now: datetime) -> int:
        """그 일정의 `event_reminders` 행 가운데 그날 일정이 아직 시작 전인 것(하루 종일은 그날이 아직 안 지난 것)을
        지운다. 시작은 `before`(바꾸기 전 규칙)로 계산한다. 지운 수."""
        today = local(now, self.tz).date()
        rows = self.conn.execute(
            "SELECT occurrence_date FROM event_reminders WHERE event_id = ? AND occurrence_date >= ?",
            (before.id, (today - timedelta(days=1)).isoformat()),
        ).fetchall()
        gone = []
        for r in rows:
            d = date.fromisoformat(r[0])
            o = occurrence_at(before, d, self.tz)
            if (d >= today) if o.all_day else (o.start is not None and o.start > now):
                gone.append(r[0])
        with transaction(self.conn):
            for d_iso in gone:
                self.conn.execute(
                    "DELETE FROM event_reminders WHERE event_id = ? AND occurrence_date = ?", (before.id, d_iso)
                )
        return len(gone)

    def delete(self, id: int, now: datetime) -> None:
        """소프트 삭제(`deleted_at`). `restore`로 되살린다."""
        with transaction(self.conn):
            self.conn.execute(
                "UPDATE events SET deleted_at = ?, updated_at = ? WHERE id = ? AND deleted_at IS NULL",
                (to_iso(now), to_iso(now), id),
            )

    def restore(self, id: int) -> bool:
        """되살린다. `updated_at = 지금`: SP9-06 알림 판정(`remind_at > updated_at`)이 되살리기 전 회차를 보내지 않게."""
        with transaction(self.conn):
            cur = self.conn.execute(
                "UPDATE events SET deleted_at = NULL, updated_at = ? WHERE id = ? AND deleted_at IS NOT NULL",
                (to_iso(self.clock.now()), id),
            )
        return cur.rowcount == 1

    def skip(self, id: int, d: date) -> bool:
        """이번만 건너뛰기. 이미 건너뛴 날이면 False."""
        with transaction(self.conn):
            cur = self.conn.execute(
                "INSERT OR IGNORE INTO event_skips (event_id, occurrence_date, created_at) VALUES (?, ?, ?)",
                (id, d.isoformat(), to_iso(self.clock.now())),
            )
        return cur.rowcount == 1

    def unskip(self, id: int, d: date) -> bool:
        """건너뛰기를 되돌린다. 되살리기처럼 `updated_at = 지금`(SP9-06 `remind_at > updated_at`)."""
        with transaction(self.conn):
            cur = self.conn.execute(
                "DELETE FROM event_skips WHERE event_id = ? AND occurrence_date = ?", (id, d.isoformat())
            )
            if cur.rowcount == 1:
                self.conn.execute(
                    "UPDATE events SET updated_at = ? WHERE id = ?", (to_iso(self.clock.now()), id)
                )
        return cur.rowcount == 1

    def end_repeat(self, id: int, from_date: date, now: datetime) -> Event | None:
        """이후 반복 끝내기: `repeat_until = from_date - 1일`. `from_date`가 첫 날(이하)이면 지우기와 같다(None)."""
        e = self.get(id)
        assert e is not None
        if from_date <= e.start_date:
            self.delete(id, now)
            return None
        return self.update(id, {"repeat_until": from_date - timedelta(days=1)}, now)

    # --- 알림 판정 기록 (`event_reminders`, SP9 5.3) ---

    def decided_reminders(self, first: date, last: date) -> set[tuple[int, date]]:
        """`[first, last]`(그날 일정의 현지 날짜) 안에서 이미 판정한 (일정 번호, 날짜). 같은 날에 두 번 판정하지 않는다."""
        rows = self.conn.execute(
            "SELECT event_id, occurrence_date FROM event_reminders WHERE occurrence_date BETWEEN ? AND ?",
            (first.isoformat(), last.isoformat()),
        ).fetchall()
        return {(r[0], date.fromisoformat(r[1])) for r in rows}

    def record_reminder(self, event_id: int, d: date, remind_at: datetime, outcome: str, now: datetime) -> None:
        """판정 한 줄. 이미 있으면 그대로 둔다(먼저 적은 쪽이 맞다)."""
        with transaction(self.conn):
            self.conn.execute(
                "INSERT OR IGNORE INTO event_reminders (event_id, occurrence_date, remind_at, outcome, decided_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (event_id, d.isoformat(), to_iso(remind_at), outcome, to_iso(now)),
            )

    def mark_reminder_failed(self, event_id: int, d: date) -> bool:
        """보냈다고 적은 줄(`sent`·`late_sent`)을 `failed`로 고친다. 그 밖의 줄은 건드리지 않는다."""
        with transaction(self.conn):
            cur = self.conn.execute(
                "UPDATE event_reminders SET outcome = 'failed' WHERE event_id = ? AND occurrence_date = ? "
                "AND outcome IN ('sent', 'late_sent')",
                (event_id, d.isoformat()),
            )
        return cur.rowcount == 1

    def reminders_attempted_since(self, since: datetime) -> int:
        """`since` 이후에 보내려 한 알림 수(`sent`·`late_sent`·`failed`). 하루 상한 계산용."""
        return self.conn.execute(
            "SELECT COUNT(*) FROM event_reminders WHERE decided_at >= ? AND outcome IN ('sent', 'late_sent', 'failed')",
            (to_iso(since),),
        ).fetchone()[0]

    def open_unsent_reminders(self, keys: list[tuple[int, date]]) -> dict[tuple[int, date], str]:
        """(일정 번호, 날짜)마다 닫지 않은 `missed`·`failed`·`skipped` 줄의 결과."""
        out: dict[tuple[int, date], str] = {}
        for eid, d in keys:
            r = self.conn.execute(
                "SELECT outcome FROM event_reminders WHERE event_id = ? AND occurrence_date = ? "
                "AND outcome IN ('missed', 'failed', 'skipped') AND dismissed_at IS NULL",
                (eid, d.isoformat()),
            ).fetchone()
            if r is not None:
                out[(eid, d)] = r[0]
        return out
