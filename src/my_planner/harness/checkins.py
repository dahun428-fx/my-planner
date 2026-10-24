"""답할 회차(체크인)의 상태 (SP3-4 스펙 6.4.5)와 오늘의 회차 목록(6.3.1 `runs_today`).

읽기만 한다. API의 `GET` 처리기가 읽기 전용 연결로 만든 저장소를 넘긴다.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING, Any, Literal

from my_planner.clock import logical_date
from my_planner.domain import RunStatus
from my_planner.harness.context import ask_condition_for
from my_planner.loop.schedule import Due, reply_window_end
from my_planner.store.views import draft_live, todo_refs

if TYPE_CHECKING:
    from my_planner.config import Settings
    from my_planner.store.repos.channels import DeliveriesRepo
    from my_planner.store.repos.conditions import ConditionsRepo
    from my_planner.store.repos.conversations import ConversationsRepo
    from my_planner.store.repos.runs import Run, RunsRepo
    from my_planner.store.repos.tasks import TasksRepo

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


def _merged(run: Run, runs: RunsRepo) -> list[Run]:
    return [m for i in run.merged_run_ids if (m := runs.get(i)) is not None]


def _is_checkin(run: Run, runs: RunsRepo) -> bool:
    """보낸(`done`) 회차이고 다른 회차에 합쳐진 것이 아니다(합친 회차는 primary 하나로만 나온다)."""
    return run.status is RunStatus.done and runs.merged_into(run.id) is None


def _summary(
    run: Run, *, runs: RunsRepo, convs: ConversationsRepo, deliveries: DeliveriesRepo, now: datetime,
    settings: Settings,
) -> dict[str, Any]:
    by_channel: dict[str, int | None] = {"app": None, "telegram": None}
    for c in convs.for_run(run.id):  # id 순이라 통로마다 가장 나중 것이 남는다
        by_channel[c.channel] = c.id
    state = checkin_state(run, runs=runs, now=now, settings=settings)
    return {
        "id": run.id,
        "loop": run.loop.value,
        "cadence": run.cadence.value,
        "scheduled_for": run.scheduled_for.isoformat(),
        "sent_at": run.finished_at.isoformat() if run.finished_at else None,
        "delivered_via": deliveries.sent_channels(run.id),
        "state": state,
        "answered_via": run.answered_via,
        "answered_at": run.answered_at.isoformat() if run.answered_at else None,
        "reply_until": reply_until(run, runs=runs, settings=settings).isoformat(),
        "conversation_ids": {"app": by_channel["app"], "telegram": by_channel["telegram"]},
    }


def checkin_summaries(
    *, runs: RunsRepo, convs: ConversationsRepo, deliveries: DeliveriesRepo, d: date, now: datetime,
    settings: Settings,
) -> list[dict[str, Any]]:
    """`GET /checkins?date=` (6.4.5): 예정 시각의 논리적 날짜가 `d`인, 보낸 회차의 요약. 건너뛴 회차와 합쳐진 회차는 없다."""
    return [
        _summary(r, runs=runs, convs=convs, deliveries=deliveries, now=now, settings=settings)
        for r in runs.on_logical_date(d, settings.timezone, settings.day_boundary)
        if _is_checkin(r, runs)
    ]


def checkin_detail(
    run_id: int, *, runs: RunsRepo, convs: ConversationsRepo, deliveries: DeliveriesRepo, tasks: TasksRepo,
    conditions: ConditionsRepo, now: datetime, settings: Settings,
) -> dict[str, Any] | None:
    """`GET /checkins/{id}` (6.4.5): 요약에 `text`와 `cards`를 더한다. 답할 회차가 아니면 None."""
    run = runs.get(run_id)
    if run is None or not _is_checkin(run, runs):
        return None
    body = _summary(run, runs=runs, convs=convs, deliveries=deliveries, now=now, settings=settings)
    body["text"] = run.outbound_text or ""
    body["cards"] = checkin_cards(
        run, _merged(run, runs), tasks=tasks, conditions=conditions, runs=runs, settings=settings, now=now
    )
    return body


def checkin_cards(
    run: Run, merged: list[Run], *, tasks: TasksRepo, conditions: ConditionsRepo, runs: RunsRepo,
    settings: Settings, now: datetime,
) -> list[dict[str, Any]]:
    """텔레그램 버튼 재료는 저장되지 않으므로 읽을 때마다 DB에서 다시 만든다(6.4.5 표). 순서는 텔레그램 버튼 줄과 같다.

    - `ui_todo_draft`(`h_draft_<run_id>`): 그 회차(합친 회차 포함)가 제안해 아직 `draft`인 할 일. 없으면 카드도 없다.
    - `ui_condition_picker`(`h_cond_<run_id>`): `ask_condition_for`가 고른 날짜. 그 날짜의 컨디션이 있으면 카드가 없다.
    사건·챕터 초안, 사다리·영역 점수, `ui_confirm` 카드는 그 단계를 만드는 티켓이 더한다.
    """
    cards: list[dict[str, Any]] = []
    today = logical_date(now, settings.timezone, settings.day_boundary)
    ids = [
        i
        for i in tasks.proposed_task_ids_for_runs([run.id, *(m.id for m in merged)])
        if (t := tasks.get(i)) is not None and draft_live(t, tasks, settings.limits.draft_ttl_days, now)
    ]
    if ids:
        cards.append(
            {
                "toolCallId": f"h_draft_{run.id}",
                "component": "ui_todo_draft",
                "props": {"task_ids": ids},
                "data": {"todos": todo_refs(ids, tasks, today)},
            }
        )
    ask = ask_condition_for(run, merged, conditions=conditions, runs=runs, settings=settings)
    if ask is not None and conditions.get(ask) is None:
        cards.append(
            {"toolCallId": f"h_cond_{run.id}", "component": "ui_condition_picker", "props": {"date": ask.isoformat()}}
        )
    return cards
