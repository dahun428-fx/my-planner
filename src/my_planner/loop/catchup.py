"""깨어났을 때 각 회차의 처리 결정 (스펙 5.4 따라잡기 규칙). 순수 함수.

티켓 05는 R4(한계 안이면 늦게라도 실행)와 R5(한계 밖이면 `skipped(late)`)를, 08은 합치기를 둔다.
R1(복귀 인사)은 09, R2·R3과 `limited_until`은 10, 계획 모드는 11이 채운다.
하루 3회 상한(`proactive_today`)은 아직 판정에 쓰지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time, tzinfo
from typing import TYPE_CHECKING

from my_planner.domain import LoopKey, SkipReason
from my_planner.loop.schedule import Due, limit_for

if TYPE_CHECKING:
    from my_planner.config import Settings


# 합치기 우선순위(스펙 5.4 "합치기"). 작을수록 primary가 된다. `return_`은 티켓 09가 만든다.
MERGE_PRIORITY: dict[LoopKey, int] = {
    LoopKey.return_: 0,
    LoopKey.evening_checkin: 1,
    LoopKey.morning_brief: 2,
    LoopKey.review: 3,
}


def merge_order(loop: LoopKey) -> int:
    return MERGE_PRIORITY[loop]


@dataclass
class Decision:
    primary: Due | None
    merged: list[Due] = field(default_factory=list)
    skipped: list[tuple[Due, SkipReason]] = field(default_factory=list)
    create_return: bool = False
    carry_review: Due | None = None


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
    runnable: list[Due] = []
    skipped: list[tuple[Due, SkipReason]] = []
    for due in sorted(pending, key=lambda d: d.scheduled_for):
        if now <= limit_for(due, cfg, tz, boundary):  # R4
            runnable.append(due)
        else:  # R5
            skipped.append((due, SkipReason.late))
    # 합치기: 실행할 회차가 둘 이상이면 우선순위가 가장 높은 하나가 primary, 나머지는 merged(같은 순위면 이른 것부터).
    runnable.sort(key=lambda d: merge_order(d.loop))
    if not runnable:
        return Decision(primary=None, skipped=skipped)
    return Decision(primary=runnable[0], merged=runnable[1:], skipped=skipped)
