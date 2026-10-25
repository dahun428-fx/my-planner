"""깨어났을 때 각 회차의 처리 결정 (스펙 5.4 따라잡기 규칙). 순수 함수.

티켓 05는 R4(한계 안이면 늦게라도 실행)와 R5(한계 밖이면 `skipped(late)`)를, 08은 합치기를 둔다.
09는 R1(복귀 인사), 넘겨 받은 회고, 하루 3회 상한(`proactive_today`), 시계 이상을 둔다.
10은 R2(멈춤: 멈춤 끝 전에 예정된 회차는 `paused`, 멈춤 중에는 R1 없음, 공백은 멈춤 끝부터 센다),
R3(하루 두뇌 호출 상한, `daily_cap`)과 사용 한도(`limited_until`까지 `rate_limit`)를 둔다.
R3과 사용 한도 중에는 두뇌를 부를 수 없으니 복귀 인사도 만들지 않는다.
11은 계획 모드(`plan_open`: 한계 안의 회차는 판정하지 않고 pending으로 두고, 한계 밖이면 `late`)를 둔다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time, timedelta, tzinfo
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from my_planner.clock import logical_date
from my_planner.domain import LoopKey, SkipReason
from my_planner.loop.schedule import Due, Overrides, due_between, limit_for

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
    overrides: Overrides | None = None,
) -> Decision:
    """`overrides`: 바꾼 체크인 시각(SP9 8장). R1이 그날 아침 브리핑 시각을 볼 때 쓴다."""
    # 시계가 뒤로 갔으면(last_seen_at이 미래) 공백을 0으로 본다
    clock_backwards = last_seen_at is not None and last_seen_at > now
    gap = timedelta(0) if last_seen_at is None or clock_backwards else now - last_seen_at
    # 아직 예정 시각이 오지 않은 회차(시계가 뒤로 갔을 때 생긴다)는 판정하지 않고 그대로 둔다
    pending = [d for d in pending if d.scheduled_for <= now]
    if carried_review is not None and carried_review.scheduled_for > now:
        carried_review = None
    # R2: 멈춤 기간 안에 예정된 회차는 skipped(paused)
    paused: list[tuple[Due, SkipReason]] = []
    if paused_until is not None:
        paused = [(d, SkipReason.paused) for d in pending if d.scheduled_for < paused_until]
        pending = [d for d in pending if d.scheduled_for >= paused_until]
    paused_now = paused_until is not None and now < paused_until
    # R3(하루 두뇌 호출 상한)과 사용 한도(`limited_until`까지): 두뇌를 부를 수 없으니 복귀 인사(R1)도 만들지 않는다
    blocked_reason = None
    if brain_calls_today >= cfg.limits.daily_brain_calls:
        blocked_reason = SkipReason.daily_cap
    elif limited_until is not None and now < limited_until:
        blocked_reason = SkipReason.rate_limit
    if blocked_reason is not None:
        blocked = [(d, blocked_reason) for d in sorted(pending, key=lambda d: d.scheduled_for)]
        return Decision(primary=None, skipped=[*paused, *blocked], clock_backwards=clock_backwards)
    if paused_until is not None and last_seen_at is not None and last_seen_at < paused_until <= now:
        gap = now - paused_until  # 멈춤 동안 쉰 것은 공백이 아니다. 멈춤이 끝난 뒤부터 센다
    if gap >= RETURN_GAP and not paused_now:  # R1: 멈춤 중이면 복귀 인사를 만들지 않는다
        # 이미 넘겨 받은 회고가 있으면 그것도 공백의 회차로 다시 판정한다
        gap_runs = [*pending, *([carried_review] if carried_review else [])]
        d = _return(now, last_seen_at, gap_runs, cfg, tz, boundary, overrides)
        d.skipped = [*paused, *d.skipped]
        return d
    d = _regular(now, pending, carried_review, proactive_today, plan_open, cfg, tz, boundary)
    d.skipped = [*paused, *d.skipped]
    d.clock_backwards = clock_backwards
    return d


def _regular(
    now: datetime,
    pending: list[Due],
    carried_review: Due | None,
    proactive_today: int,
    plan_open: bool,
    cfg: Settings,
    tz: str | tzinfo,
    boundary: time,
) -> Decision:
    """R4·R5, 계획 모드 대기, 합치기, 넘겨 받은 회고, 하루 3회 상한."""
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
    if plan_open:
        # 계획 대화가 닫힐 때까지 한계 안의 회차(넘겨 받은 회고 포함)는 그대로 둔다. 한계 밖은 위에서 late
        return Decision(primary=None, skipped=skipped)
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


def _return(
    now: datetime,
    last_seen_at: datetime | None,
    pending: list[Due],
    cfg: Settings,
    tz: str | tzinfo,
    boundary: time,
    overrides: Overrides | None = None,
) -> Decision:
    """R1: 공백 동안의 회차는 `skipped(merged_into_return)`, 복귀 인사 하나를 만든다.

    회고는 한계(+3일) 안이면 넘겨 받는다(`carry_review`, 가장 최근 것 하나).
    공백 전부터 기다리던 회차(`scheduled_for <= last_seen_at`, 예: 상한으로 대기, 넘겨 받은 회고)가
    한계를 넘었으면 공백의 회차가 아니라 `late`다.
    """
    gap = sorted(pending, key=lambda d: d.scheduled_for)
    in_limit = {d: now <= limit_for(d, cfg, tz, boundary) for d in gap}
    reviews = [d for d in gap if d.loop is LoopKey.review and in_limit[d]]
    carry = reviews[-1] if reviews else None
    skipped: list[tuple[Due, SkipReason]] = []
    for due in gap:
        if due == carry:
            continue
        waited = last_seen_at is not None and due.scheduled_for <= last_seen_at
        reason = SkipReason.late if waited and not in_limit[due] else SkipReason.merged_into_return
        skipped.append((due, reason))
    # 복귀 인사가 오늘(논리적 날짜) 아침 브리핑 예정 시각 전에 나가면, 그 아침 브리핑도 건너뛴다
    zone = ZoneInfo(tz) if isinstance(tz, str) else tz
    day_end = datetime.combine(logical_date(now, tz, boundary) + timedelta(days=1), boundary, zone)
    for morning in due_between(now, day_end, cfg, tz, {LoopKey.morning_brief}, overrides):
        skipped.append((morning, SkipReason.merged_into_return))
    return Decision(primary=Due(LoopKey.return_, now), skipped=skipped, create_return=True, carry_review=carry)
