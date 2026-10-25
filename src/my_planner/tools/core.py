"""도구 함수 (스펙 5.5). 메서드는 `(ctx, **inputs) -> dict`이고 잘못된 입력은 `{"error": "…"}`로 돌려준다.

변경 도구는 데이터 변경, `tool_events_log`, `activity`(SP3-4 스펙 5.2)를 같은 트랜잭션에서 쓰고, `ctx.events`에
이벤트를 쌓고, `tasks.md`를 다시 만든다. 로그에는 제목이나 인자를 남기지 않는다.

회차 차례(`ctx.run_turn`, SP3-4 10.1 A1)에서는 `drop_task`, `set_priorities`, `scheduled_at`을 바꾸는 `update_task`,
시각 있는 할 일의 `move_task`가 입력을 검증한 뒤 아무것도 바꾸지 않고 확인 토큰만 만든다(`_request_confirm`, A2).
사용자 메시지에 답하는 차례는 SP1 그대로 바로 적용한다(A3). `add_task`는 언제나 바로(A4).
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from datetime import date, datetime, time, timedelta, tzinfo
from pathlib import Path
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from my_planner.clock import Clock, from_iso, local, logical_date, period_of, to_iso
from my_planner.curve.model import ZOOMS, TooManyBuckets, curve_view, default_range
from my_planner.domain import Area, Cadence, RunContext, TaskStatus, ToolEvent
from my_planner.status.snapshot import status_snapshot
from my_planner.status.xp import (
    LABEL_CONDITION,
    LABEL_LADDER,
    LABEL_TASK,
    LABEL_WHEEL,
    SECRETARY_DAILY_MAX,
    SECRETARY_REASON_MAX,
    XP_CONDITION,
    XP_LADDER,
    XP_SECRETARY,
    XP_WHEEL,
    task_xp,
    title_name,
)
from my_planner.store.db import transaction
from my_planner.store.exports import SENSITIVE_MASK, export_curve, export_tasks
from my_planner.store.repos.cards import Card, CardsRepo
from my_planner.store.repos.conditions import Condition
from my_planner.store.repos.curve import AreaScore, CurveRepo, Ladder, date_precision
from my_planner.store.repos.habits import HabitsRepo
from my_planner.store.repos.status import StatusRepo
from my_planner.store.repos.tasks import Task, TasksRepo
from my_planner.store.transcripts import TranscriptStore
from my_planner.store.views import habits_view, moment_counts, moment_dict, todo_refs
from my_planner.timefmt import api_time
from my_planner.tools._base import _err, _tool
from my_planner.tools.activity import (
    CARDS_ORDER_TARGET,
    SUPERSEDED,
    areas_target,
    card_target,
    chapter_target,
    condition_target,
    ladder_target,
    many_target,
    milestone_target,
    priorities_target,
    record_activity,
    register_undo,
    task_target,
    tasks_target,
)
from my_planner.tools.checkin_times import CheckinTimeTools
from my_planner.tools.confirmations import (
    area_scores_line,
    card_label,
    chapter_confirmed_line,
    condition_summary,
    confirm_button_drop,
    confirm_button_move,
    confirm_button_priorities,
    confirm_button_schedule,
    confirm_drop_summary,
    confirm_move_summary,
    confirm_priorities_summary,
    confirm_requested_summary,
    confirm_schedule_summary,
    confirmation_line,
    drafts_expired_summary,
    dropped_line,
    ladder_line,
    milestone_confirmed_line,
    period_label,
    titles_summary,
    xp_granted_line,
)
from my_planner.tools.habits import HabitTools
from my_planner.tools.moments import MomentTools
from my_planner.tools.ui import PINNABLE_COMPONENTS, validate_props

if TYPE_CHECKING:
    from my_planner.config import Settings
    from my_planner.store.repos.activity import ConfirmsRepo
    from my_planner.store.repos.moments import MomentsRepo
    from my_planner.store.repos.runs import RunsRepo
    from my_planner.store.repos.state import StateRepo

log = logging.getLogger(__name__)

TITLE_MAX = 200
LIST_LIMIT_MAX = 50
LIST_LIMIT_DEFAULT = 20
TRANSCRIPT_MAX_DAYS = 7
PRIORITY_MAX = 3
BRAIN_MOMENTS_DAYS = 7  # 두뇌 `get_status`의 이룬 순간(SP8 10.3)
SCORE_MIN, SCORE_MAX = 1, 5  # 컨디션 점수
_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")  # fromisoformat은 20261023, 2026-W43-5도 받는다
LADDER_MIN, LADDER_MAX = 0, 10  # 사다리(5.4)
AREA_SCORE_MIN, AREA_SCORE_MAX = 1, 10  # 영역 점수(5.4)
RECOVERY_QUEST_MAX = 80
MILESTONE_KINDS = ("high", "low", "turning_point")  # 5.4 `curve_milestones.kind`
CURVE_TITLE_MAX = 100  # 사건·챕터 제목(5.4 CHECK)
_MONTH = re.compile(r"\d{4}-(0[1-9]|1[0-2])")
TITLE_KINDS = frozenset({"high", "turning_point"})  # 칭호를 주는 사건 종류(9.4). 저점에는 주지 않는다
PROPOSE_MAX = 10  # 한 번에 제안하는 초안 수. 버튼 줄이 너무 길어지지 않게
_NEW_FIELDS = {"title", "areas", "planned_for", "scheduled_at", "parent_id", "note"}
# 확인 저장소는 있는데 답장 창을 알 수 없을 때(조립하지 않은 시험)의 회차 토큰 만료. `/actions` 토큰과 같다
RUN_CONFIRM_FALLBACK_TTL = timedelta(minutes=10)
PERIOD_EXAMPLE = {
    Cadence.day: "2026-10-23",
    Cadence.week: "2026-W43",
    Cadence.month: "2026-10",
    Cadence.quarter: "2026-Q4",
    Cadence.year: "2026",
}


class Tools(MomentTools, HabitTools, CheckinTimeTools):
    def __init__(
        self,
        *,
        tasks: TasksRepo,
        transcripts: TranscriptStore,
        export_path: Path,
        clock: Clock,
        tz: str | tzinfo,
        boundary: time,
        conditions: Any = None,
        activity: Any = None,
        cards: CardsRepo | None = None,
        confirms: ConfirmsRepo | None = None,
        reply_until: Callable[[int], datetime] | None = None,
        curve: CurveRepo | None = None,
        status: StatusRepo | None = None,
        review_date_for: Callable[[RunContext], date | None] | None = None,
        curve_export_path: Path | None = None,
        habits: HabitsRepo | None = None,
        moments: MomentsRepo | None = None,
        state: StateRepo | None = None,
        settings: Settings | None = None,
        runs: RunsRepo | None = None,
    ) -> None:
        self.tasks = tasks
        self.transcripts = transcripts
        self.export_path = Path(export_path)
        self.clock = clock
        self.tz = ZoneInfo(tz) if isinstance(tz, str) else tz
        self.boundary = boundary
        self.conditions = conditions
        self.activity = activity  # `ActivityRepo`. None이면 활동을 남기지 않는다(SP1 시험)
        self.cards = cards  # `CardsRepo`(고정 카드, SP3-4 5.3). None이면 카드 도구가 거절한다
        # `ConfirmsRepo`(SP3-4 10.1). None이면 회차 차례에서도 SP1처럼 바로 적용한다(SP1 시험)
        self.confirms = confirms
        self.reply_until = reply_until  # 회차 id → 그 회차 답장 창 끝(합친 회차는 가장 늦은 끝). 토큰 만료
        # 인생 곡선(SP3-4 5.4, 10장). None이면 곡선 도구가 거절한다
        self.curve = curve
        self.status = status  # 칭호(`status_titles`, 9.4)
        # 지금 대화가 회고 회차의 대화면 그 회고 `scheduled_for`의 논리적 날짜(10장 "기간 기본값"), 아니면 None
        self.review_date_for = review_date_for
        self.curve_export_path = (
            Path(curve_export_path) if curve_export_path is not None
            else self.export_path.parent.parent / "curve" / "chapters.md"  # data/exports/tasks.md → data/curve/
        )
        self.habits = habits  # 습관(SP7 5.4). None이면 습관 도구가 거절한다
        self.habits_export_path = self.export_path.parent / "habits.md"  # data/exports/habits.md (5.8)
        self.moments = moments  # 이룬 순간(SP8 6.1). None이면 `save_moments`가 거절한다. 내보내기는 없다(6.4)
        # 체크인 시간 바꾸기(SP9 8장): 바꾼 칸(`app_state`), config 기본값, 오늘 회차. 하나라도 None이면 거절한다
        self.state = state
        self.settings = settings
        self.runs = runs

    # --- 공통 ---

    def today(self) -> date:
        return logical_date(self.clock.now(), self.tz, self.boundary)

    def _parse_date(self, v: Any, name: str) -> date | None | str:
        """날짜 문자열 → date. None은 None. 잘못되면 오류 문구(str)."""
        if v is None:
            return None
        if not isinstance(v, str):
            return f"{name}은(는) YYYY-MM-DD 형식으로 알려 주세요."
        try:
            return date.fromisoformat(v)
        except ValueError:
            return f"{name}은(는) YYYY-MM-DD 형식으로 알려 주세요."

    def _parse_dt(self, v: Any) -> datetime | None | str:
        if v is None:
            return None
        if not isinstance(v, str):
            return "scheduled_at은 날짜와 시각(예: 2026-10-25T14:00)으로 알려 주세요."
        try:
            dt = datetime.fromisoformat(v)
        except ValueError:
            return "scheduled_at은 날짜와 시각(예: 2026-10-25T14:00)으로 알려 주세요."
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=self.tz)
        return dt

    def _check_title(self, v: Any) -> str | None:
        if not isinstance(v, str) or not v.strip():
            return "제목이 비어 있어요."
        if len(v.strip()) > TITLE_MAX:
            return f"제목은 {TITLE_MAX}자까지 쓸 수 있어요."
        return None

    def _check_areas(self, v: Any) -> list[Area] | str:
        if not isinstance(v, list) or not v:
            return "영역을 하나 이상 알려 주세요."
        out: list[Area] = []
        for a in v:
            try:
                out.append(Area(a))
            except ValueError:
                names = ", ".join(x.value for x in Area)
                return f"알 수 없는 영역이에요. 쓸 수 있는 영역: {names}"
        return out

    def _task_dict(self, t: Task) -> dict[str, Any]:
        return {
            "id": t.id,
            "title": t.title,
            "status": t.status.value,
            "areas": [a.value for a in t.areas],
            "planned_for": t.planned_for.isoformat() if t.planned_for else None,
            "scheduled_at": self._local_iso(t.scheduled_at),
            "parent_id": t.parent_id,
            "note": t.note,
            "completed_at": self._local_iso(t.completed_at),
        }

    def _local_iso(self, dt: datetime | None) -> str | None:
        return local(dt, self.tz).isoformat(timespec="minutes") if dt else None

    def _event_data(self, t: Task) -> dict[str, Any]:
        return {
            "title": t.title,
            "planned_for": t.planned_for.isoformat() if t.planned_for else None,
            "scheduled_at": self._local_iso(t.scheduled_at),
        }

    def _finish(
        self, ctx: RunContext, kind: str, t: Task, *, undo: dict[str, Any] | None = None, extra: tuple[str, ...] | list[str] = ()
    ) -> dict[str, Any]:
        """트랜잭션 안에서 부른다: 호출 기록과 활동(확인 문구 한 줄, 바꾸기 전 값). 끝난 뒤 `_after`를 부른다.

        `extra`는 할 일 말고도 바뀐 대상(내려놓기로 지워진 우선순위 칸)이다.
        """
        data = self._event_data(t)
        self.tasks.log_tool_event(ctx.run_id, ctx.conversation_id, t.id, kind, inbound_id=ctx.inbound_id, data=data)
        summary = confirmation_line(ToolEvent(kind, t.id, data), self.today())
        self._record(ctx, kind, task_target(t.id), summary, undo, targets=[task_target(t.id), *extra])
        return self._task_dict(t)

    def _record(
        self, ctx: RunContext, kind: str, target: str | None, summary: str | None, undo: dict[str, Any] | None,
        *, targets: list[str] | None = None,
    ) -> None:
        record_activity(
            self.activity, ctx, kind=kind, target=target, summary=summary or kind, undo=undo, targets=targets
        )

    @staticmethod
    def _before(t: Task) -> dict[str, Any]:
        """되돌릴 때 쓸 이전 값(활동 `undo_json`). 시각은 저장 형식(UTC ISO) 그대로."""
        return {
            "task_id": t.id,
            "status": t.status.value,
            "completed_at": to_iso(t.completed_at) if t.completed_at else None,
            "planned_for": t.planned_for.isoformat() if t.planned_for else None,
            "scheduled_at": to_iso(t.scheduled_at) if t.scheduled_at else None,
        }

    def _after(self, ctx: RunContext, kind: str, t: Task) -> None:
        ctx.events.append(ToolEvent(kind=kind, task_id=t.id, data=self._event_data(t)))
        self._export()

    def _export(self) -> None:
        """`tasks.md`, 곡선 저장소가 있으면 `curve/chapters.md`, 습관 저장소가 있으면 `habits.md`도. 되돌리기와 실패한 즉시 갈래도 이것을 부른다."""
        try:
            export_tasks(self.tasks, self.export_path, self.today())
        except OSError as e:  # 데이터는 이미 저장됐다. 내보내기는 다음 변경 때 다시 만든다.
            log.warning("export_failed", extra={"error_type": type(e).__name__})
        self._export_curve()
        self._export_habits()

    def _export_curve(self) -> None:
        if self.curve is None:
            return
        try:
            export_curve(self.curve, self.curve_export_path)
        except OSError as e:
            log.warning("curve_export_failed", extra={"error_type": type(e).__name__})

    def _grant(self, ctx: RunContext, *, source_kind: str, source_ref: str, amount: int, label: str) -> bool:
        """경험치 원장 한 줄(9.1 X1~X8, X10). 변경과 같은 트랜잭션 안에서 부른다. 상태창 저장소가 없으면(SP1 시험)
        쌓지 않는다. 되돌리기는 원장을 건드리지 않는다(U6)."""
        if self.status is None:
            return False
        return self.status.grant(
            at=self.clock.now(), logical_date=self.today(), source_kind=source_kind, source_ref=source_ref,
            amount=amount, label=label, gain=ctx.xp,
        )

    def _get(self, id: Any) -> Task | str:
        t = self.tasks.get(id) if isinstance(id, int) and not isinstance(id, bool) else None
        return t if t is not None else f"{id}번 할 일을 찾을 수 없어요."

    # --- 회차 차례의 확인 (SP3-4 10.1) ---

    def _confirm_first(self, ctx: RunContext) -> bool:
        """회차 차례이고 확인 토큰을 둘 곳이 있다(A1·A2)."""
        return ctx.run_turn and self.confirms is not None

    def _request_confirm(
        self, ctx: RunContext, action: str, args: dict[str, Any], summary: str, button: str
    ) -> dict[str, Any]:
        """아무것도 바꾸지 않고 확인 토큰을 만든다(A2): `pending_confirms`(`origin = run_turn`, 만료 = 그 회차 답장 창
        끝), 호출 기록과 활동 `confirm_requested`(되돌릴 것 없음)는 한 트랜잭션. ToolEvent `confirm_requested`.

        `args`는 `/actions`에 그대로 다시 보낼 모양이다(`{"action": …, "args": …, "confirm_token": …}`, 6.4.2).
        `summary`(확인 문구 전부)는 토큰, 앱 `ui_confirm`, 회차 메시지 글에, `button`(짧은 동작 이름 + 대상)은
        텔레그램 `✓` 버튼에 쓴다. 두뇌에게 `needs_confirm`은 오류가 아니다(A7).
        """
        assert self.confirms is not None and ctx.run_id is not None
        expires_at = (
            self.reply_until(ctx.run_id) if self.reply_until is not None
            else self.clock.now() + RUN_CONFIRM_FALLBACK_TTL
        )
        with self.tasks.transaction():
            p = self.confirms.create(
                action=action, args=args, summary=summary, origin="run_turn", expires_at=expires_at,
                run_id=ctx.run_id, conversation_id=ctx.conversation_id,
            )
            data = {"action": action, "summary": summary, "button": button, "confirm_token": p.token}
            self.tasks.log_tool_event(
                ctx.run_id, ctx.conversation_id, None, "confirm_requested", inbound_id=ctx.inbound_id, data=data
            )
            self._record(ctx, "confirm_requested", None, confirm_requested_summary(summary), None)
        ctx.events.append(ToolEvent(kind="confirm_requested", task_id=None, data=data))
        log.info("confirm_requested", extra={"action": action, "run_id": ctx.run_id})  # 인자, 문구, 토큰 없이
        return {"status": "needs_confirm", "confirm_token": p.token, "summary": summary}

    # --- 변경 도구 ---

    def _check_new(
        self,
        title: Any = None,
        areas: Any = None,
        planned_for: Any = None,
        scheduled_at: Any = None,
        parent_id: Any = None,
        note: Any = None,
    ) -> dict[str, Any] | str:
        """새 할 일 입력 검증(add_task, propose_tasks 공용). 맞으면 `TasksRepo.create` 인자, 아니면 오류 문구."""
        if (m := self._check_title(title)) is not None:
            return m
        checked_areas = self._check_areas(areas)
        if isinstance(checked_areas, str):
            return checked_areas
        pf = self._parse_date(planned_for, "planned_for")
        if isinstance(pf, str):
            return pf
        sa = self._parse_dt(scheduled_at)
        if isinstance(sa, str):
            return sa
        if parent_id is not None and (
            not isinstance(parent_id, int) or self.tasks.get(parent_id) is None
        ):
            return f"{parent_id}번 할 일이 없어서 첫 걸음으로 붙일 수 없어요."
        if pf is None and sa is not None:  # 시각만 주면 그 날이 하려는 날이다
            pf = logical_date(sa, self.tz, self.boundary)
        return {
            "title": title.strip(),
            "areas": checked_areas,
            "planned_for": pf,
            "scheduled_at": sa,
            "parent_id": parent_id,
            "note": note if isinstance(note, str) else "",
        }

    @_tool
    def add_task(self, ctx: RunContext, **inputs: Any) -> dict[str, Any]:
        unknown = set(inputs) - _NEW_FIELDS
        if unknown:
            return _err(f"알 수 없는 항목이 있어요: {', '.join(sorted(unknown))}")
        new = self._check_new(**inputs)
        if isinstance(new, str):
            return _err(new)
        with self.tasks.transaction():
            t = self.tasks.create(status=TaskStatus.open, **new)
            out = self._finish(ctx, "task_added", t, undo={"task_id": t.id})
        self._after(ctx, "task_added", t)
        return out

    @_tool
    def propose_tasks(self, ctx: RunContext, tasks: Any = None) -> dict[str, Any]:
        """비서가 제안하는 할 일을 `draft`로 저장한다. 하나라도 잘못되면 아무것도 만들지 않는다."""
        if not isinstance(tasks, list) or not tasks:
            return _err("제안할 할 일 목록을 하나 이상 알려 주세요.")
        if len(tasks) > PROPOSE_MAX:
            return _err(f"한 번에 {PROPOSE_MAX}개까지 제안할 수 있어요.")
        checked: list[dict[str, Any]] = []
        for i, item in enumerate(tasks, start=1):
            if not isinstance(item, dict):
                return _err(f"{i}번째 제안이 할 일 형식이 아니에요.")
            unknown = set(item) - _NEW_FIELDS
            if unknown:
                return _err(f"{i}번째 제안에 알 수 없는 항목이 있어요: {', '.join(sorted(unknown))}")
            new = self._check_new(**item)
            if isinstance(new, str):
                return _err(f"{i}번째 제안: {new}")
            checked.append(new)
        made: list[Task] = []
        with self.tasks.transaction():
            for new in checked:
                t = self.tasks.create(status=TaskStatus.draft, **new)
                self.tasks.log_tool_event(
                    ctx.run_id, ctx.conversation_id, t.id, "tasks_proposed",
                    inbound_id=ctx.inbound_id, data={"ids": [t.id], "titles": [t.title]},
                )
                made.append(t)
            target, targets = tasks_target([t.id for t in made])
            self._record(ctx, "tasks_proposed", target, titles_summary("제안", [t.title for t in made]), None,
                         targets=targets)
        ids = [t.id for t in made]
        ctx.events.append(
            ToolEvent(kind="tasks_proposed", task_id=None, data={"ids": ids, "titles": [t.title for t in made]})
        )
        self._export()
        return {"proposed": [self._task_dict(t) for t in made]}

    @_tool
    def confirm_tasks(self, ctx: RunContext, ids: Any = None) -> dict[str, Any]:
        """초안을 `open`으로 확정한다. 초안이 아니거나 없는 번호는 바꾸지 않고 `skipped_ids`에 둔다."""
        if not isinstance(ids, list) or any(not isinstance(i, int) or isinstance(i, bool) for i in ids):
            return _err("ids는 할 일 번호(숫자) 목록이에요.")
        confirmed: list[Task] = []
        skipped: list[int] = []
        with self.tasks.transaction():
            for i in dict.fromkeys(ids):
                t = self.tasks.get(i)
                if t is None or t.status is not TaskStatus.draft:
                    skipped.append(i)
                    continue
                t = self.tasks.set_status(t.id, TaskStatus.open)
                self.tasks.log_tool_event(
                    ctx.run_id, ctx.conversation_id, t.id, "tasks_confirmed",
                    inbound_id=ctx.inbound_id, data=self._event_data(t),
                )
                confirmed.append(t)
            if confirmed:
                one = len(confirmed) == 1
                target, targets = tasks_target([t.id for t in confirmed])
                self._record(
                    ctx, "tasks_confirmed", target,
                    confirmation_line(ToolEvent("tasks_confirmed", confirmed[0].id, self._event_data(confirmed[0])),
                                      self.today()) if one else titles_summary("확정", [t.title for t in confirmed]),
                    {"task_ids": [t.id for t in confirmed]}, targets=targets,
                )
        for t in confirmed:
            ctx.events.append(ToolEvent(kind="tasks_confirmed", task_id=t.id, data=self._event_data(t)))
        if confirmed:
            self._export()
        return {"confirmed": [self._task_dict(t) for t in confirmed], "skipped_ids": skipped}

    @_tool
    def update_task(self, ctx: RunContext, id: Any = None, **fields: Any) -> dict[str, Any]:
        t = self._get(id)
        if isinstance(t, str):
            return _err(t)
        extra = set(fields) - {"title", "areas", "note", "scheduled_at"}
        if extra:
            hint = " 날짜는 move_task로 바꿔 주세요." if "planned_for" in extra else ""
            return _err(f"바꿀 수 없는 항목이 있어요: {', '.join(sorted(extra))}.{hint}")
        if not fields:
            return _err("바꿀 내용을 알려 주세요.")
        changes: dict[str, Any] = {}
        if "title" in fields:
            if (m := self._check_title(fields["title"])) is not None:
                return _err(m)
            changes["title"] = fields["title"].strip()
        if "areas" in fields:
            checked = self._check_areas(fields["areas"])
            if isinstance(checked, str):
                return _err(checked)
            changes["areas"] = checked
        if "note" in fields:
            if not isinstance(fields["note"], str):
                return _err("메모는 글로 알려 주세요.")
            changes["note"] = fields["note"]
        if "scheduled_at" in fields:
            sa = self._parse_dt(fields["scheduled_at"])
            if isinstance(sa, str):
                return _err(sa)
            changes["scheduled_at"] = sa
            if sa is not None:  # 시각을 바꾸면 하려는 날도 그 시각의 논리적 날짜로 다시 정한다
                changes["planned_for"] = logical_date(sa, self.tz, self.boundary)
        if self._confirm_first(ctx) and "scheduled_at" in changes and changes["scheduled_at"] != t.scheduled_at:
            sa = changes["scheduled_at"]
            args = {"id": t.id, **fields, "scheduled_at": api_time(sa) if sa is not None else None}
            return self._request_confirm(
                ctx, "update_task", args, confirm_schedule_summary(t.title, local(sa, self.tz) if sa else None),
                confirm_button_schedule(t.title),
            )
        prior = {**self._before(t), "title": t.title, "note": t.note, "areas": [a.value for a in t.areas]}
        before = {k: prior[k] for k in changes}  # 바뀐 필드의 이전 값만
        with self.tasks.transaction():
            t = self.tasks.update(t.id, **changes)
            out = self._finish(ctx, "task_updated", t, undo={"task_id": t.id, "before": before})
        self._after(ctx, "task_updated", t)
        return out

    @_tool
    def move_task(self, ctx: RunContext, id: Any = None, planned_for: Any = None) -> dict[str, Any]:
        t = self._get(id)
        if isinstance(t, str):
            return _err(t)
        pf = self._parse_date(planned_for, "planned_for")
        if isinstance(pf, str):
            return _err(pf)
        # 날짜를 옮기면 시각도 바뀐다(A2). 같은 날로 옮기면 바뀌는 것이 없어 바로 적용한다
        if self._confirm_first(ctx) and t.scheduled_at is not None and pf != t.planned_for:
            args = {"id": t.id, "planned_for": pf.isoformat() if pf is not None else None}
            return self._request_confirm(
                ctx, "move_task", args, confirm_move_summary(t.title, pf, self.today()), confirm_button_move(t.title)
            )
        changes: dict[str, Any] = {"planned_for": pf}
        if pf is None:  # 날짜 없음: 시각도 함께 지운다
            changes["scheduled_at"] = None
        elif t.scheduled_at is not None:  # 시각이 있으면 날짜만 옮기고 한국 시간 시각은 그대로 둔다
            at = local(t.scheduled_at, self.tz)
            # 경계 전(00:00~03:59)의 시각은 새 논리적 날짜의 다음 달력 날에 놓는다
            day = pf + timedelta(days=1) if at.time() < self.boundary else pf
            changes["scheduled_at"] = datetime.combine(day, at.timetz().replace(tzinfo=None), tzinfo=self.tz)
        prior = self._before(t)
        undo = {"task_id": t.id, "planned_for": prior["planned_for"], "scheduled_at": prior["scheduled_at"]}
        with self.tasks.transaction():
            t = self.tasks.update(t.id, event_kind="moved", **changes)
            out = self._finish(ctx, "task_moved", t, undo=undo)
        self._after(ctx, "task_moved", t)
        return out

    def _set_status(
        self, ctx: RunContext, id: Any, new: TaskStatus, kind: str, allowed: set[TaskStatus], why: str
    ) -> dict[str, Any]:
        t = self._get(id)
        if isinstance(t, str):
            return _err(t)
        if t.status not in allowed:
            return _err(why)
        undo = self._before(t)
        # X1/X2: 완료 순간 그 할 일이 든 지금 기간 우선순위 가운데 가장 큰 주기(9.1)
        prio = self.tasks.current_priority(t.id, self.today()) if new is TaskStatus.done else None
        extra: list[str] = []
        if new is TaskStatus.dropped:  # 내려놓으면 우선순위 칸이 지워진다. 비어 있으면 되살린다(6.4.3)
            rows = self.tasks.priority_rows(t.id)
            undo["priorities"] = [list(row) for row in rows]
            extra = [priorities_target(c, p) for c, p, _ in rows]  # 그 목록도 바뀐 대상이다
        with self.tasks.transaction():
            t = self.tasks.set_status(t.id, new)
            out = self._finish(ctx, kind, t, undo=undo, extra=extra)
            if new is TaskStatus.done:  # 다시 완료해도 한 번만(`task:<id>`, U6)
                self._grant(ctx, source_kind="task_done", source_ref=f"task:{t.id}",
                            amount=task_xp(prio[0].value if prio is not None else None), label=LABEL_TASK)
        self._after(ctx, kind, t)
        return out

    @_tool
    def complete_task(self, ctx: RunContext, id: Any = None) -> dict[str, Any]:
        return self._set_status(
            ctx, id, TaskStatus.done, "task_completed", {TaskStatus.open}, "열린 할 일만 완료로 바꿀 수 있어요."
        )

    @_tool
    def reopen_task(self, ctx: RunContext, id: Any = None) -> dict[str, Any]:
        """전에 열려 있던 할 일만 다시 연다: 완료한 것, 열린 채로 내려놓은 것.

        초안이었다가 빠지거나 만료된 것은 열지 않는다(사용자가 확정한 적이 없다).
        """
        t = self._get(id)
        if isinstance(t, str):
            return _err(t)
        if t.status is TaskStatus.dropped and self.tasks.dropped_from(t.id) is not TaskStatus.open:
            return _err("확정하지 않은 초안이라 되돌릴 수 없어요. 필요하면 새로 추가해 드릴게요.")
        return self._set_status(
            ctx,
            t.id,
            TaskStatus.open,
            "task_reopened",
            {TaskStatus.done, TaskStatus.dropped},
            "완료했거나 내려놓은 할 일만 되돌릴 수 있어요.",
        )

    @_tool
    def drop_task(self, ctx: RunContext, id: Any = None) -> dict[str, Any]:
        if self._confirm_first(ctx):
            t = self._get(id)
            # 열린 할 일만. 초안(비서 자신의 제안)은 바로 뺀다. 그 밖은 아래가 거절한다
            if not isinstance(t, str) and t.status is TaskStatus.open:
                return self._request_confirm(
                    ctx, "drop_task", {"id": t.id}, confirm_drop_summary(t.title), confirm_button_drop(t.title)
                )
        return self._set_status(
            ctx,
            id,
            TaskStatus.dropped,
            "task_dropped",
            {TaskStatus.open, TaskStatus.draft},
            "열려 있거나 초안인 할 일만 내려놓을 수 있어요.",
        )

    @staticmethod
    def _valid_period(c: Cadence, period: str) -> bool:
        try:
            if c is Cadence.day:
                return date.fromisoformat(period).isoformat() == period
            if c is Cadence.week:
                y, w = period.split("-W")
                date.fromisocalendar(int(y), int(w), 1)
                return len(y) == 4 and len(w) == 2
            if c is Cadence.month:
                y, m = period.split("-")
                return len(y) == 4 and len(m) == 2 and 1 <= int(m) <= 12
            if c is Cadence.quarter:
                y, q = period.split("-Q")
                return len(y) == 4 and q in ("1", "2", "3", "4")
            return len(period) == 4 and period.isdigit()
        except ValueError:
            return False

    @_tool
    def set_priorities(
        self, ctx: RunContext, cadence: Any = None, period: Any = None, task_ids: Any = None
    ) -> dict[str, Any]:
        """그 기간의 우선순위를 통째로 바꾼다. 순서가 순위다."""
        try:
            c = Cadence(cadence)
        except ValueError:
            return _err("cadence는 day, week, month, quarter, year 중 하나예요.")
        if not isinstance(period, str) or not self._valid_period(c, period):
            return _err(f"period 형식이 맞지 않아요. {c.value}는 {PERIOD_EXAMPLE[c]} 같은 형식이에요.")
        if not isinstance(task_ids, list):
            return _err("task_ids는 할 일 번호 목록이에요.")
        if len(task_ids) > PRIORITY_MAX:
            return _err(f"우선순위는 {PRIORITY_MAX}개까지 정할 수 있어요.")
        if any(not isinstance(i, int) or isinstance(i, bool) for i in task_ids):
            return _err("task_ids는 할 일 번호(숫자) 목록이에요.")
        if len(set(task_ids)) != len(task_ids):
            return _err("같은 할 일을 두 순위에 올릴 수 없어요.")
        for i in task_ids:
            t = self._get(i)
            if isinstance(t, str):
                return _err(t)
            if t.status is not TaskStatus.open:
                return _err(f"{t.id}번 할 일은 열린 할 일이 아니라서 우선순위에 올릴 수 없어요.")
        ids: list[int] = list(task_ids)
        # 지금 목록과 같으면 바뀌는 것이 없어 바로 적용한다
        if self._confirm_first(ctx) and [t.id for _, t in self.tasks.priority_ranks(c, period)] != ids:
            titles = [t.title for i in ids if not isinstance(t := self._get(i), str)]
            label = period_label(c.value, period, period_of(c, self.today()))
            return self._request_confirm(
                ctx, "set_priorities", {"cadence": c.value, "period": period, "task_ids": ids},
                confirm_priorities_summary(label, titles), confirm_button_priorities(label),
            )
        ranked = self.tasks.priority_ranks(c, period)
        before = [t.id for _, t in ranked]
        before_status = [t.status.value for _, t in ranked]  # 되돌릴 때 그 뒤에 상태가 바뀌었는지 본다(6.4.3)
        with self.tasks.transaction():
            self.tasks.set_priorities(c, period, ids)
            picked = self.tasks.priorities(c, period)
            data = {"cadence": c.value, "period": period, "titles": [t.title for t in picked]}
            self.tasks.log_tool_event(
                ctx.run_id, ctx.conversation_id, None, "priorities_set", inbound_id=ctx.inbound_id, data=data,
            )
            self._record(
                ctx, "priorities_set", priorities_target(c.value, period),
                confirmation_line(ToolEvent("priorities_set", None, data), self.today()),
                {"cadence": c.value, "period": period, "task_ids": before, "statuses": before_status},
                # 목록과 함께, 빠지거나 들어온 할 일도 바뀐 대상이다(그 할 일의 확인 토큰이 stale이 된다)
                targets=[priorities_target(c.value, period), *(task_target(i) for i in dict.fromkeys([*before, *ids]))],
            )
        ctx.events.append(
            ToolEvent(
                kind="priorities_set",
                task_id=None,
                data={"cadence": c.value, "period": period, "titles": [t.title for t in picked]},
            )
        )
        return {"cadence": c.value, "period": period, "priorities": [self._task_dict(t) for t in picked]}

    @_tool
    def record_condition(
        self, ctx: RunContext, score: Any = None, date: Any = None, note: Any = None
    ) -> dict[str, Any]:
        """그날 컨디션(1~5)을 기록한다. 날짜를 안 주면 논리적 오늘. 같은 날은 덮어쓴다(ToolEvent 없음)."""
        if self.conditions is None:
            return _err("컨디션을 기록할 수 없어요.")
        if not isinstance(score, int) or isinstance(score, bool) or not SCORE_MIN <= score <= SCORE_MAX:
            return _err(f"컨디션은 {SCORE_MIN}~{SCORE_MAX} 사이의 숫자로 알려 주세요.")
        if date is not None and not (isinstance(date, str) and _ISO_DATE.fullmatch(date)):
            return _err("date는 YYYY-MM-DD 형식으로 알려 주세요.")
        d = self._parse_date(date, "date")
        if isinstance(d, str):
            return _err(d)
        day = d if d is not None else self.today()
        if day > self.today():
            return _err("아직 오지 않은 날의 컨디션은 기록할 수 없어요.")
        with transaction(self.conditions.conn):
            prev = self.conditions.get(day)
            c = self.conditions.upsert(day, score, note if isinstance(note, str) else None)
            # 활동에도 메모(사용자 글)는 넣지 않는다. 되돌릴 이전 행만 `undo_json`에 둔다
            before = (
                {"score": prev.score, "note": prev.note, "recorded_at": to_iso(prev.recorded_at)} if prev else None
            )
            self._record(
                ctx, "condition_recorded", condition_target(day), condition_summary(c.score),
                {"date": day.isoformat(), "before": before},
            )
            self._grant(ctx, source_kind="condition", source_ref=f"date:{day.isoformat()}", amount=XP_CONDITION,
                        label=LABEL_CONDITION)  # X4: 날마다 한 번
        # 메모는 남기지 않는다. 날짜와 점수만.
        log.info("condition_recorded", extra={"date": day.isoformat(), "score": c.score})
        return {"date": c.date.isoformat(), "score": c.score, "note": c.note}

    def expire_drafts(self, ctx: RunContext, older_than: datetime) -> dict[str, Any]:
        """하루 한 번 작업(`apply_action`, `secretary`/`scheduler`): `proposed_at`이 `older_than` 이전인 초안을
        조용히 `dropped`로 바꾸고 활동 `drafts_expired` 하나를 남긴다(되돌릴 수 없다). 알리지 않는다."""
        with self.tasks.transaction():
            ids = self.tasks.expire_drafts(older_than)
            if ids:
                target, targets = tasks_target(ids)
                self._record(ctx, "drafts_expired", target, drafts_expired_summary(len(ids)), None, targets=targets)
        if ids:
            self._export()
        return {"expired_ids": ids}

    # --- 인생 곡선 (SP3-4 10장, 5.4). 사용자가 말한 점수만 기록하고, 초안의 확정과 빼기만 한다 ---

    def _curve_period(self, ctx: RunContext, cadence: Cadence) -> str:
        """기간 기본값(10장): 회고 회차의 대화면 그 회고 날짜가 든 달·분기, 아니면 오늘이 든 달·분기."""
        review = self.review_date_for(ctx) if self.review_date_for is not None else None
        return period_of(cadence, review if review is not None else self.today())

    def _curve_event(self, ctx: RunContext, kind: str, data: dict[str, Any]) -> ToolEvent:
        """트랜잭션 안에서: 호출 기록(`tool_events_log`, 중단 뒤 다시 처리할 때 두 번 쓰지 않게)과 ToolEvent."""
        self.tasks.log_tool_event(ctx.run_id, ctx.conversation_id, None, kind, inbound_id=ctx.inbound_id, data=data)
        return ToolEvent(kind=kind, task_id=None, data=data)

    @staticmethod
    def _score(v: Any, lo: int, hi: int) -> int | None:
        return v if isinstance(v, int) and not isinstance(v, bool) and lo <= v <= hi else None

    @_tool
    def record_ladder_score(
        self, ctx: RunContext, period: Any = None, now: Any = None, future: Any = None, note: Any = None
    ) -> dict[str, Any]:
        """사용자가 말한 사다리 점수(0~10). 없는 쪽은 그 달 기존 값을 둔다. 미래 달은 거절한다."""
        if self.curve is None:
            return _err("사다리 점수를 기록할 수 없어요.")
        if now is None and future is None:
            return _err("now(지금)나 future(5년 뒤) 가운데 하나는 알려 주세요.")
        for name, v in (("now", now), ("future", future)):
            if v is not None and self._score(v, LADDER_MIN, LADDER_MAX) is None:
                return _err(f"{name}은(는) {LADDER_MIN}~{LADDER_MAX} 사이의 숫자로 알려 주세요.")
        if note is not None and not isinstance(note, str):
            return _err("메모는 글로 알려 주세요.")
        if period is None:
            period = self._curve_period(ctx, Cadence.month)
        elif not isinstance(period, str) or not self._valid_period(Cadence.month, period):
            return _err(f"period는 {PERIOD_EXAMPLE[Cadence.month]} 같은 달 형식이에요.")
        if period > period_of(Cadence.month, self.today()):
            return _err("아직 오지 않은 달의 사다리 점수는 기록할 수 없어요.")
        before = self.curve.ladder(period)
        with transaction(self.curve.conn):
            row = self.curve.set_ladder(period, now=now, future=future, note=note)
            data = {"period": period, "now": row.now, "future": row.future}  # 메모는 넣지 않는다
            event = self._curve_event(ctx, "ladder_recorded", data)
            self._record(ctx, "ladder_recorded", ladder_target(period), ladder_line(period, row.now, row.future),
                         {"period": period, "before": _ladder_dict(before)})
            self._grant(ctx, source_kind="ladder", source_ref=f"ladder:{period}", amount=XP_LADDER,
                        label=LABEL_LADDER)  # X6: 그 달 처음
        ctx.events.append(event)
        self._export_curve()
        log.info("ladder_recorded", extra={"period": period})
        return {"period": row.period, "now": row.now, "future": row.future, "note": row.note}

    @_tool
    def record_area_scores(
        self, ctx: RunContext, scores: Any = None, period: Any = None, notes: Any = None, recovery_quests: Any = None
    ) -> dict[str, Any]:
        """사용자가 말한 영역 점수(1~10). 회복 퀘스트는 바로 앞 분기보다 내려간 영역에만 받는다(10장, 9.3)."""
        if self.curve is None:
            return _err("영역 점수를 기록할 수 없어요.")
        names = ", ".join(a.value for a in Area)
        if not isinstance(scores, dict) or not scores:
            return _err(f"scores는 영역별 점수예요. 예: {{\"career\": 7}}. 쓸 수 있는 영역: {names}")
        for area, v in scores.items():
            if area not in {a.value for a in Area}:
                return _err(f"알 수 없는 영역이에요. 쓸 수 있는 영역: {names}")
            if self._score(v, AREA_SCORE_MIN, AREA_SCORE_MAX) is None:
                return _err(f"영역 점수는 {AREA_SCORE_MIN}~{AREA_SCORE_MAX} 사이의 숫자로 알려 주세요.")
        for name, extra in (("notes", notes), ("recovery_quests", recovery_quests)):
            if extra is None:
                continue
            if not isinstance(extra, dict) or not all(isinstance(v, str) and v.strip() for v in extra.values()):
                return _err(f"{name}는 영역별 글이에요.")
            if set(extra) - set(scores):
                return _err(f"{name}에는 이번에 점수를 넣은 영역만 쓸 수 있어요.")
        if period is None:
            period = self._curve_period(ctx, Cadence.quarter)
        elif not isinstance(period, str) or not self._valid_period(Cadence.quarter, period):
            return _err(f"period는 {PERIOD_EXAMPLE[Cadence.quarter]} 같은 분기 형식이에요.")
        if period > period_of(Cadence.quarter, self.today()):
            return _err("아직 오지 않은 분기의 영역 점수는 기록할 수 없어요.")
        quests = {a: q.strip() for a, q in (recovery_quests or {}).items()}
        prev_period = _prev_quarter(period)
        for area in quests:
            prev = self.curve.area_score(prev_period, area)
            if prev is None or scores[area] >= prev.score:
                return _err("recovery_quests는 지난 분기보다 내려간 영역에만 넣을 수 있어요.")
        if any(len(q) > RECOVERY_QUEST_MAX for q in quests.values()):
            return _err(f"회복 퀘스트는 {RECOVERY_QUEST_MAX}자까지 쓸 수 있어요.")
        before = {a: _area_dict(self.curve.area_score(period, a)) for a in scores}
        with transaction(self.curve.conn):
            rows = self.curve.set_area_scores(period, dict(scores), notes=notes, quests=quests)
            data = {"period": period, "scores": {r.area: r.score for r in rows}}
            event = self._curve_event(ctx, "area_scores_recorded", data)
            self._record(ctx, "area_scores_recorded", areas_target(period), area_scores_line(period, data["scores"]),
                         {"period": period, "before": before})
            self._grant(ctx, source_kind="wheel", source_ref=f"areas:{period}", amount=XP_WHEEL,
                        label=LABEL_WHEEL)  # X7: 그 분기 처음(한 영역이라도)
        ctx.events.append(event)
        self._export_curve()
        log.info("area_scores_recorded", extra={"period": period, "areas": len(rows)})
        return {"period": period, "scores": data["scores"]}

    @_tool
    def grant_xp(self, ctx: RunContext, amount: Any = None, reason: Any = None) -> dict[str, Any]:
        """X10(9.1, 10장): 하네스 규칙에 없는 일을 사용자가 했다고 말했을 때 비서가 주는 경험치. 5 또는 10, 하루 3회.

        사유는 원장 `label`(상태창 "최근 경험치" 줄)과 확인 문구에 쓴다. 되돌릴 수 없다(원장은 오르기만 한다, U6).
        로그에는 사유를 남기지 않는다.
        """
        if self.status is None:
            return _err("경험치를 줄 수 없어요.")
        if not isinstance(amount, int) or isinstance(amount, bool) or amount not in XP_SECRETARY:
            return _err("amount는 5 또는 10이에요.")
        if not isinstance(reason, str) or not reason.strip():
            return _err("reason에 경험치를 주는 까닭을 짧게 적어 주세요.")
        why = reason.strip()
        if len(why) > SECRETARY_REASON_MAX:
            return _err(f"reason은 {SECRETARY_REASON_MAX}자까지 쓸 수 있어요.")
        today = self.today()
        with transaction(self.status.conn):
            n = self.status.count_secretary_on(today)
            if n >= SECRETARY_DAILY_MAX:
                return _err(f"비서가 주는 경험치는 하루 {SECRETARY_DAILY_MAX}번까지예요. 오늘은 이미 다 줬어요.")
            ref = f"secretary:{today.isoformat()}:{n + 1}"
            self._grant(ctx, source_kind="secretary", source_ref=ref, amount=amount, label=why)
            data = {"amount": amount, "reason": why}
            event = self._curve_event(ctx, "xp_granted_by_secretary", data)
            self._record(ctx, "xp_granted_by_secretary", None, xp_granted_line(amount, why), None)
        ctx.events.append(event)
        log.info("xp_granted_by_secretary", extra={"amount": amount})
        return {"amount": amount, "reason": why, "today_count": n + 1}

    def mark_question_asked(self, question_id: int) -> None:
        """하네스가 월말 회고 메시지에 열린 시드 질문을 실었다(11.1-5): `curve_questions.status = asked`.

        두뇌 도구가 아니다(도구 수는 그대로). 회고 회차 차례가 부르고, 질문 글은 로그에 남기지 않는다.
        """
        if self.curve is None:
            return
        self.curve.mark_question(question_id, "asked")
        log.info("curve_question_asked", extra={"question_id": question_id})

    @staticmethod
    def _ids(v: Any) -> list[int] | None:
        if not isinstance(v, list) or any(not isinstance(i, int) or isinstance(i, bool) for i in v):
            return None
        return list(dict.fromkeys(v))

    def _check_curve_title(self, v: Any) -> str | None:
        if not isinstance(v, str) or not v.strip():
            return "제목이 비어 있어요."
        if len(v.strip()) > CURVE_TITLE_MAX:
            return f"제목은 {CURVE_TITLE_MAX}자까지 쓸 수 있어요."
        return None

    def _curve_origin(self, ctx: RunContext) -> str:
        """회고 회차의 대화(연말 회고 등)에서 꺼낸 초안은 `review`, 그 밖의 대화는 `chat`(5.4 `origin`)."""
        review = self.review_date_for(ctx) if self.review_date_for is not None else None
        return "review" if review is not None else "chat"

    @_tool
    def add_milestone(
        self, ctx: RunContext, date: Any = None, kind: Any = None, title: Any = None, note: Any = None,
        chapter_id: Any = None, sensitive: Any = False,
    ) -> dict[str, Any]:
        """사건 **초안**(11.3). 하네스가 답 아래에 `✓ 저장` `✗ 빼기` 버튼(앱은 `ui_milestone_draft`)을 붙인다.
        `sensitive`는 사용자가 민감하다고 말했을 때만 true다(기본 false)."""
        if self.curve is None:
            return _err("사건을 남길 수 없어요.")
        try:
            ok = isinstance(date, str) and bool(date_precision(date))
        except ValueError:
            ok = False
        if not ok:
            return _err("date는 기억하는 만큼 YYYY, YYYY-MM, YYYY-MM-DD 가운데 하나로 알려 주세요. 예: 2019, 2019-05")
        if kind not in MILESTONE_KINDS:
            return _err("kind는 high(고점), low(저점), turning_point(전환점) 가운데 하나예요.")
        if (m := self._check_curve_title(title)) is not None:
            return _err(m)
        if note is not None and not isinstance(note, str):
            return _err("메모는 글로 알려 주세요.")
        if not isinstance(sensitive, bool):
            return _err("sensitive는 true나 false예요.")
        if chapter_id is not None and (
            not isinstance(chapter_id, int) or isinstance(chapter_id, bool) or self.curve.get_chapter(chapter_id) is None
        ):
            return _err(f"{chapter_id}번 챕터를 찾을 수 없어요.")
        assert isinstance(title, str)
        with transaction(self.curve.conn):
            m = self.curve.add_milestone(
                date_text=date, kind=kind, title=title.strip(), status="draft", origin=self._curve_origin(ctx),
                note=note, chapter_id=chapter_id, sensitive=sensitive, conversation_id=ctx.conversation_id,
            )
            # 메모는 넣지 않는다. 버튼과 확인 문구를 다시 만들 재료만
            data = {"id": m.id, "title": m.title, "date_text": m.date_text, "kind": m.kind, "sensitive": m.sensitive}
            event = self._curve_event(ctx, "milestone_proposed", data)
            # 활동 요약(`GET /activity`)에서는 민감 사건 제목을 가린다(`confirm_milestones`와 같다)
            self._record(ctx, "milestone_proposed", milestone_target(m.id),
                         titles_summary("제안", [SENSITIVE_MASK if m.sensitive else m.title]), None)
        ctx.events.append(event)
        log.info("milestone_proposed", extra={"milestone_id": m.id})
        return _milestone_dict(m)

    @_tool
    def propose_chapter(
        self, ctx: RunContext, title: Any = None, start: Any = None, theme: Any = None, end: Any = None
    ) -> dict[str, Any]:
        """챕터 **초안**(연말 회고). `start`, `end`는 `YYYY-MM`이고 `end`가 없으면 지금까지다."""
        if self.curve is None:
            return _err("챕터를 남길 수 없어요.")
        if (m := self._check_curve_title(title)) is not None:
            return _err(m)
        for name, v, need in (("start", start, True), ("end", end, False)):
            if v is None and not need:
                continue
            if not isinstance(v, str) or not _MONTH.fullmatch(v):
                return _err(f"{name}은(는) 2019-03 같은 달 형식이에요.")
        if end is not None and end < start:
            return _err("end는 start와 같거나 뒤여야 해요.")
        if theme is not None and not isinstance(theme, str):
            return _err("theme은 글로 알려 주세요.")
        assert isinstance(title, str) and isinstance(start, str)
        with transaction(self.curve.conn):
            c = self.curve.add_chapter(title=title.strip(), start_month=start, end_month=end, theme=theme,
                                       status="draft", origin=self._curve_origin(ctx))
            data = {"id": c.id, "title": c.title, "start_month": c.start_month, "end_month": c.end_month}
            event = self._curve_event(ctx, "chapter_proposed", data)
            self._record(ctx, "chapter_proposed", chapter_target(c.id), titles_summary("제안", [c.title]), None)
        ctx.events.append(event)
        log.info("chapter_proposed", extra={"chapter_id": c.id})
        return _chapter_dict(c)

    @_tool
    def confirm_milestones(self, ctx: RunContext, ids: Any = None) -> dict[str, Any]:
        """사건 초안을 확정한다. 고점·전환점이면 칭호(9.4). 초안이 아니거나 없는 번호는 `skipped_ids`."""
        if self.curve is None or self.status is None:
            return _err("사건을 저장할 수 없어요.")
        if (wanted := self._ids(ids)) is None:
            return _err("ids는 사건 번호(숫자) 목록이에요.")
        events: list[ToolEvent] = []
        with transaction(self.curve.conn):
            done = self.curve.confirm_milestones(wanted)
            now = self.clock.now()
            for m in done:
                data = {"id": m.id, "title": m.title, "date_text": m.date_text, "kind": m.kind}
                events.append(self._curve_event(ctx, "milestones_confirmed", data))
                if m.kind in TITLE_KINDS:
                    self.status.add_title(m.id, now)
                    name = title_name(m.kind, m.title, m.title_label)
                    events.append(self._curve_event(ctx, "title_granted", {"milestone_id": m.id, "title": name}))
            if done:
                target, targets = many_target([milestone_target(m.id) for m in done])
                # 활동 요약(`GET /activity`)에서는 민감 사건 제목을 가린다(`chapters.md`와 같은 "(민감)")
                lines = [milestone_confirmed_line(SENSITIVE_MASK if m.sensitive else m.title, m.date_text, m.kind)
                         for m in done]
                summary = lines[0] if len(lines) == 1 else "✓ 저장: " + ", ".join(ln.removeprefix("✓ 저장: ") for ln in lines)
                self._record(ctx, "milestones_confirmed", target, summary, {"milestone_ids": [m.id for m in done]},
                             targets=targets)
        ctx.events.extend(events)
        if done:
            self._export_curve()
        got = {m.id for m in done}
        return {"confirmed": [_milestone_dict(m) for m in done], "skipped_ids": [i for i in wanted if i not in got]}

    @_tool
    def confirm_chapters(self, ctx: RunContext, ids: Any = None) -> dict[str, Any]:
        if self.curve is None:
            return _err("챕터를 저장할 수 없어요.")
        if (wanted := self._ids(ids)) is None:
            return _err("ids는 챕터 번호(숫자) 목록이에요.")
        events: list[ToolEvent] = []
        with transaction(self.curve.conn):
            done = self.curve.confirm_chapters(wanted)
            for c in done:
                data = {"id": c.id, "title": c.title, "start_month": c.start_month, "end_month": c.end_month}
                events.append(self._curve_event(ctx, "chapters_confirmed", data))
            if done:
                target, targets = many_target([chapter_target(c.id) for c in done])
                lines = [chapter_confirmed_line(c.title, c.start_month, c.end_month) for c in done]
                summary = lines[0] if len(lines) == 1 else "✓ 저장: " + ", ".join(ln.removeprefix("✓ 저장: ") for ln in lines)
                self._record(ctx, "chapters_confirmed", target, summary, {"chapter_ids": [c.id for c in done]},
                             targets=targets)
        ctx.events.extend(events)
        if done:
            self._export_curve()
        got = {c.id for c in done}
        return {"confirmed": [_chapter_dict(c) for c in done], "skipped_ids": [i for i in wanted if i not in got]}

    @_tool
    def drop_curve_drafts(self, ctx: RunContext, milestone_ids: Any = None, chapter_ids: Any = None) -> dict[str, Any]:
        """사건·챕터 **초안**을 뺀다(행 삭제, 되돌릴 수 없음). 확정한 것이 하나라도 있으면 아무것도 빼지 않고 거절한다.
        없는 번호(이미 정리된 것)는 `skipped_*`."""
        if self.curve is None:
            return _err("초안을 뺄 수 없어요.")
        ms = self._ids(milestone_ids if milestone_ids is not None else [])
        cs = self._ids(chapter_ids if chapter_ids is not None else [])
        if ms is None or cs is None:
            return _err("milestone_ids, chapter_ids는 번호(숫자) 목록이에요.")
        if not ms and not cs:
            return _err("뺄 사건이나 챕터 초안 번호를 알려 주세요.")
        found_m = {i: m for i in ms if (m := self.curve.get_milestone(i)) is not None}
        found_c = {i: c for i in cs if (c := self.curve.get_chapter(i)) is not None}
        if any(m.status != "draft" for m in found_m.values()) or any(c.status != "draft" for c in found_c.values()):
            return _err("확정한 사건이나 챕터는 뺄 수 없어요. 초안만 뺄 수 있어요.")
        events: list[ToolEvent] = []
        with transaction(self.curve.conn):
            for m in found_m.values():
                self.curve.delete_milestone_draft(m.id)
                event = self._curve_event(ctx, "milestone_dropped", {"id": m.id, "title": m.title})
                self._record(ctx, "milestone_dropped", milestone_target(m.id), dropped_line(m.title), None)
                events.append(event)
            for c in found_c.values():
                self.curve.delete_chapter_draft(c.id)
                event = self._curve_event(ctx, "chapter_dropped", {"id": c.id, "title": c.title})
                self._record(ctx, "chapter_dropped", chapter_target(c.id), dropped_line(c.title), None)
                events.append(event)
        ctx.events.extend(events)
        if events:
            self._export_curve()
        return {
            "dropped_milestone_ids": list(found_m), "dropped_chapter_ids": list(found_c),
            "skipped_milestone_ids": [i for i in ms if i not in found_m],
            "skipped_chapter_ids": [i for i in cs if i not in found_c],
        }

    def expire_curve_drafts(self, ctx: RunContext, older_than: datetime) -> dict[str, Any]:
        """하루 한 번 작업(`secretary`/`scheduler`): `draft_since`가 `older_than` 이전인 사건·챕터 초안을 조용히
        지운다(5.4). 활동 `milestone_drafts_expired`, `chapter_drafts_expired`(되돌릴 수 없다). 알리지 않는다."""
        if self.curve is None:
            return {"expired_milestone_ids": [], "expired_chapter_ids": []}
        with transaction(self.curve.conn):
            ms, cs = self.curve.expire_drafts(older_than)
            for kind, ids, to_target in (
                ("milestone_drafts_expired", ms, milestone_target), ("chapter_drafts_expired", cs, chapter_target)
            ):
                if ids:
                    target, targets = many_target([to_target(i) for i in ids])
                    self._record(ctx, kind, target, drafts_expired_summary(len(ids)), None, targets=targets)
        if ms or cs:
            self._export_curve()
        return {"expired_milestone_ids": ms, "expired_chapter_ids": cs}

    # --- 화면 도구 (SP3-4 6.4.7): 그리기만 한다. DB, 파일, `ctx.events`를 건드리지 않는다 ---

    def _draw(self, component: str, props: dict[str, Any]) -> dict[str, Any]:
        """props를 카탈로그 스키마로 검사만 한다. 빠진 항목(None)은 넣지 않는다(스키마가 빠졌다고 알린다)."""
        err = validate_props(component, {k: v for k, v in props.items() if v is not None})
        return _err(f"화면 조각 형식이 맞지 않아요: {err}") if err is not None else {"ok": True}

    @_tool
    def ui_todo_list(self, ctx: RunContext, title: Any = None, task_ids: Any = None, **extra: Any) -> dict[str, Any]:
        return self._draw("ui_todo_list", {"title": title, "task_ids": task_ids, **extra})

    @_tool
    def ui_choice(self, ctx: RunContext, question: Any = None, options: Any = None, **extra: Any) -> dict[str, Any]:
        return self._draw("ui_choice", {"question": question, "options": options, **extra})

    @_tool
    def ui_summary_card(self, ctx: RunContext, title: Any = None, lines: Any = None, **extra: Any) -> dict[str, Any]:
        return self._draw("ui_summary_card", {"title": title, "lines": lines, **extra})

    @_tool
    def ui_habit_check(self, ctx: RunContext, date: Any = None, **extra: Any) -> dict[str, Any]:
        """오늘 습관 줄 묶음(SP7 6.3, 9장): 그리기만 한다. `date`를 빼면 오늘."""
        day = self.today().isoformat() if date is None else date
        err = self._parse_date(day, "date") if isinstance(day, str) else None
        if isinstance(err, str):
            return _err(f"화면 조각 형식이 맞지 않아요: {err}")
        return self._draw("ui_habit_check", {"date": day, **extra})

    def ui_habit_list(self, day: Any) -> list[dict[str, Any]]:
        """화면 조각의 `data.habits`(그 날짜 기준 활성 습관 `Habit`). 날짜가 틀리거나 습관 저장소가 없으면 빈 목록. 읽기만 한다."""
        if self.habits is None or not isinstance(day, str):
            return []
        try:
            d = date.fromisoformat(day)
        except ValueError:
            return []
        return habits_view(self.habits, d, ("active",))["items"]

    def ui_todo_refs(self, ids: Any, *, drafts: bool) -> list[dict[str, Any]]:
        """화면 조각의 `data.todos`(6.3 `TodoRef`, `ids` 순서). 소프트 삭제한 할 일은 늘 빠지고, 초안은 `drafts`일 때만
        (하네스 초안 카드 `ui_todo_draft`) 넣는다. 읽기만 한다."""
        if not isinstance(ids, list):
            return []
        ints = [i for i in ids if isinstance(i, int) and not isinstance(i, bool)]
        return todo_refs(ints, self.tasks, self.today(), drafts=drafts)

    # --- 카드 도구 (SP3-4 10장, 6.4.2): 고정 카드(`app_cards`). 활동은 되돌릴 수 있다 ---

    def _card_event(
        self, ctx: RunContext, kind: str, target: str, data: dict[str, Any], undo: dict[str, Any]
    ) -> None:
        """카드 변경과 같은 트랜잭션 안에서: 호출 기록(`tool_events_log`: 중단 뒤 다시 처리할 때 두 번 쓰지 않게,
        스펙 5.4-3), 활동(확인 문구 한 줄), `ctx.events`(두뇌 재시도 방지와 `data-activity.confirmation`)."""
        self.tasks.log_tool_event(ctx.run_id, ctx.conversation_id, None, kind, inbound_id=ctx.inbound_id, data=data)
        event = ToolEvent(kind=kind, task_id=None, data=data)
        self._record(ctx, kind, target, confirmation_line(event, self.today()), undo)
        ctx.events.append(event)

    @staticmethod
    def _card_dict(c: Card) -> dict[str, Any]:
        return {"id": c.id, "component": c.component, "order": c.sort_order}

    @_tool
    def pin_card(self, ctx: RunContext, component: Any = None, props: Any = None) -> dict[str, Any]:
        """화면 조각을 맨 뒤에 고정한다. props는 **고정하는 그 컴포넌트**의 카탈로그 스키마로 검증한다."""
        if self.cards is None:
            return _err("카드를 고정할 수 없어요.")
        if component not in PINNABLE_COMPONENTS:  # SP6의 새 넷은 그때의 값이라 고정하지 않는다
            return _err(f"고정할 수 있는 화면 조각은 {', '.join(PINNABLE_COMPONENTS)}이에요.")
        if (err := validate_props(component, props)) is not None:
            return _err(f"화면 조각 형식이 맞지 않아요: {err}")
        with transaction(self.cards.conn):
            card = self.cards.pin(component, props, conversation_id=ctx.conversation_id)
            self._card_event(ctx, "card_pinned", card_target(card.id), {"title": card_label(component, props)},
                             {"card_id": card.id})
        return self._card_dict(card)

    @_tool
    def unpin_card(self, ctx: RunContext, id: Any = None) -> dict[str, Any]:
        if self.cards is None:
            return _err("카드 고정을 풀 수 없어요.")
        before = self.cards.get(id) if isinstance(id, int) and not isinstance(id, bool) else None
        if before is None or before.unpinned_at is not None:
            return _err(f"{id}번 고정 카드를 찾을 수 없어요.")
        order = self.cards.order()
        with transaction(self.cards.conn):
            self.cards.unpin(before.id)
            self._card_event(ctx, "card_unpinned", card_target(before.id),
                             {"title": card_label(before.component, before.props)},
                             {"card_id": before.id, "index": order.index(before.id)})
        return {"id": before.id}

    @_tool
    def reorder_cards(self, ctx: RunContext, ids: Any = None) -> dict[str, Any]:
        """새 순서. 고정한 카드 전부를 한 번씩 담아야 한다."""
        if self.cards is None:
            return _err("카드 순서를 바꿀 수 없어요.")
        if not isinstance(ids, list) or any(not isinstance(i, int) or isinstance(i, bool) for i in ids):
            return _err("ids는 카드 번호(숫자) 목록이에요.")
        if not ids:  # 고정 카드가 없을 때도: 바뀐 것 없는 활동을 남기지 않는다
            return _err("순서를 바꿀 고정 카드 번호를 알려 주세요.")
        before = self.cards.order()
        with transaction(self.cards.conn):
            try:
                self.cards.reorder(ids)
            except ValueError:
                return _err("ids에는 고정한 카드 번호를 모두 한 번씩 새 순서로 넣어 주세요.")
            self._card_event(ctx, "cards_reordered", CARDS_ORDER_TARGET, {}, {"order": before})
        return {"ids": self.cards.order()}

    # --- 읽기 도구 ---

    @_tool
    def list_tasks(
        self,
        ctx: RunContext,
        status: Any = None,
        from_: Any = None,
        to: Any = None,
        area: Any = None,
        limit: Any = None,
        **extra: Any,
    ) -> dict[str, Any]:
        """`from`은 파이썬 예약어라 `from_`로도 `from`으로도 받는다."""
        if "from" in extra:
            from_ = extra.pop("from")
        if extra:
            return _err(f"알 수 없는 조건이에요: {', '.join(sorted(extra))}")
        statuses: list[TaskStatus] | None = None
        if status is None:  # 기본: 열린 것만. 초안은 status="draft"로 따로 물을 때만 보인다
            statuses = [TaskStatus.open]
        else:
            try:
                statuses = [TaskStatus(status)]
            except ValueError:
                return _err("status는 draft, open, done, dropped 중 하나예요.")
        d_from = self._parse_date(from_, "from")
        d_to = self._parse_date(to, "to")
        for d in (d_from, d_to):
            if isinstance(d, str):
                return _err(d)
        a: Area | None = None
        if area is not None:
            try:
                a = Area(area)
            except ValueError:
                return _err("알 수 없는 영역이에요.")
        if limit is None:
            n = LIST_LIMIT_DEFAULT
        elif isinstance(limit, int) and not isinstance(limit, bool) and limit >= 1:
            n = min(limit, LIST_LIMIT_MAX)
        else:
            return _err("limit은 1 이상의 숫자예요.")
        found = self.tasks.list(statuses, d_from, d_to, a, n)  # type: ignore[arg-type]
        return {"tasks": [self._task_dict(t) for t in found], "count": len(found)}

    @_tool
    def get_curve(
        self, ctx: RunContext, from_: Any = None, to: Any = None, zoom: Any = "month", **extra: Any
    ) -> dict[str, Any]:
        """6.3.5와 같은 데이터를 짧게: 확정한 것만, 민감 사건은 넣되 제목 대신 "(민감)", 메모(`note`)는 뺀다.
        `from`은 파이썬 예약어라 `from_`로도 `from`으로도 받는다."""
        if "from" in extra:
            from_ = extra.pop("from")
        if extra:
            return _err(f"알 수 없는 조건이에요: {', '.join(sorted(extra))}")
        if self.curve is None or self.conditions is None:
            return _err("곡선을 읽을 수 없어요.")
        zoom = "month" if zoom is None else zoom
        if zoom not in ZOOMS:
            return _err(f"zoom은 {', '.join(ZOOMS)} 가운데 하나예요.")
        d_from = self._parse_date(from_, "from")
        d_to = self._parse_date(to, "to")
        for d in (d_from, d_to):
            if isinstance(d, str):
                return _err(d)
        today = self.today()
        if d_from is None or d_to is None:
            lo, hi = default_range(zoom, today, self.curve.earliest_chapter_start())
            d_from, d_to = d_from or lo, d_to or hi
        assert isinstance(d_from, date) and isinstance(d_to, date)
        if d_from > d_to:
            return _err("from은 to보다 늦을 수 없어요.")
        try:
            body = curve_view(self.curve, self.conditions, zoom=zoom, from_=d_from, to=d_to, include_sensitive=True,
                              today=today)
        except TooManyBuckets:
            return _err("범위를 줄이거나 확대 단위를 키워 주세요.")
        for m in body["milestones"]:
            m.pop("note", None)
            if m["sensitive"]:
                m["title"] = SENSITIVE_MASK
        for x in body["ladder"]:
            x.pop("note", None)
        return body

    @_tool
    def get_status(self, ctx: RunContext) -> dict[str, Any]:
        """6.3.6과 같은 데이터(`status_snapshot`, 민감 사건 칭호는 뺀다). 시각은 현지 시각(두뇌가 받는 도구 결과).

        이룬 순간은 지난 7일(숨긴 것 빼고)만, 통로를 하네스가 고른다(SP8 10.3, D7): 앱 통로(`ctx.channel == "app"`)는
        글이 있는 `Moment`, 그 밖(텔레그램 대화, 회차 차례)은 `[{"date", "count"}]`(날짜와 개수만). 두뇌에게 고르게
        하지 않는다.
        """
        if self.curve is None or self.status is None or self.conditions is None:
            return _err("상태창을 읽을 수 없어요.")
        snap = status_snapshot(
            now=self.clock.now(), tz=self.tz, boundary=self.boundary, status=self.status, curve=self.curve,
            tasks=self.tasks, conditions=self.conditions,
        )
        snap["moments"] = self._brain_moments(ctx)
        del snap["moments_hidden"]  # `GET /status`의 14일 수다. 두뇌에는 지난 7일의 보이는 순간만 준다
        return self._local_times(snap)

    def _brain_moments(self, ctx: RunContext) -> list[dict[str, Any]]:
        if self.moments is None:
            return []
        today = self.today()
        week = self.moments.between(today - timedelta(days=BRAIN_MOMENTS_DAYS - 1), today, include_hidden=False)
        return [moment_dict(m) for m in week] if ctx.channel == "app" else moment_counts(week)

    def _local_times(self, v: Any) -> Any:
        if isinstance(v, dict):
            return {k: self._local_times(x) for k, x in v.items()}
        if isinstance(v, list):
            return [self._local_times(x) for x in v]
        if isinstance(v, datetime):
            return self._local_iso(v)
        return v

    @_tool
    def read_transcript(
        self, ctx: RunContext, from_: Any = None, to: Any = None, **kw: Any
    ) -> dict[str, Any]:
        if "from" in kw:
            from_ = kw.pop("from")
        if kw:
            return _err(f"알 수 없는 조건이에요: {', '.join(sorted(kw))}")
        start = self._parse_date(from_, "from")
        end = self._parse_date(to, "to")
        for d in (start, end):
            if isinstance(d, str):
                return _err(d)
        if start is None or end is None:
            return _err("from과 to를 모두 알려 주세요.")
        if end < start:
            return _err("to는 from보다 같거나 뒤여야 해요.")
        if (end - start) + timedelta(days=1) > timedelta(days=TRANSCRIPT_MAX_DAYS):
            return _err(f"원문 기록은 최대 {TRANSCRIPT_MAX_DAYS}일까지 읽을 수 있어요.")
        # 텔레그램 통로(회차 차례 포함)는 앱 대화의 비서 줄을 받지 않는다: 이룬 순간의 글을 옮겨 말했을 수 있다(SP8 11장)
        text = self.transcripts.read_range(start, end, drop_app_secretary=ctx.channel != "app")
        return {"from": start.isoformat(), "to": end.isoformat(), "text": text}


def _prev_quarter(period: str) -> str:
    year, q = int(period[:4]), int(period[-1])
    return f"{year}-Q{q - 1}" if q > 1 else f"{year - 1}-Q4"


def _ladder_dict(x: Ladder | None) -> dict[str, Any] | None:
    """되돌릴 때 쓸 이전 행(`recorded_at`은 UTC ISO). 메모는 DB의 `undo_json`에만 있고 요약·로그에는 없다."""
    if x is None:
        return None
    return {"now": x.now, "future": x.future, "note": x.note, "recorded_at": to_iso(x.recorded_at)}


def _area_dict(x: AreaScore | None) -> dict[str, Any] | None:
    if x is None:
        return None
    return {"score": x.score, "note": x.note, "recovery_quest": x.recovery_quest, "recorded_at": to_iso(x.recorded_at)}


def _milestone_dict(m: Any) -> dict[str, Any]:
    return {"id": m.id, "date": m.date_text, "kind": m.kind, "title": m.title, "sensitive": m.sensitive,
            "chapter_id": m.chapter_id, "status": m.status}


def _chapter_dict(c: Any) -> dict[str, Any]:
    return {"id": c.id, "title": c.title, "start": c.start_month, "end": c.end_month, "status": c.status}


# --- 종류별 되돌리기 (SP3-4 스펙 6.4.3). `undo`는 그 활동의 `undo_json`(바꾸기 전 값, 시각은 UTC ISO) ---


def _dt(v: Any) -> datetime | None:
    return from_iso(v) if v else None


def _undo_task_added(tools: Tools, undo: dict[str, Any], ctx: RunContext) -> str | None:
    """소프트 삭제(`deleted_at` = 지금). 상태와 완료 시각은 그대로 둔다."""
    t = tools.tasks.get(undo["task_id"])
    if t is not None:
        tools.tasks.restore(t.id, status=t.status, completed_at=t.completed_at, deleted_at=tools.clock.now())
    return None


def _undo_task_updated(tools: Tools, undo: dict[str, Any], ctx: RunContext) -> str | None:
    """바뀐 필드만 이전 값으로."""
    before: dict[str, Any] = undo["before"]
    changes: dict[str, Any] = {k: before[k] for k in ("title", "note", "areas") if k in before}
    if "planned_for" in before:
        changes["planned_for"] = date.fromisoformat(before["planned_for"]) if before["planned_for"] else None
    if "scheduled_at" in before:
        changes["scheduled_at"] = _dt(before["scheduled_at"])
    tools.tasks.update(undo["task_id"], **changes)
    return None


def _undo_task_moved(tools: Tools, undo: dict[str, Any], ctx: RunContext) -> str | None:
    pf = undo["planned_for"]
    tools.tasks.update(
        undo["task_id"], event_kind="moved", planned_for=date.fromisoformat(pf) if pf else None,
        scheduled_at=_dt(undo["scheduled_at"]),
    )
    return None


def _undo_task_status(tools: Tools, undo: dict[str, Any], ctx: RunContext) -> str | None:
    """완료·다시 열기·내려놓기: 이전 상태와 이전 `completed_at` 그대로. 내려놓기로 지워진 우선순위 칸은 비어 있을
    때만 되살리고, 차 있으면 `superseded`(쓴 것은 바깥이 되돌린다)."""
    tid = undo["task_id"]
    tools.tasks.restore(tid, status=undo["status"], completed_at=_dt(undo["completed_at"]), deleted_at=None)
    for cadence, period, rank in undo.get("priorities", []):
        if not tools.tasks.restore_priority(cadence, period, rank, tid):
            return SUPERSEDED
    return None


def _undo_tasks_confirmed(tools: Tools, undo: dict[str, Any], ctx: RunContext) -> str | None:
    """확정한 할 일 가운데 아직 `open`이고 나중 변경이 없는 것만 `draft`로(일부 되돌리기, 6.4.3). 나머지는 그대로.

    `proposed` 이벤트를 새로 써서 초안 만료 시계가 되돌린 시각부터 다시 센다. 하나도 못 돌리면 superseded.
    """
    live = set(undo["targets"])
    reverted: list[Task] = []
    for i in undo["task_ids"]:
        t = tools.tasks.get(i)
        if task_target(i) in live and t is not None and t.status is TaskStatus.open:
            tools.tasks.restore(t.id, status=TaskStatus.draft, completed_at=None, deleted_at=None)
            reverted.append(t)
    undo["targets"] = [task_target(t.id) for t in reverted]
    if not reverted:
        return SUPERSEDED
    # 확인 문구는 실제로 되돌린 할 일만 적는다(확정 때와 같은 모양: 하나면 `✓ 확정: 제목`, 여럿이면 제목 목록)
    undo["summary"] = (
        f"✓ 확정: {reverted[0].title}" if len(reverted) == 1 else titles_summary("확정", [t.title for t in reverted])
    )
    return None


def _undo_priorities_set(tools: Tools, undo: dict[str, Any], ctx: RunContext) -> str | None:
    """이전 목록으로. 이전 목록의 할 일 가운데 지워졌거나, 내려놓았거나, 그 목록 변경 뒤에 상태가 바뀐 것이 있으면
    superseded. 그때 이미 `done`이던 할 일은 그대로 되살린다(완료한 할 일이 목록에 남는 것은 정상이다).
    U3은 목록 대상만 본다(할 일 대상은 지켜보기만 한다)."""
    ids = list(undo["task_ids"])
    statuses = undo.get("statuses")  # 티켓 05 전 행에는 없다: 그때는 `open`이었다고 본다(set_priorities 규칙)
    for k, i in enumerate(ids):
        t = tools.tasks.get(i)
        then = statuses[k] if isinstance(statuses, list) and k < len(statuses) else TaskStatus.open.value
        if t is None or t.status is TaskStatus.dropped or t.status.value != then:
            return SUPERSEDED
    tools.tasks.set_priorities(undo["cadence"], undo["period"], ids)
    return None


def _undo_condition_recorded(tools: Tools, undo: dict[str, Any], ctx: RunContext) -> str | None:
    """이전 행 그대로(`recorded_at` 포함). 없었으면 행을 지운다."""
    d = date.fromisoformat(undo["date"])
    b = undo["before"]
    before = Condition(d, b["score"], b["note"], from_iso(b["recorded_at"])) if b else None
    tools.conditions.restore(d, before)
    return None


def _undo_card_pinned(tools: Tools, undo: dict[str, Any], ctx: RunContext) -> str | None:
    """고정을 푼다(행은 남긴다). 다른 카드의 순서는 그대로다."""
    assert tools.cards is not None
    tools.cards.unpin(undo["card_id"])
    return None


def _undo_card_unpinned(tools: Tools, undo: dict[str, Any], ctx: RunContext) -> str | None:
    """다시 고정하고 풀기 전 자리(지금 순서의 그 번째)에 넣는다."""
    assert tools.cards is not None
    c = tools.cards.get(undo["card_id"])
    if c is None:
        return SUPERSEDED
    order = tools.cards.order()
    tools.cards.restore(Card(c.id, c.component, c.props, c.sort_order, c.pinned_at, None, c.conversation_id))
    order.insert(min(int(undo["index"]), len(order)), c.id)
    tools.cards.restore_order(order)
    return None


def _undo_cards_reordered(tools: Tools, undo: dict[str, Any], ctx: RunContext) -> str | None:
    """이전 순서로. 그 뒤에 고정을 푼 카드는 빼고, 그 뒤에 고정한 카드는 지금 순서대로 맨 뒤에 둔다."""
    assert tools.cards is not None
    now = tools.cards.order()
    before = [i for i in undo["order"] if i in now]
    tools.cards.restore_order([*before, *(i for i in now if i not in before)])
    return None


def _undo_ladder_recorded(tools: Tools, undo: dict[str, Any], ctx: RunContext) -> str | None:
    """이전 행 그대로(`recorded_at` 포함). 없었으면 지운다."""
    assert tools.curve is not None
    b = undo["before"]
    period = undo["period"]
    before = Ladder(period, b["now"], b["future"], b["note"], from_iso(b["recorded_at"])) if b else None
    tools.curve.restore_ladder(period, before)
    return None


def _undo_area_scores_recorded(tools: Tools, undo: dict[str, Any], ctx: RunContext) -> str | None:
    """영역마다 이전 행 그대로, 없었으면 지운다."""
    assert tools.curve is not None
    period = undo["period"]
    before = {
        area: AreaScore(period, area, b["score"], b["note"], b["recovery_quest"], from_iso(b["recorded_at"])) if b else None
        for area, b in undo["before"].items()
    }
    tools.curve.restore_area_scores(period, before)
    return None


def _undo_milestones_confirmed(tools: Tools, undo: dict[str, Any], ctx: RunContext) -> str | None:
    """초안으로, `draft_since` = 되돌린 시각(3일을 다시 센다). 칭호도 지운다(칭호는 원장이 아니다)."""
    assert tools.curve is not None and tools.status is not None
    now = tools.clock.now()
    for i in undo["milestone_ids"]:
        tools.status.remove_title(i)
        tools.curve.unconfirm_milestone(i, now)
    return None


def _undo_chapters_confirmed(tools: Tools, undo: dict[str, Any], ctx: RunContext) -> str | None:
    assert tools.curve is not None
    now = tools.clock.now()
    for i in undo["chapter_ids"]:
        tools.curve.unconfirm_chapter(i, now)
    return None


for _kind, _handler in (
    ("task_added", _undo_task_added),
    ("task_updated", _undo_task_updated),
    ("task_moved", _undo_task_moved),
    ("task_completed", _undo_task_status),
    ("task_reopened", _undo_task_status),
    ("task_dropped", _undo_task_status),
    ("tasks_confirmed", _undo_tasks_confirmed),
    ("priorities_set", _undo_priorities_set),
    ("condition_recorded", _undo_condition_recorded),
    ("card_pinned", _undo_card_pinned),
    ("card_unpinned", _undo_card_unpinned),
    ("cards_reordered", _undo_cards_reordered),
    ("ladder_recorded", _undo_ladder_recorded),
    ("area_scores_recorded", _undo_area_scores_recorded),
    ("milestones_confirmed", _undo_milestones_confirmed),
    ("chapters_confirmed", _undo_chapters_confirmed),
):
    register_undo(_kind, _handler)
