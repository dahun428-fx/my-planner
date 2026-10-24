"""답할 회차(체크인)의 상태 (SP3-4 스펙 6.4.5)와 오늘의 회차 목록(6.3.1 `runs_today`).

읽기만 한다. API의 `GET` 처리기가 읽기 전용 연결로 만든 저장소를 넘긴다.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any, Literal

from my_planner.clock import logical_date
from my_planner.domain import RunStatus
from my_planner.loop.schedule import Due, reply_window_end

if TYPE_CHECKING:
    from my_planner.config import Settings
    from my_planner.store.repos.channels import DeliveriesRepo
    from my_planner.store.repos.runs import Run, RunsRepo

CheckinState = Literal["pending", "answered", "missed"]


def reply_until(run: Run, *, runs: RunsRepo, settings: Settings) -> datetime:
    """답장 창의 끝. 합쳐 보낸 회차는 묶음의 가장 늦은 끝이다."""
    group = [run, *(m for i in run.merged_run_ids if (m := runs.get(i)) is not None)]
    return max(
        reply_window_end(Due(r.loop, r.scheduled_for, r.cadence), settings.timezone, settings.day_boundary,
                         cfg=settings)
        for r in group
    )


def checkin_state(run: Run, *, runs: RunsRepo, now: datetime, settings: Settings) -> CheckinState | None:
    """보낸(`done`) 회차만 답할 회차다. 건너뛰거나 아직 보내지 않은 회차는 None.

    합쳐진 회차는 primary를 따른다(답은 primary에 적는다). "missed"의 화면 문구는 "지나감"이다.
    """
    if run.status is not RunStatus.done:
        return None
    primary = runs.merged_into(run.id)
    if primary is not None:
        run = primary
    if run.answered_at is not None:
        return "answered"
    return "pending" if now <= reply_until(run, runs=runs, settings=settings) else "missed"


def runs_today(*, runs: RunsRepo, deliveries: DeliveriesRepo, now: datetime, settings: Settings) -> list[dict[str, Any]]:
    """예정 시각의 논리적 날짜가 오늘인 회차. 시각은 저장한 그대로(오프셋 붙은 ISO), API 경계에서 UTC `Z`로 바꾼다."""
    today = logical_date(now, settings.timezone, settings.day_boundary)
    return [
        {
            "id": r.id,
            "loop": r.loop.value,
            "cadence": r.cadence.value,
            "scheduled_for": r.scheduled_for.isoformat(),
            "status": r.status.value,
            "skip_reason": r.skip_reason.value if r.skip_reason else None,
            "delivered_via": deliveries.sent_channels(r.id),
            "checkin_state": checkin_state(r, runs=runs, now=now, settings=settings),
        }
        for r in runs.on_logical_date(today, settings.timezone, settings.day_boundary)
    ]
