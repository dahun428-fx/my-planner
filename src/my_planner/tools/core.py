"""도구 함수 (스펙 5.5). 메서드는 `(ctx, **inputs) -> dict`이고 잘못된 입력은 `{"error": "…"}`로 돌려준다.

변경 도구는 데이터 변경, `tool_events_log`, `activity`(SP3-4 스펙 5.2)를 같은 트랜잭션에서 쓰고, `ctx.events`에
이벤트를 쌓고, `tasks.md`를 다시 만든다. 로그에는 제목이나 인자를 남기지 않는다.
"""

from __future__ import annotations

import functools
import logging
import re
from collections.abc import Callable
from datetime import date, datetime, time, timedelta, tzinfo
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from my_planner.clock import Clock, from_iso, local, logical_date, to_iso
from my_planner.domain import Area, Cadence, RunContext, TaskStatus, ToolEvent
from my_planner.store.db import transaction
from my_planner.store.exports import export_tasks
from my_planner.store.repos.conditions import Condition
from my_planner.store.repos.tasks import Task, TasksRepo
from my_planner.store.transcripts import TranscriptStore
from my_planner.tools.activity import (
    SUPERSEDED,
    condition_target,
    priorities_target,
    record_activity,
    register_undo,
    task_target,
    tasks_target,
)
from my_planner.tools.confirmations import (
    condition_summary,
    confirmation_line,
    drafts_expired_summary,
    titles_summary,
)

log = logging.getLogger(__name__)

TITLE_MAX = 200
LIST_LIMIT_MAX = 50
LIST_LIMIT_DEFAULT = 20
TRANSCRIPT_MAX_DAYS = 7
PRIORITY_MAX = 3
SCORE_MIN, SCORE_MAX = 1, 5  # 컨디션 점수
_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")  # fromisoformat은 20261023, 2026-W43-5도 받는다
PROPOSE_MAX = 10  # 한 번에 제안하는 초안 수. 버튼 줄이 너무 길어지지 않게
_NEW_FIELDS = {"title", "areas", "planned_for", "scheduled_at", "parent_id", "note"}
PERIOD_EXAMPLE = {
    Cadence.day: "2026-10-23",
    Cadence.week: "2026-W43",
    Cadence.month: "2026-10",
    Cadence.quarter: "2026-Q4",
    Cadence.year: "2026",
}


def _err(msg: str) -> dict[str, Any]:
    return {"error": msg}


def _tool(fn: Callable[..., dict[str, Any]]) -> Callable[..., dict[str, Any]]:
    """부른 도구 이름(인자 없이)을 `ctx.tool_names`에 남긴다. 원문 기록의 `> 도구:` 줄과 로그가 쓴다."""

    @functools.wraps(fn)
    def wrapper(self: Tools, ctx: RunContext, *args: Any, **kwargs: Any) -> dict[str, Any]:
        ctx.tool_names.append(fn.__name__)
        return fn(self, ctx, *args, **kwargs)

    return wrapper


class Tools:
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
    ) -> None:
        self.tasks = tasks
        self.transcripts = transcripts
        self.export_path = Path(export_path)
        self.clock = clock
        self.tz = ZoneInfo(tz) if isinstance(tz, str) else tz
        self.boundary = boundary
        self.conditions = conditions
        self.activity = activity  # `ActivityRepo`. None이면 활동을 남기지 않는다(SP1 시험)

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
        try:
            export_tasks(self.tasks, self.export_path, self.today())
        except OSError as e:  # 데이터는 이미 저장됐다. 내보내기는 다음 변경 때 다시 만든다.
            log.warning("export_failed", extra={"error_type": type(e).__name__})

    def _get(self, id: Any) -> Task | str:
        t = self.tasks.get(id) if isinstance(id, int) and not isinstance(id, bool) else None
        return t if t is not None else f"{id}번 할 일을 찾을 수 없어요."

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
        extra: list[str] = []
        if new is TaskStatus.dropped:  # 내려놓으면 우선순위 칸이 지워진다. 비어 있으면 되살린다(6.4.3)
            rows = self.tasks.priority_rows(t.id)
            undo["priorities"] = [list(row) for row in rows]
            extra = [priorities_target(c, p) for c, p, _ in rows]  # 그 목록도 바뀐 대상이다
        with self.tasks.transaction():
            t = self.tasks.set_status(t.id, new)
            out = self._finish(ctx, kind, t, undo=undo, extra=extra)
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
        before = [t.id for _, t in self.tasks.priority_ranks(c, period)]
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
                {"cadence": c.value, "period": period, "task_ids": before},
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
        text = self.transcripts.read_range(start, end)
        return {"from": start.isoformat(), "to": end.isoformat(), "text": text}


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
    reverted: list[str] = []
    for i in undo["task_ids"]:
        t = tools.tasks.get(i)
        if task_target(i) in live and t is not None and t.status is TaskStatus.open:
            tools.tasks.restore(t.id, status=TaskStatus.draft, completed_at=None, deleted_at=None)
            reverted.append(task_target(i))
    undo["targets"] = reverted
    return None if reverted else SUPERSEDED


def _undo_priorities_set(tools: Tools, undo: dict[str, Any], ctx: RunContext) -> str | None:
    """이전 목록으로. 이전 목록의 할 일이 지금도 목록에 오를 수 있어야 한다(`set_priorities`와 같은 규칙: 있고,
    지워지지 않았고, `open`). 하나라도 아니면 superseded. U3은 목록 대상만 본다(할 일 대상은 지켜보기만 한다)."""
    ids = list(undo["task_ids"])
    for i in ids:
        t = tools.tasks.get(i)
        if t is None or t.status is not TaskStatus.open:
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
):
    register_undo(_kind, _handler)
