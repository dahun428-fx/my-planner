"""인생 곡선 읽기 모델 (SP3-4 스펙 6.3.5, 8장): 확대 단위 묶음, 컨디션 평균, 안심 보기.

순수 함수가 대부분이다. 쓰지 않는다. 로그에 제목, 메모를 남기지 않는다.
"""

from __future__ import annotations

import calendar
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Literal, get_args

from my_planner.clock import period_of
from my_planner.store.repos.conditions import Condition, ConditionsRepo
from my_planner.store.repos.curve import CurveRepo, Ladder

Zoom = Literal["day", "week", "month", "quarter", "year"]
ZOOMS: tuple[str, ...] = get_args(Zoom)
MAX_BUCKETS = 400

DEFAULT_DAYS = 30
DEFAULT_WEEKS = 26
DEFAULT_MONTHS = 24
DEFAULT_QUARTERS = 20

MIN_REASSURANCE_DAYS = 7  # 8.3 / 6.3.5: 그 달 컨디션 기록이 이보다 적으면 비교하지 않는다


class TooManyBuckets(ValueError):
    """묶음이 `MAX_BUCKETS`를 넘는다(자르지 않고 알린다, 6.3.5)."""


@dataclass(frozen=True)
class Bucket:
    name: str  # `period_of(zoom, d)` 형식, day는 날짜
    start: date
    end: date  # 포함


def _month_end(d: date) -> date:
    return date(d.year, d.month, calendar.monthrange(d.year, d.month)[1])


def _bucket_of(zoom: str, d: date) -> Bucket:
    name = period_of(zoom, d)
    if zoom == "day":
        return Bucket(name, d, d)
    if zoom == "week":
        start = d - timedelta(days=d.weekday())
        return Bucket(name, start, start + timedelta(days=6))
    if zoom == "month":
        return Bucket(name, d.replace(day=1), _month_end(d))
    if zoom == "quarter":
        first = (d.month - 1) // 3 * 3 + 1
        return Bucket(name, date(d.year, first, 1), _month_end(date(d.year, first + 2, 1)))
    return Bucket(name, date(d.year, 1, 1), date(d.year, 12, 31))


def _add_months(d: date, months: int) -> date:
    """`d`가 속한 달의 1일에서 `months`달 뒤 1일."""
    index = d.year * 12 + (d.month - 1) + months
    return date(index // 12, index % 12 + 1, 1)


def default_range(zoom: str, today: date, earliest_chapter: date | None) -> tuple[date, date]:
    """확대 단위별 기본 범위(6.3.5). 묶음 경계에 맞춰 현재 묶음까지 준다."""
    if zoom == "day":
        return today - timedelta(days=DEFAULT_DAYS - 1), today
    if zoom == "week":
        this = _bucket_of("week", today)
        return this.start - timedelta(weeks=DEFAULT_WEEKS - 1), this.end
    if zoom == "month":
        return _add_months(today, -(DEFAULT_MONTHS - 1)), _month_end(today)
    if zoom == "quarter":
        this = _bucket_of("quarter", today)
        return _add_months(this.start, -3 * (DEFAULT_QUARTERS - 1)), this.end
    start_year = earliest_chapter.year if earliest_chapter is not None else today.year
    return date(min(start_year, today.year), 1, 1), date(today.year, 12, 31)


def buckets(zoom: str, from_: date, to: date) -> list[Bucket]:
    """`from_`이 든 묶음부터 `to`가 든 묶음까지. `MAX_BUCKETS`를 넘으면 `TooManyBuckets`."""
    out: list[Bucket] = []
    b = _bucket_of(zoom, from_)
    last = _bucket_of(zoom, to).start
    while b.start <= last:
        out.append(b)
        if len(out) > MAX_BUCKETS:
            raise TooManyBuckets
        if b.end == date.max:
            break
        b = _bucket_of(zoom, b.end + timedelta(days=1))
    return out


def _average(scores: list[int]) -> float | None:
    return round(sum(scores) / len(scores), 1) if scores else None


def bucket_conditions(conditions: list[Condition], bs: list[Bucket]) -> list[dict[str, Any]]:
    """묶음마다 컨디션 평균. 기록 있는 날만 평균 내고(빈 날은 0이 아니다, P2) 기록이 없으면 `average`는 None."""
    out = []
    for b in bs:
        scores = [c.score for c in conditions if b.start <= c.date <= b.end]
        out.append({
            "bucket": b.name, "start": b.start.isoformat(), "end": b.end.isoformat(),
            "average": _average(scores), "days_logged": len(scores),
        })
    return out


def reassurance(ladder: list[Ladder], conditions: list[Condition]) -> list[dict[str, Any]]:
    """사다리 `now`가 있는 달마다 그 달 컨디션 평균을 0~10으로 옮겨 나란히 놓는다(8.3).

    기록이 7일 미만이면 `condition_*`과 `gap`은 None. 5년 뒤만 있는 달은 뺀다.
    """
    by_month: dict[str, list[int]] = defaultdict(list)
    for c in conditions:
        by_month[f"{c.date.year}-{c.date.month:02d}"].append(c.score)
    out = []
    for lad in ladder:
        if lad.now is None:
            continue
        scores = by_month.get(lad.period, [])
        row: dict[str, Any] = {
            "period": lad.period, "ladder_now": lad.now, "condition_average": None, "condition_scaled": None,
            "days_logged": len(scores), "gap": None,
        }
        if len(scores) >= MIN_REASSURANCE_DAYS:
            avg = sum(scores) / len(scores)
            scaled = (avg - 1) * 2.5
            row["condition_average"] = round(avg, 1)
            row["condition_scaled"] = round(scaled, 1) + 0.0
            row["gap"] = round(scaled - lad.now, 1) + 0.0
        out.append(row)
    return out


def curve_view(
    curve: CurveRepo, conditions: ConditionsRepo, *, zoom: str, from_: date, to: date, include_sensitive: bool,
    today: date,
) -> dict[str, Any]:
    """`GET /curve` 본문 (6.3.5). `today`는 쓰는 곳이 없어도 호출 모양을 `default_range`와 맞춘다."""
    bs = buckets(zoom, from_, to)
    from_month, to_month = f"{from_.year}-{from_.month:02d}", f"{to.year}-{to.month:02d}"
    chapters = curve.chapters_overlapping(from_month, to_month)
    milestones = curve.milestones_between(from_, to, include_sensitive=include_sensitive)
    ladder = curve.ladder_between(from_month, to_month)
    scores = curve.area_scores_between(period_of("quarter", from_), period_of("quarter", to))

    # 조건은 묶음 전체와 사다리 달 전체를 덮는 범위를 한 번에 읽는다
    lo = min(bs[0].start, from_.replace(day=1))
    hi = max(bs[-1].end, _month_end(to))
    days = conditions.between(lo, hi)

    areas: dict[str, dict[str, int]] = {}
    for s in scores:
        areas.setdefault(s.period, {})[s.area] = s.score
    return {
        "zoom": zoom, "from": from_.isoformat(), "to": to.isoformat(),
        "chapters": [
            {"id": c.id, "title": c.title, "theme": c.theme, "start": c.start_month, "end": c.end_month,
             "sketch": c.sketch, "certainty": c.certainty}
            for c in chapters
        ],
        "milestones": [
            {"id": m.id, "date": m.date_text, "precision": m.precision, "kind": m.kind, "title": m.title,
             "note": m.note, "chapter_id": m.chapter_id, "sensitive": m.sensitive, "certainty": m.certainty}
            for m in milestones
        ],
        "ladder": [{"period": x.period, "now": x.now, "future": x.future, "note": x.note} for x in ladder],
        "areas": [{"period": p, "scores": s} for p, s in sorted(areas.items())],
        "condition": bucket_conditions(days, bs),
        "reassurance": reassurance(ladder, days),
    }
