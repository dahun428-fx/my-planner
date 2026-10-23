"""깨어났을 때 각 회차의 처리 결정 (스펙 5.4 따라잡기 규칙). 순수 함수.

티켓 05는 R4(한계 안이면 늦게라도 실행)와 R5(한계 밖이면 `skipped(late)`)를, 08은 합치기를 둔다.
09는 R1(복귀 인사), 넘겨 받은 회고, 하루 3회 상한(`proactive_today`), 시계 이상을 둔다.
R2·R3과 `limited_until`은 10, 계획 모드는 11이 채운다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time, timedelta, tzinfo
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from my_planner.clock import logical_date
from my_planner.domain import LoopKey, SkipReason
from my_planner.loop.schedule import Due, due_between, limit_for

if TYPE_CHECKING:
    from my_planner.config import Settings


# 합치기 우선순위(스펙 5.4 "합치기"). 작을수록 primary가 된다. `return_`은 티켓 09가 만든다.
MERGE_PRIORITY: dict[LoopKey, int] = {
    LoopKey.return_: 0,
    LoopKey.evening_checkin: 1,
    LoopKey.morning_brief: 2,
    LoopKey.review: 3,
}


# R1: 마지막 tick에서 이만큼 지났으면 복귀 인사 하나만 보낸다.
RETURN_GAP = timedelta(hours=24)


# 넘겨 받은 회고를 합칠 수 있는 정규 연락
REGULAR_CONTACTS = frozenset({LoopKey.morning_brief, LoopKey.evening_checkin})


def merge_order(loop: LoopKey) -> int:
    return MERGE_PRIORITY[loop]


@dataclass
class Decision:
    primary: Due | None
    merged: list[Due] = field(default_factory=list)
    skipped: list[tuple[Due, SkipReason]] = field(default_factory=list)
    create_return: bool = False
    carry_review: Due | None = None
    clock_backwards: bool = False  # last_seen_at이 지금보다 뒤다. 경고 로그는 러너가 남긴다


def decide(
    now: datetime,
    last_seen_at: datetime | None,
    pending: list[Due],
    *,
    carried_review: Due | None = None,
    paused_until: datetime | None = None,
    limited_until: datetime | None = None,
    brain_calls_today: int = 0,
    proactive_today: int = 0,
    plan_open: bool = False,
    cfg: Settings,
    tz: str | tzinfo,
    boundary: time,
) -> Decision:
    # 시계가 뒤로 갔으면(last_seen_at이 미래) 공백을 0으로 본다
    clock_backwards = last_seen_at is not None and last_seen_at > now
    gap = timedelta(0) if last_seen_at is None or clock_backwards else now - last_seen_at
    if gap >= RETURN_GAP:  # R1
        # 이미 넘겨 받은 회고가 있으면 그것도 공백의 회차로 다시 판정한다
        return _return(now, [*pending, *([carried_review] if carried_review else [])], cfg, tz, boundary)
    d = _regular(now, pending, carried_review, proactive_today, cfg, tz, boundary)
    d.clock_backwards = clock_backwards
    return d


def _regular(
    now: datetime,
    pending: list[Due],
    carried_review: Due | None,
    proactive_today: int,
    cfg: Settings,
    tz: str | tzinfo,
    boundary: time,
) -> Decision:
    """R4·R5, 합치기, 넘겨 받은 회고, 하루 3회 상한."""
    runnable: list[Due] = []
    skipped: list[tuple[Due, SkipReason]] = []
    if carried_review is not None and now > limit_for(carried_review, cfg, tz, boundary):
        skipped.append((carried_review, SkipReason.late))  # 다음 정규 연락 없이 +3일이 지났다
        carried_review = None
    for due in sorted(pending, key=lambda d: d.scheduled_for):
        if now <= limit_for(due, cfg, tz, boundary):  # R4
            runnable.append(due)
        else:  # R5
            skipped.append((due, SkipReason.late))
    # 합치기: 실행할 회차가 둘 이상이면 우선순위가 가장 높은 하나가 primary, 나머지는 merged(같은 순위면 이른 것부터).
    runnable.sort(key=lambda d: merge_order(d.loop))
    if not runnable or proactive_today >= cfg.limits.daily_proactive_messages:
        # 하루 3회 상한: 4번째가 될 회차는 보내지도 건너뛰지도 않고 pending으로 기다린다
        return Decision(primary=None, skipped=skipped)
    primary, merged = runnable[0], runnable[1:]
    # 넘겨 받은 회고는 혼자 실행하지 않고, 다음 정규 연락(아침 브리핑 또는 저녁 체크인)에 합친다
    if carried_review is not None and primary.loop in REGULAR_CONTACTS:
        merged.append(carried_review)
    return Decision(primary=primary, merged=merged, skipped=skipped)


def _return(now: datetime, pending: list[Due], cfg: Settings, tz: str | tzinfo, boundary: time) -> Decision:
    """R1: 공백 동안의 회차는 `skipped(merged_into_return)`, 복귀 인사 하나를 만든다.

    회고는 한계(+3일) 안이면 넘겨 받는다(`carry_review`, 가장 최근 것 하나).
    """
    gap = sorted(pending, key=lambda d: d.scheduled_for)
    reviews = [d for d in gap if d.loop is LoopKey.review and now <= limit_for(d, cfg, tz, boundary)]
    carry = reviews[-1] if reviews else None
    skipped = [(due, SkipReason.merged_into_return) for due in gap if due != carry]
    # 복귀 인사가 오늘(논리적 날짜) 아침 브리핑 예정 시각 전에 나가면, 그 아침 브리핑도 건너뛴다
    zone = ZoneInfo(tz) if isinstance(tz, str) else tz
    day_end = datetime.combine(logical_date(now, tz, boundary) + timedelta(days=1), boundary, zone)
    for morning in due_between(now, day_end, cfg, tz, {LoopKey.morning_brief}):
        skipped.append((morning, SkipReason.merged_into_return))
    return Decision(primary=Due(LoopKey.return_, now), skipped=skipped, create_return=True, carry_review=carry)
