"""습관 도구 (SP7 스펙 5.3, 5.4 규칙 H1~H7, 5.5 되돌리기, 5.6 X11). `Tools`가 이 mixin을 상속한다.

변경 도구는 습관 데이터, `activity`, 경험치 원장을 한 트랜잭션에서 쓴다(규칙 H5). 추가·고치기·상태는 할 일 도구처럼
`tool_events_log`에도 쓰고, 체크·취소는 `record_condition`처럼 쓰지 않는다. 로그에는 습관 id와 결과만 남긴다(8장).
"""

from __future__ import annotations

import logging
import re
from datetime import date, timedelta
from typing import TYPE_CHECKING, Any

from my_planner.domain import Area, EventKind, InboxAgent, RunContext, ToolEvent
from my_planner.status.xp import LABEL_HABIT_CHECK, XP_HABIT_CHECK
from my_planner.store.db import transaction
from my_planner.store.exports import export_habits
from my_planner.store.repos.habits import Habit, HabitsRepo
from my_planner.store.views import habit_dict, habits_view
from my_planner.tools._base import _err, _tool
from my_planner.tools.activity import (
    SUPERSEDED,
    habit_day_target,
    habit_target,
    register_undo,
)
from my_planner.tools.confirmations import (
    confirm_button_habit_archive,
    confirm_button_habit_update,
    confirm_habit_archive_summary,
    confirm_habit_edit_summary,
    confirm_habit_rename_summary,
    confirm_habit_update_summary,
    habit_kind_label,
    habit_line,
)

if TYPE_CHECKING:
    from pathlib import Path

    from my_planner.clock import Clock
    from my_planner.store.repos.tasks import TasksRepo
    from my_planner.tools.core import Tools

log = logging.getLogger(__name__)

HABIT_TITLE_MAX = 40
HABIT_ACTIVE_MAX = 10  # 활성 습관 상한(5.1). `active`만 센다
HABIT_TARGET_MIN, HABIT_TARGET_MAX = 1, 6
HABIT_DAYS = 7  # 오늘 포함 7일만 체크·취소(5.3)
HABIT_KINDS = ("daily", "weekly")
HABIT_STATUSES = ("active", "paused", "archived")
_LIVE = ("active", "paused")  # 같은 제목을 막는 상태(규칙 H3)
_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")

# 부록 A
MSG_CAP = "습관은 한 번에 10개까지 챙길 수 있어요. 하나를 쉬어 가거나 그만두면 더할 수 있어요."
MSG_DUPLICATE = "이미 있는 습관이에요."
MSG_FUTURE = "아직 오지 않은 날은 체크할 수 없어요."
MSG_RANGE = "오늘 포함 7일 안의 날만 체크할 수 있어요."
MSG_PAUSED = "쉬는 중인 습관이에요. 다시 시작하면 체크할 수 있어요."
MSG_TARGET = "주 몇 번인지 1~6으로 알려 주세요. 매일이면 매일 습관으로 만들어요."
MSG_RUN_TURN = "사용자가 말한 습관만 체크할 수 있어요."
MSG_NOT_FOUND = "없는 습관이에요."
# SP1 도구와 같은 방식의 입력 오류(규칙 H1)
MSG_NO_HABITS = "습관을 다룰 수 없어요."
MSG_TITLE_EMPTY = "제목이 비어 있어요."
MSG_TITLE_LONG = f"제목은 {HABIT_TITLE_MAX}자까지 쓸 수 있어요."
MSG_KIND = "kind는 daily, weekly 중 하나예요."
MSG_STATUS = "status는 active, paused, archived 중 하나예요."
MSG_LIST_STATUS = "status는 active, paused, archived, all 중 하나예요."
MSG_DATE = "date는 YYYY-MM-DD 형식으로 알려 주세요."
MSG_NOTHING = "바꿀 내용을 알려 주세요."


def _is_int(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _parse_day(v: Any) -> date:
    """`YYYY-MM-DD`만 받는다(`fromisoformat`은 20261023, 2026-W43-5도 받는다). 틀리면 `ValueError`."""
    if not (isinstance(v, str) and _ISO_DATE.fullmatch(v)):
        raise ValueError(MSG_DATE)
    try:
        return date.fromisoformat(v)
    except ValueError:
        raise ValueError(MSG_DATE) from None


class HabitTools:
    """습관 도구 여섯 개. `Tools`의 공통 부품(`today`, `_record`, `_request_confirm`, `_export`)을 쓴다."""

    habits: HabitsRepo | None

    if TYPE_CHECKING:
        tasks: TasksRepo
        status: Any
        clock: Clock
        habits_export_path: Path

        def today(self) -> date: ...
        def _record(self, ctx: RunContext, kind: str, target: str | None, summary: str | None,
                    undo: dict[str, Any] | None, *, targets: list[str] | None = None) -> None: ...
        def _confirm_first(self, ctx: RunContext) -> bool: ...
        def _agent_event(self, ctx: RunContext, kind: EventKind, ref: str, area: str | None = None, *,
                         handoff_to: InboxAgent | None = None) -> None: ...
        def _request_confirm(self, ctx: RunContext, action: str, args: dict[str, Any], summary: str,
                             button: str) -> dict[str, Any]: ...
        def _export(self) -> None: ...

    # --- 공통 ---

    def _habit(self, id: Any) -> Habit | str:
        """습관 또는 오류 문구. 소프트 삭제된 습관은 없는 습관이다(규칙 H3)."""
        assert self.habits is not None
        h = self.habits.get(id) if _is_int(id) else None
        return h if h is not None else MSG_NOT_FOUND

    @staticmethod
    def _habit_title(v: Any) -> str:
        """앞뒤 공백을 뺀 제목, 틀리면 오류 문구를 `ValueError`로."""
        if not isinstance(v, str) or not v.strip():
            raise ValueError(MSG_TITLE_EMPTY)
        t = v.strip()
        if len(t) > HABIT_TITLE_MAX:
            raise ValueError(MSG_TITLE_LONG)
        return t

    @staticmethod
    def _habit_area(v: Any) -> Area:
        try:
            return Area(v)
        except ValueError:
            names = ", ".join(x.value for x in Area)
            raise ValueError(f"알 수 없는 영역이에요. 쓸 수 있는 영역: {names}") from None

    @staticmethod
    def _habit_kind(kind: Any, target: Any) -> tuple[str, int | None]:
        """(주기, 주 목표). 규칙 H2: 매일 습관에 목표가 오거나, 주 N회 습관에 1~6이 없으면 거절."""
        if kind not in HABIT_KINDS:
            raise ValueError(MSG_KIND)
        if kind == "daily":
            if target is not None:
                raise ValueError(MSG_TARGET)
            return "daily", None
        if not _is_int(target) or not HABIT_TARGET_MIN <= target <= HABIT_TARGET_MAX:
            raise ValueError(MSG_TARGET)
        return "weekly", target

    def _duplicate(self, title: str, own: int | None = None) -> bool:
        """같은 제목의 활성·쉬는 습관이 (자기 말고) 있다(규칙 H3)."""
        assert self.habits is not None
        other = self.habits.find_by_title(title, _LIVE)
        return other is not None and other.id != own

    def _habit_out(self, h: Habit, day: date | None = None) -> dict[str, Any]:
        """공통 `Habit` 모양(5.5): 그 날짜(기본 오늘)의 체크 여부와 그 ISO 주의 체크 수."""
        assert self.habits is not None
        d = day if day is not None else self.today()
        monday = d - timedelta(days=d.weekday())
        return habit_dict(
            h, checked=h.id in self.habits.checked_on(d), week_count=self.habits.week_counts(monday).get(h.id, 0)
        )

    @staticmethod
    def _habit_data(h: Habit, label: str | None = None, day: date | None = None) -> dict[str, Any]:
        """ToolEvent 데이터(확인 문구를 다시 만든다)."""
        return {"habit_id": h.id, "title": h.title, "label": label, "date": day.isoformat() if day else None}

    def _habit_change(
        self, ctx: RunContext, kind: str, h: Habit, undo: dict[str, Any], *, label: str | None,
    ) -> ToolEvent:
        """트랜잭션 안에서: 호출 기록(`tool_events_log`)과 활동. 추가·고치기·상태가 쓴다(규칙 H5)."""
        data = self._habit_data(h, label)
        self.tasks.log_tool_event(ctx.run_id, ctx.conversation_id, None, kind, inbound_id=ctx.inbound_id, data=data)
        summary = habit_line(kind, h.title, label=label, today=self.today())
        self._record(ctx, kind, habit_target(h.id), summary, undo)
        return ToolEvent(kind, None, data)

    def _grant_habit(self, ctx: RunContext, h: Habit, d: date) -> None:
        """X11(5.6): 습관·날짜마다 한 번. `logical_date`는 체크한 날짜, `at`은 지금. 라벨에 제목은 넣지 않는다.
        상태창 저장소가 없으면(SP1 시험) 쌓지 않는다."""
        if self.status is None:
            return
        self.status.grant(
            at=self.clock.now(), logical_date=d, source_kind="habit_check", source_ref=habit_day_target(h.id, d),
            amount=XP_HABIT_CHECK, label=LABEL_HABIT_CHECK, area=h.area.value, gain=ctx.xp,
        )

    def _export_habits(self) -> None:
        """`habits.md`(5.8). `Tools._export`가 부른다. 습관 저장소가 없으면 만들지 않는다."""
        if self.habits is None:
            return
        try:
            export_habits(self.habits, self.habits_export_path, self.today())
        except OSError as e:  # 데이터는 이미 저장됐다. 다음 변경 때 다시 만든다
            log.warning("habits_export_failed", extra={"error_type": type(e).__name__})

    # --- 변경 도구 ---

    @_tool
    def add_habit(
        self, ctx: RunContext, title: Any = None, area: Any = None, kind: Any = None, target_per_week: Any = None,
    ) -> dict[str, Any]:
        """사용자가 직접 추가해 달라고 한 습관만(5.4). 같은 제목(규칙 H3)과 상한 10개를 거절한다."""
        if self.habits is None:
            return _err(MSG_NO_HABITS)
        if ctx.run_turn:  # 규칙 H6: 비서가 스스로 꺼낸 습관은 말로 제안만 한다
            return _err(MSG_RUN_TURN)
        try:
            t = self._habit_title(title)
            a = self._habit_area(area)
            k, n = self._habit_kind(kind, target_per_week)
        except ValueError as e:
            return _err(str(e))
        if self._duplicate(t):
            return _err(MSG_DUPLICATE)
        if self.habits.count_active() >= HABIT_ACTIVE_MAX:
            return _err(MSG_CAP)
        with transaction(self.habits.conn):
            h = self.habits.add(t, a, k, n, self.clock.now())
            event = self._habit_change(ctx, "habit_added", h, {"habit_id": h.id}, label=habit_kind_label(k, n))
        ctx.events.append(event)
        log.info("habit_added", extra={"habit_id": h.id})
        self._export()
        return self._habit_out(h)

    @_tool
    def update_habit(
        self, ctx: RunContext, id: Any = None, title: Any = None, area: Any = None, kind: Any = None,
        target_per_week: Any = None,
    ) -> dict[str, Any]:
        """제목, 영역, 주기, 주 목표를 고친다. 주기를 매일로 바꾸면 목표는 지운다. 바꾼 필드의 이전 값을 남긴다."""
        if self.habits is None:
            return _err(MSG_NO_HABITS)
        h = self._habit(id)
        if isinstance(h, str):
            return _err(h)
        if title is None and area is None and kind is None and target_per_week is None:
            return _err(MSG_NOTHING)
        changes: dict[str, Any] = {}
        try:
            if title is not None:
                changes["title"] = self._habit_title(title)
            if area is not None:
                changes["area"] = self._habit_area(area).value
            if kind is not None or target_per_week is not None:
                new_kind = kind if kind is not None else h.kind
                # 주 N회 습관을 주 N회로 두고 목표만 바꾸지 않으면 지금 목표를 그대로 쓴다
                target = target_per_week if target_per_week is not None or new_kind == "daily" else h.target_per_week
                changes["kind"], changes["target_per_week"] = self._habit_kind(new_kind, target)
        except ValueError as e:
            return _err(str(e))
        if "title" in changes and self._duplicate(changes["title"], own=h.id):
            return _err(MSG_DUPLICATE)
        prior = {"title": h.title, "area": h.area.value, "kind": h.kind, "target_per_week": h.target_per_week}
        changes = {k: v for k, v in changes.items() if v != prior[k]}
        before = {k: prior[k] for k in changes}  # 바뀐 필드의 이전 값만
        if not changes:  # 바뀌는 것이 없으면 아무것도 쓰지 않는다(`set_habit_status`의 같은 상태와 같다)
            return {**self._habit_out(h), "already": True}
        if self._confirm_first(ctx):  # 규칙 H7
            given = {"title": title, "area": area, "kind": kind, "target_per_week": target_per_week}
            args = {"id": h.id, **{k: v for k, v in given.items() if v is not None}}
            if "title" in args:
                args["title"] = changes.get("title", h.title)
            if "kind" in changes or "target_per_week" in changes:  # 주기가 바뀔 때만 주기 문구
                summary = confirm_habit_update_summary(
                    changes.get("title", h.title),
                    habit_kind_label(changes.get("kind", h.kind), changes.get("target_per_week", h.target_per_week)),
                )
            elif set(changes) == {"title"}:
                summary = confirm_habit_rename_summary(h.title, changes["title"])
            else:  # 영역만, 또는 제목과 영역
                summary = confirm_habit_edit_summary(changes.get("title", h.title))
            return self._request_confirm(ctx, "update_habit", args, summary, confirm_button_habit_update(h.title))
        with transaction(self.habits.conn):
            h = self.habits.update(h.id, now=self.clock.now(), **changes)
            event = self._habit_change(
                ctx, "habit_updated", h, {"habit_id": h.id, "before": before},
                label=habit_kind_label(h.kind, h.target_per_week),
            )
        ctx.events.append(event)
        log.info("habit_updated", extra={"habit_id": h.id, "fields": sorted(changes)})
        self._export()
        return self._habit_out(h)

    @_tool
    def set_habit_status(self, ctx: RunContext, id: Any = None, status: Any = None) -> dict[str, Any]:
        """쉬어 가기(`paused`), 다시 시작(`active`), 그만두기(`archived`). 다시 시작은 상한과 같은 제목을 본다.
        지금 상태와 같으면 바꾸지 않고 `already`."""
        if self.habits is None:
            return _err(MSG_NO_HABITS)
        h = self._habit(id)
        if isinstance(h, str):
            return _err(h)
        if status not in HABIT_STATUSES:
            return _err(MSG_STATUS)
        if status == h.status:
            return {**self._habit_out(h), "already": True}
        if status == "archived" and self._confirm_first(ctx):  # 규칙 H7. 쉬어 가기는 바로 적용한다
            return self._request_confirm(
                ctx, "set_habit_status", {"id": h.id, "status": "archived"}, confirm_habit_archive_summary(h.title),
                confirm_button_habit_archive(h.title),
            )
        if status == "active":
            if self._duplicate(h.title, own=h.id):
                return _err(MSG_DUPLICATE)
            if self.habits.count_active() >= HABIT_ACTIVE_MAX:
                return _err(MSG_CAP)
        before = h.status
        with transaction(self.habits.conn):
            h = self.habits.set_status(h.id, status, self.clock.now())
            event = self._habit_change(ctx, "habit_status_set", h, {"habit_id": h.id, "status": before}, label=status)
        ctx.events.append(event)
        log.info("habit_status_set", extra={"habit_id": h.id, "status": status})
        self._export()
        return self._habit_out(h)

    def _habit_day(self, id: Any, day: Any) -> tuple[Habit, date] | str:
        """체크·취소의 (습관, 날짜). 날짜 기본은 논리적 오늘, 오늘 포함 7일만, 쉬는·그만둔 습관은 거절(5.3)."""
        h = self._habit(id)
        if isinstance(h, str):
            return h
        today = self.today()
        try:
            d = today if day is None else _parse_day(day)
        except ValueError as e:
            return str(e)
        if d > today:
            return MSG_FUTURE
        if d <= today - timedelta(days=HABIT_DAYS):
            return MSG_RANGE
        if h.status != "active":
            return MSG_PAUSED
        return h, d

    def _check_out(self, h: Habit, d: date, already: bool) -> dict[str, Any]:
        return {"habit": self._habit_out(h, d), "date": d.isoformat(), "already": already}

    @_tool
    def check_habit(self, ctx: RunContext, id: Any = None, date: Any = None) -> dict[str, Any]:
        """그날(기본 오늘) 체크. 이미 체크했으면 바꾸지 않고 `already`. 새로 넣었을 때만 경험치 X11(5.6)."""
        if self.habits is None:
            return _err(MSG_NO_HABITS)
        if ctx.run_turn:  # 규칙 H6: 비서는 습관을 추측해서 체크하지 않는다
            return _err(MSG_RUN_TURN)
        got = self._habit_day(id, date)
        if isinstance(got, str):
            return _err(got)
        h, d = got
        target = habit_day_target(h.id, d)
        with transaction(self.habits.conn):
            new = self.habits.check(h.id, d, self.clock.now())
            if new:
                self._record(
                    ctx, "habit_checked", target, habit_line("habit_checked", h.title, day=d, today=self.today()),
                    {"habit_id": h.id, "date": d.isoformat()},
                )
                self._agent_event(ctx, "habit_checked", habit_target(h.id), h.area.value)
                self._grant_habit(ctx, h, d)
        if new:
            ctx.events.append(ToolEvent("habit_checked", None, self._habit_data(h, day=d)))
            self._export()
        log.info("habit_checked", extra={"habit_id": h.id, "date": d.isoformat(), "already": not new})
        return self._check_out(h, d, not new)

    @_tool
    def uncheck_habit(self, ctx: RunContext, id: Any = None, date: Any = None) -> dict[str, Any]:
        """그날(기본 오늘) 체크 취소. 체크가 없으면 바꾸지 않고 `already`. 경험치는 그대로 둔다(5.6)."""
        if self.habits is None:
            return _err(MSG_NO_HABITS)
        if ctx.run_turn:  # 규칙 H6: 비서는 습관을 추측해서 체크하지 않는다
            return _err(MSG_RUN_TURN)
        got = self._habit_day(id, date)
        if isinstance(got, str):
            return _err(got)
        h, d = got
        with transaction(self.habits.conn):
            checked_at = self.habits.uncheck(h.id, d)
            if checked_at is not None:
                self._record(
                    ctx, "habit_unchecked", habit_day_target(h.id, d),
                    habit_line("habit_unchecked", h.title, day=d, today=self.today()),
                    {"habit_id": h.id, "date": d.isoformat(), "checked_at": checked_at},
                )
        if checked_at is not None:
            ctx.events.append(ToolEvent("habit_unchecked", None, self._habit_data(h, day=d)))
            self._export()
        log.info("habit_unchecked", extra={"habit_id": h.id, "date": d.isoformat(), "already": checked_at is None})
        return self._check_out(h, d, checked_at is None)

    # --- 읽기 도구 ---

    @_tool
    def list_habits(self, ctx: RunContext, status: Any = "active", date: Any = None) -> dict[str, Any]:
        """습관과 그날(기본 오늘) 체크 여부, 그 ISO 주의 체크 수(`GET /habits`와 같은 모양)."""
        if self.habits is None:
            return _err(MSG_NO_HABITS)
        status = "active" if status is None else status
        if status not in (*HABIT_STATUSES, "all"):
            return _err(MSG_LIST_STATUS)
        try:
            d = self.today() if date is None else _parse_day(date)
        except ValueError as e:
            return _err(str(e))
        statuses = HABIT_STATUSES if status == "all" else (status,)
        return habits_view(self.habits, d, statuses)


# --- 되돌리기 (SP7 5.5 표). 5.3의 거절(쉬는 습관, 7일 범위)과 상한 10개는 보지 않고 이전 상태로만 돌린다 ---


def _undo_habit_added(tools: Tools, undo: dict[str, Any], ctx: RunContext) -> str | None:
    """소프트 삭제. 체크가 하나라도 있거나 이미 없는 습관이면 superseded."""
    assert tools.habits is not None
    hid = undo["habit_id"]
    if tools.habits.get(hid) is None or tools.habits.has_checks(hid):
        return SUPERSEDED
    tools.habits.soft_delete(hid, tools.clock.now())
    return None


def _undo_habit_updated(tools: Tools, undo: dict[str, Any], ctx: RunContext) -> str | None:
    assert tools.habits is not None
    tools.habits.update(undo["habit_id"], now=tools.clock.now(), **undo["before"])
    return None


def _undo_habit_status_set(tools: Tools, undo: dict[str, Any], ctx: RunContext) -> str | None:
    """이전 상태로. `active`로 돌아가도 상한은 보지 않는다(잠깐 11개가 될 수 있다)."""
    assert tools.habits is not None
    tools.habits.set_status(undo["habit_id"], undo["status"], tools.clock.now())
    return None


def _undo_habit_checked(tools: Tools, undo: dict[str, Any], ctx: RunContext) -> str | None:
    """체크 행을 지운다. 습관이 지워졌으면(되돌린 추가) superseded."""
    assert tools.habits is not None
    if tools.habits.get(undo["habit_id"]) is None:
        return SUPERSEDED
    tools.habits.uncheck(undo["habit_id"], date.fromisoformat(undo["date"]))
    return None


def _undo_habit_unchecked(tools: Tools, undo: dict[str, Any], ctx: RunContext) -> str | None:
    """이전 `checked_at` 그대로 되살린다. 습관이 지워졌으면(되돌린 추가) 고아 행을 만들지 않고 superseded."""
    assert tools.habits is not None
    if tools.habits.get(undo["habit_id"]) is None:
        return SUPERSEDED
    tools.habits.restore_check(undo["habit_id"], date.fromisoformat(undo["date"]), undo["checked_at"])
    return None


for _kind, _handler in (
    ("habit_added", _undo_habit_added),
    ("habit_updated", _undo_habit_updated),
    ("habit_status_set", _undo_habit_status_set),
    ("habit_checked", _undo_habit_checked),
    ("habit_unchecked", _undo_habit_unchecked),
):
    register_undo(_kind, _handler)
