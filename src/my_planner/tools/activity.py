"""활동 기록 (SP3-4 스펙 5.2, 6.4.4). 변경 도구가 데이터 변경과 같은 트랜잭션 안에서 부른다.

대상 문자열(5.2): `task:12`, `condition:2026-10-24`, `priorities:week:2026-W43`, `ladder:2026-10`, `areas:2026-Q4`,
`milestone:7`, `chapter:3`, `card:2`. `summary`는 확인 문구 한 줄이고 메시지 본문(메모 포함)은 넣지 않는다.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, Any

from my_planner.domain import ActivityChannel, Actor, Risk, RunContext

if TYPE_CHECKING:
    from my_planner.store.repos.activity import ActivityRepo


def activity_origin(ctx: RunContext) -> tuple[Actor, ActivityChannel]:
    """(행위자, 활동 통로). 통로는 `activity_channel`이 있으면 그것(회차 첫 호출, 하루 한 번 작업), 없으면 대화 통로."""
    return ctx.actor, ctx.activity_channel if ctx.activity_channel is not None else ctx.channel


def task_target(task_id: int) -> str:
    return f"task:{task_id}"


def condition_target(d: date) -> str:
    return f"condition:{d.isoformat()}"


def priorities_target(cadence: str, period: str) -> str:
    return f"priorities:{cadence}:{period}"


def record_activity(
    repo: ActivityRepo | None,
    ctx: RunContext,
    *,
    kind: str,
    target: str | None,
    summary: str,
    risk: Risk | None = None,
    undo: dict[str, Any] | None,
) -> int | None:
    """활동 한 행을 쓰고 `ctx.activity_ids`(되돌릴 수 있으면 `ctx.undo_ids`도)에 더한다. 저장소가 없으면 None.

    `risk`를 주지 않으면 `ctx.risk`. `risk = confirm`으로 적용한 변경은 되돌릴 수 없다(6.4.2).
    """
    if repo is None:
        return None
    actor, channel = activity_origin(ctx)
    risk = risk if risk is not None else ctx.risk
    aid = repo.add(
        actor=actor, channel=channel, kind=kind, target=target, summary=summary, risk=risk, undo=undo,
        conversation_id=ctx.conversation_id, run_id=ctx.run_id, inbound_id=ctx.inbound_id,
    )
    ctx.activity_ids.append(aid)
    if risk == "low" and undo is not None:
        ctx.undo_ids.append(aid)
    return aid
