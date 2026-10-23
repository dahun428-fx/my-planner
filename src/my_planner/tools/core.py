"""도구 함수 (스펙 5.5). 메서드는 `(ctx, **inputs) -> dict`이고 잘못된 입력은 `{"error": "…"}`로 돌려준다.

변경 도구는 데이터 변경과 `tool_events_log`를 같은 트랜잭션에서 쓰고, `ctx.events`에 이벤트를 쌓고,
`tasks.md`를 다시 만든다. 로그에는 제목이나 인자를 남기지 않는다.
"""

from __future__ import annotations

import functools
import logging
from collections.abc import Callable
from datetime import date, datetime, time, timedelta, tzinfo
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from my_planner.clock import Clock, local, logical_date
from my_planner.domain import Area, Cadence, RunContext, TaskStatus, ToolEvent
from my_planner.store.exports import export_tasks
from my_planner.store.repos.tasks import Task, TasksRepo
from my_planner.store.transcripts import TranscriptStore

log = logging.getLogger(__name__)

TITLE_MAX = 200
LIST_LIMIT_MAX = 50
LIST_LIMIT_DEFAULT = 20
TRANSCRIPT_MAX_DAYS = 7
PRIORITY_MAX = 3
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
    ) -> None:
        self.tasks = tasks
        self.transcripts = transcripts
        self.export_path = Path(export_path)
        self.clock = clock
        self.tz = ZoneInfo(tz) if isinstance(tz, str) else tz
        self.boundary = boundary
        self.conditions = conditions

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

    def _finish(self, ctx: RunContext, kind: str, t: Task) -> dict[str, Any]:
        """트랜잭션 안에서 부른다: 호출 기록. 끝난 뒤 `_after`를 부른다."""
        self.tasks.log_tool_event(ctx.run_id, ctx.conversation_id, t.id, kind)
        return self._task_dict(t)

    def _after(self, ctx: RunContext, kind: str, t: Task) -> None:
        ctx.events.append(ToolEvent(kind=kind, task_id=t.id, data=self._event_data(t)))
        try:
            export_tasks(self.tasks, self.export_path, self.today())
        except OSError as e:  # 데이터는 이미 저장됐다. 내보내기는 다음 변경 때 다시 만든다.
            log.warning("export_failed", extra={"error_type": type(e).__name__})

    def _get(self, id: Any) -> Task | str:
        t = self.tasks.get(id) if isinstance(id, int) and not isinstance(id, bool) else None
        return t if t is not None else f"{id}번 할 일을 찾을 수 없어요."

    # --- 변경 도구 ---

    @_tool
    def add_task(
        self,
        ctx: RunContext,
        title: Any = None,
        areas: Any = None,
        planned_for: Any = None,
        scheduled_at: Any = None,
        parent_id: Any = None,
        note: Any = None,
    ) -> dict[str, Any]:
        if (m := self._check_title(title)) is not None:
            return _err(m)
        checked_areas = self._check_areas(areas)
        if isinstance(checked_areas, str):
            return _err(checked_areas)
        pf = self._parse_date(planned_for, "planned_for")
        if isinstance(pf, str):
            return _err(pf)
        sa = self._parse_dt(scheduled_at)
        if isinstance(sa, str):
            return _err(sa)
        if parent_id is not None and (
            not isinstance(parent_id, int) or self.tasks.get(parent_id) is None
        ):
            return _err(f"{parent_id}번 할 일이 없어서 첫 걸음으로 붙일 수 없어요.")
        if pf is None and sa is not None:  # 시각만 주면 그 날이 하려는 날이다
            pf = logical_date(sa, self.tz, self.boundary)
        with self.tasks.transaction():
            t = self.tasks.create(
                title.strip(),
                checked_areas,
                TaskStatus.open,
                pf,
                sa,
                parent_id,
                note if isinstance(note, str) else "",
            )
            out = self._finish(ctx, "task_added", t)
        self._after(ctx, "task_added", t)
        return out

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
        with self.tasks.transaction():
            t = self.tasks.update(t.id, **changes)
            out = self._finish(ctx, "task_updated", t)
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
        with self.tasks.transaction():
            t = self.tasks.update(t.id, event_kind="moved", **changes)
            out = self._finish(ctx, "task_moved", t)
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
        with self.tasks.transaction():
            t = self.tasks.set_status(t.id, new)
            out = self._finish(ctx, kind, t)
        self._after(ctx, kind, t)
        return out

    @_tool
    def complete_task(self, ctx: RunContext, id: Any = None) -> dict[str, Any]:
        return self._set_status(
            ctx, id, TaskStatus.done, "task_completed", {TaskStatus.open}, "열린 할 일만 완료로 바꿀 수 있어요."
        )

    @_tool
    def reopen_task(self, ctx: RunContext, id: Any = None) -> dict[str, Any]:
        return self._set_status(
            ctx,
            id,
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
        with self.tasks.transaction():
            self.tasks.set_priorities(c, period, ids)
            self.tasks.log_tool_event(ctx.run_id, ctx.conversation_id, None, "priorities_set")
            picked = self.tasks.priorities(c, period)
        ctx.events.append(
            ToolEvent(
                kind="priorities_set",
                task_id=None,
                data={"cadence": c.value, "period": period, "titles": [t.title for t in picked]},
            )
        )
        return {"cadence": c.value, "period": period, "priorities": [self._task_dict(t) for t in picked]}

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
        statuses: list[TaskStatus] | None = None  # 기본: 열린 것과 초안
        if status is None:
            statuses = [TaskStatus.open, TaskStatus.draft]
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
