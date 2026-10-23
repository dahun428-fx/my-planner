"""깨어났을 때 각 회차의 처리 결정 (스펙 5.4 따라잡기 규칙). 순수 함수.

티켓 05는 R4(한계 안이면 늦게라도 실행)와 R5(한계 밖이면 `skipped(late)`)만 둔다.
R1(복귀 인사)은 09, R2·R3과 `limited_until`은 10, 합치기와 하루 3회 상한은 08, 계획 모드는 11이 채운다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time, tzinfo
from typing import TYPE_CHECKING

from my_planner.domain import SkipReason
from my_planner.loop.schedule import Due, limit_for

if TYPE_CHECKING:
    from my_planner.config import Settings


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
    # 합치기(08) 전까지는 가장 이른 회차 하나만 실행한다. 나머지는 pending으로 남아 다음 tick에서 다시 판정된다.
    return Decision(primary=runnable[0] if runnable else None, skipped=skipped)
