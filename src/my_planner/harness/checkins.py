"""답할 회차(체크인)의 상태 (SP3-4 스펙 6.4.5)와 오늘의 회차 목록(6.3.1 `runs_today`).

읽기만 한다. API의 `GET` 처리기가 읽기 전용 연결로 만든 저장소를 넘긴다.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Any, Literal

from my_planner.clock import logical_date, period_of
from my_planner.domain import Cadence, LoopKey, RunStatus
from my_planner.harness.context import ask_condition_for, evening_done
from my_planner.harness.stream import CHAPTER_CARD_MAX, MILESTONE_CARD_MAX
from my_planner.loop.schedule import Due, reply_window_end
from my_planner.store.views import (
    chapter_refs,
    curve_draft_live,
    draft_live,
    milestone_refs,
    todo_refs,
)

if TYPE_CHECKING:
    from my_planner.config import Settings
    from my_planner.store.repos.activity import ActivityRepo, ConfirmsRepo
    from my_planner.store.repos.channels import DeliveriesRepo
    from my_planner.store.repos.conditions import ConditionsRepo
    from my_planner.store.repos.conversations import ConversationsRepo
    from my_planner.store.repos.curve import CurveRepo
    from my_planner.store.repos.runs import Run, RunsRepo
    from my_planner.store.repos.tasks import TasksRepo
    from my_planner.tools.actions import ActionRequest

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


# 답장 창이 가장 긴 회차(회고 24시간)보다 넉넉히: 지금 답장 창 안일 수 있는 회차를 찾는 범위
_ANSWER_LOOKBACK = timedelta(days=3)


def _open_checkins(runs: RunsRepo, now: datetime, settings: Settings) -> list[Run]:
    """지금 답장 창 안에 있는 답할 회차(primary), 최근 것부터."""
    found = [
        r for r in runs.between(now - _ANSWER_LOOKBACK, now)
        if _is_checkin(r, runs) and (r.finished_at is None or r.finished_at <= now)
        and now <= reply_until(r, runs=runs, settings=settings)
    ]
    return sorted(found, key=lambda r: (r.scheduled_for, r.id), reverse=True)


def _condition_run(
    day: date, runs: RunsRepo, now: datetime, settings: Settings, activity: ActivityRepo | None
) -> Run | None:
    """그 날짜의 컨디션 버튼을 단 회차: 그 날짜의 저녁 체크인(합쳐 보냈으면 primary), 또는 그 전날 저녁이 없고
    보낼 때 그 날짜 컨디션이 아직 없어 어제를 물은 아침 브리핑(SP1 5.4 판정과 같은 뜻. 기록한 뒤라
    `ask_condition_for`는 더 묻지 않으므로, 보낼 때 기록이 있었는지는 활동 기록으로 본다)."""
    from my_planner.tools.activity import condition_target

    tz, boundary = settings.timezone, settings.day_boundary
    for r in _open_checkins(runs, now, settings):
        for b in (r, *_merged(r, runs)):
            d = logical_date(b.scheduled_for, tz, boundary)
            if b.loop is LoopKey.evening_checkin and d == day:
                return r
            if (
                b.loop is LoopKey.morning_brief and d - timedelta(days=1) == day
                and not evening_done(day, runs=runs, settings=settings)
                and not (
                    activity is not None and r.finished_at is not None
                    and activity.recorded_by(condition_target(day), r.finished_at)
                )
            ):
                return r
    return None


def run_answered_by(
    req: ActionRequest, *, runs: RunsRepo, tasks: TasksRepo, settings: Settings, now: datetime,
    activity: ActivityRepo | None = None, confirms: ConfirmsRepo | None = None,
) -> int | None:
    """즉시 갈래 동작이 답한 회차(6.4.5 "답으로 치는 것"). `apply_action`이 적용한 뒤 부른다. 없으면 None.

    - `record_condition`: 그 날짜에 컨디션 버튼을 단, 지금 답장 창 안의 회차(저녁 체크인의 날짜 등)
    - `confirm_tasks`, `drop_task`: 그 초안을 제안한(`tool_events_log.run_id`), 지금 답장 창 안의 회차
    - 회차 차례의 확인 토큰으로 적용한 동작과 `decline_confirm`: 그 토큰을 만든, 지금 답장 창 안의 회차(10.1 A5의
      확인 카드·버튼도 그 회차에 붙은 버튼이다)
    - `record_ladder_score(period)`: 그 달(없으면 오늘이 든 달)의 월말 회고 회차, `record_area_scores(period)`: 그
      분기(없으면 오늘이 든 분기)의 분기 마지막 회고 회차(11.1, 사다리 버튼과 `ui_ladder_picker`·`ui_area_scores`)
    사용자 동작(`app`, `telegram`)만 센다. 하루 한 번 작업(`scheduler`)은 답이 아니다.
    """
    if req.actor != "user" or req.channel not in ("app", "telegram") or not isinstance(req.args, dict):
        return None
    args = req.args
    token = args.get("confirm_token") if req.action == "decline_confirm" else req.confirm_token
    if isinstance(token, str) and confirms is not None:
        p = confirms.get(token)
        if p is not None and p.origin == "run_turn" and p.run_id is not None:
            got = runs.get(p.run_id)
            primary = (runs.merged_into(got.id) or got) if got is not None else None
            if primary is not None and primary.id in {r.id for r in _open_checkins(runs, now, settings)}:
                return primary.id
    if req.action == "record_condition":
        raw = args.get("date")
        try:
            day = date.fromisoformat(raw) if isinstance(raw, str) else logical_date(
                now, settings.timezone, settings.day_boundary
            )
        except ValueError:
            return None
        run = _condition_run(day, runs, now, settings, activity)
        return run.id if run is not None else None
    if req.action in ("record_ladder_score", "record_area_scores"):
        return _review_step_run(req.action, args.get("period"), runs, now, settings)
    if req.action in ("confirm_tasks", "drop_task"):
        ids = args.get("ids") if req.action == "confirm_tasks" else [args.get("id")]
        open_ids = {r.id for r in _open_checkins(runs, now, settings)}
        for i in ids if isinstance(ids, list) else []:
            if not isinstance(i, int) or isinstance(i, bool):
                continue
            run_id, _ = tasks.proposal_origin(i)
            got = runs.get(run_id) if run_id is not None else None
            if got is None:
                continue
            primary = runs.merged_into(got.id) or got
            if primary.id in open_ids:
                return primary.id
    return None


def _review_step_run(
    action: str, period: object, runs: RunsRepo, now: datetime, settings: Settings
) -> int | None:
    """그 기간의 회고 단계(월말 사다리, 분기 영역 점수)를 묻는, 지금 답장 창 안의 회고 회차(primary)."""
    from my_planner.harness.review_steps import review_in

    cadence = Cadence.month if action == "record_ladder_score" else Cadence.quarter
    if not isinstance(period, str):
        period = period_of(cadence, logical_date(now, settings.timezone, settings.day_boundary))
    for r in _open_checkins(runs, now, settings):
        of = review_in([r, *_merged(r, runs)], settings)
        if of is None or not of.steps:
            continue
        if (cadence is Cadence.month and of.month == period) or (of.steps.quarter and of.quarter == period):
            return r.id
    return None


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
    conditions: ConditionsRepo, now: datetime, settings: Settings, confirms: ConfirmsRepo | None = None,
    activity: ActivityRepo | None = None, curve: CurveRepo | None = None,
) -> dict[str, Any] | None:
    """`GET /checkins/{id}` (6.4.5): 요약에 `text`와 `cards`를 더한다. 답할 회차가 아니면 None."""
    run = runs.get(run_id)
    if run is None or not _is_checkin(run, runs):
        return None
    body = _summary(run, runs=runs, convs=convs, deliveries=deliveries, now=now, settings=settings)
    body["text"] = run.outbound_text or ""
    body["cards"] = checkin_cards(
        run, _merged(run, runs), tasks=tasks, conditions=conditions, runs=runs, settings=settings, now=now,
        confirms=confirms, activity=activity, curve=curve,
    )
    return body


def checkin_cards(
    run: Run, merged: list[Run], *, tasks: TasksRepo, conditions: ConditionsRepo, runs: RunsRepo,
    settings: Settings, now: datetime, confirms: ConfirmsRepo | None = None, activity: ActivityRepo | None = None,
    curve: CurveRepo | None = None,
) -> list[dict[str, Any]]:
    """텔레그램 버튼 재료는 저장되지 않으므로 읽을 때마다 DB에서 다시 만든다(6.4.5 표). 순서는 텔레그램 버튼 줄과 같다.

    - `ui_todo_draft`(`h_draft_<run_id>`): 그 회차(합친 회차 포함)가 제안해 아직 `draft`인 할 일. 없으면 카드도 없다.
    - `ui_confirm`(`h_confirm_<run_id>_<n>`, 10.1 A5): 그 회차의 열린 확인 토큰(`resolved_at IS NULL`, 만료 전)마다.
      토큰 뒤에 대상이 바뀐 토큰(누르면 `stale`)은 카드를 빼고 토큰은 열린 채 둔다(읽기만 한다. 누를 때 닫힌다).
      `n`은 그 회차의 `pending_confirms` 전체를 `created_at` 순으로 센 번호라, 하나가 닫혀도 다른 카드의 id가
      바뀌지 않는다. 회차 차례에서만 생기므로 `/chat` 스트림에는 없다. `props.args`는 `/actions`에 그대로 보낸다.
    - `ui_condition_picker`(`h_cond_<run_id>`): `ask_condition_for`가 고른 날짜. 그 날짜의 컨디션이 있으면 카드가 없다.
    - `ui_milestone_draft`(`h_mdraft_<run_id>`), `ui_chapter_draft`(`h_cdraft_<run_id>`): 그 회차가 `add_milestone`·
      `propose_chapter`로 꺼내 아직 초안이고 만료 전인 것(11.3). `data.milestones`·`data.chapters`(6.4.7). 할 일 초안
      다음, 확인 카드 앞(텔레그램 줄 순서). props 상한(10개, 5개)까지만 싣는다.
    - `ui_ladder_picker`(`h_ladder_<run_id>`, 11.1): 월말 회고면 그 달 사다리. `now`가 없으면 `field: "now"`, 이
      회차를 보낸 뒤 `now`를 기록했고 `future`가 없으면 `"future"`. 회차 전에 이미 `now`가 있었거나(빈 곳 14) 둘 다
      있으면 카드가 없다.
    - `ui_area_scores`(`h_areas_<run_id>`): 분기 마지막 회고이고 그 분기 영역 점수가 아직 없으면. `previous`는 바로
      앞 분기 점수(없으면 빈 객체).
    순서는 컨디션 카드 다음 사다리, 영역 점수(텔레그램에서 차례로 묻는 순서).
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
    if curve is not None:
        run_ids = [run.id, *(m.id for m in merged)]
        ttl = settings.limits.draft_ttl_days
        ms = [
            i for i in tasks.proposed_curve_ids("milestone_proposed", run_ids=run_ids)
            if (m := curve.get_milestone(i)) is not None and curve_draft_live(m.status, m.draft_since, ttl, now)
        ][:MILESTONE_CARD_MAX]
        if ms:
            cards.append({
                "toolCallId": f"h_mdraft_{run.id}", "component": "ui_milestone_draft",
                "props": {"milestone_ids": ms}, "data": {"milestones": milestone_refs(ms, curve)},
            })
        cs = [
            i for i in tasks.proposed_curve_ids("chapter_proposed", run_ids=run_ids)
            if (c := curve.get_chapter(i)) is not None and curve_draft_live(c.status, c.draft_since, ttl, now)
        ][:CHAPTER_CARD_MAX]
        if cs:
            cards.append({
                "toolCallId": f"h_cdraft_{run.id}", "component": "ui_chapter_draft",
                "props": {"chapter_ids": cs}, "data": {"chapters": chapter_refs(cs, curve)},
            })
    # 순환 가져오기를 피해 함수 안에서
    from my_planner.tools.actions import confirm_targets

    for n, p in enumerate(confirms.for_run(run.id) if confirms is not None else [], start=1):
        stale = activity is not None and any(
            activity.changed_after(t, p.created_at) for t in confirm_targets(tasks, p.action, p.args)
        )
        if p.open_at(now) and not stale:
            cards.append({
                "toolCallId": f"h_confirm_{run.id}_{n}",
                "component": "ui_confirm",
                "props": {"summary": p.summary, "confirm_token": p.token, "action": p.action, "args": p.args},
            })
    ask = ask_condition_for(run, merged, conditions=conditions, runs=runs, settings=settings)
    if ask is not None and conditions.get(ask) is None:
        cards.append(
            {"toolCallId": f"h_cond_{run.id}", "component": "ui_condition_picker", "props": {"date": ask.isoformat()}}
        )
    if curve is not None:
        cards.extend(_review_step_cards(run, merged, curve, settings))
    return cards


def _review_step_cards(run: Run, merged: list[Run], curve: CurveRepo, settings: Settings) -> list[dict[str, Any]]:
    from my_planner.harness.review_steps import previous_scores, review_in

    of = review_in([run, *merged], settings)
    if of is None or not of.steps:
        return []
    out: list[dict[str, Any]] = []
    ladder = curve.ladder(of.month)
    field: str | None = None
    if ladder is None or ladder.now is None:
        field = "now"
    elif ladder.future is None and run.finished_at is not None and ladder.recorded_at > run.finished_at:
        field = "future"
    if field is not None:
        out.append({
            "toolCallId": f"h_ladder_{run.id}", "component": "ui_ladder_picker",
            "props": {"period": of.month, "field": field},
        })
    if of.steps.quarter and not curve.area_scores(of.quarter):
        out.append({
            "toolCallId": f"h_areas_{run.id}", "component": "ui_area_scores",
            "props": {"period": of.quarter, "previous": previous_scores(of.quarter, curve)},
        })
    return out
