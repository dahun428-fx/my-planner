"""인생 히스토리 읽기 모델 (SP8 스펙 8.2): `GET /curve/history` 본문.

확정한 챕터와 사건만 쓴다. 순수 함수에 가깝고 쓰지 않는다. 로그에 제목, 메모를 남기지 않는다.
민감 사건은 `include_sensitive=false`면 제목·메모를 본문에 넣지 않고 챕터마다 개수와 해만 준다(8.5).
"""

from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from fractions import Fraction
from typing import Any

from my_planner.store.repos.conditions import ConditionsRepo
from my_planner.store.repos.curve import Chapter, CurveRepo, Milestone


def round_half_up(x: Fraction, places: str = "0.1") -> Decimal:
    """`Fraction`을 소수 반올림(0.5는 올림). 6.25 → 6.3 (float `round`는 6.2를 준다)."""
    return (Decimal(x.numerator) / Decimal(x.denominator)).quantize(Decimal(places), ROUND_HALF_UP)


def _month_index(month: str) -> int:
    y, m = month.split("-")
    return int(y) * 12 + int(m) - 1


def _end_month(c: Chapter, today: date) -> str:
    """끝나지 않은 챕터는 오늘 달까지."""
    return c.end_month or f"{today.year}-{today.month:02d}"


def _ladder(c: Chapter, recorded: list[tuple[str, int]], today: date) -> dict[str, Any] | None:
    """기억한 값 → 그 기간 월별 사다리 `now` 평균(소수 한 자리) → None."""
    if c.ladder_remembered is not None:
        return {"value": float(c.ladder_remembered), "source": "remembered"}
    end = _end_month(c, today)
    values = [n for period, n in recorded if c.start_month <= period <= end]
    if not values:
        return None
    return {"value": float(round_half_up(Fraction(sum(values), len(values)))), "source": "recorded"}


def _event(m: Milestone) -> dict[str, Any]:
    return {
        "id": m.id, "date": m.date_text, "precision": m.precision, "kind": m.kind,
        "kind_certainty": m.kind_certainty, "title": m.title, "note": m.note, "area": m.area, "origin": m.origin,
        "certainty": m.certainty, "sensitive": m.sensitive,
    }


def _recent_first(ms: list[Milestone]) -> list[Milestone]:
    return sorted(ms, key=lambda m: (m.sort_date, m.id), reverse=True)


def _group(ms: list[Milestone], include_sensitive: bool) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """(보이는 사건, `hidden_sensitive`). 가린 사건은 개수와 해만 남는다."""
    hidden = [m for m in ms if m.sensitive and not include_sensitive]
    shown = [m for m in ms if not (m.sensitive and not include_sensitive)]
    return (
        [_event(m) for m in _recent_first(shown)],
        {"count": len(hidden), "years": sorted({m.sort_date.year for m in hidden})},
    )


def curve_history(
    curve: CurveRepo, conditions: ConditionsRepo, *, today: date, include_sensitive: bool,
) -> dict[str, Any]:
    """`GET /curve/history` (8.2). 챕터는 `start` 최근부터, 사건은 챕터 안에서 `sort_date` 최근부터."""
    chapters = sorted(curve.confirmed_chapters(), key=lambda c: (c.start_month, c.id), reverse=True)
    milestones = curve.confirmed_milestones()
    known = {c.id for c in chapters}
    recorded = [(x.period, x.now) for x in curve.ladder_between("0000-01", "9999-12") if x.now is not None]

    out_chapters: list[dict[str, Any]] = []
    visible: list[dict[str, Any]] = []
    for c in chapters:
        events, hidden = _group([m for m in milestones if m.chapter_id == c.id], include_sensitive)
        visible += events
        out_chapters.append({
            "id": c.id, "title": c.title, "theme": c.theme, "start": c.start_month, "end": c.end_month,
            "sketch": c.sketch, "certainty": c.certainty, "ladder": _ladder(c, recorded, today),
            "events": events, "hidden_sensitive": hidden,
        })
    loose, loose_hidden = _group([m for m in milestones if m.chapter_id not in known], include_sensitive)
    visible += loose

    # 가장 높았던 챕터: 같으면 최근 챕터(목록이 최근부터라 처음 만난 것)
    highest = None
    for ch in out_chapters:
        if ch["ladder"] is not None and (highest is None or ch["ladder"]["value"] > highest["ladder"]):
            highest = {"chapter_id": ch["id"], "title": ch["title"], "ladder": ch["ladder"]["value"]}
    longest = None
    best = -1
    for c in chapters:
        months = _month_index(_end_month(c, today)) - _month_index(c.start_month)
        if months > best:
            best = months
            longest = {"chapter_id": c.id, "title": c.title, "years": int(round_half_up(Fraction(months, 12), "1"))}
    turning = [e for e in visible if e["kind"] == "turning_point"]
    firsts = [int(e["date"][:4]) for e in visible] + [int(c.start_month[:4]) for c in chapters]
    record_years = [d.year for d in (conditions.earliest(),) if d is not None]
    if (period := curve.earliest_ladder_period()) is not None:
        record_years.append(int(period[:4]))
    return {
        "since_year": min(firsts) if firsts else None,
        "chapters": out_chapters,
        "unassigned": {"events": loose, "hidden_sensitive": loose_hidden},
        "summary": {
            "chapters": len(chapters),
            "events": len(visible),
            "highest": highest,
            "turning_points": {"count": len(turning), "years": sorted({int(e["date"][:4]) for e in turning})},
            "longest": longest,
            "records_since": min(record_years) if record_years else None,
        },
    }
