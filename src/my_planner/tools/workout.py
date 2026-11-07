"""운동메이트 도구 (SP12 스펙 5.3, 6장 몸 메모, 7장 플랜, 8장 기록, 10장 X13). `Tools`가 이 mixin을 상속한다.

메이트 대화의 두뇌만 부른다(`MATE_TOOLS`). 앱 운동 화면의 지우기(`drop_body_note`, `delete_workout_log`)는 `/actions`.
칸마다의 값 검증(7.3 표, 8.1 CHECK 범위)은 여기서 하고, 하나라도 틀리면 아무것도 쓰지 않는다.

- 몸 메모 더하기·고치기는 조용히(6.3): 활동·확인 문구·경험치가 없다. 저장 전에 `redact`를 한 번 더 건다(6.2).
- 플랜은 통째로 바꾼다(7.2). 모든 `workout_plan_set` 활동은 공통 대상 `workout_plan:current`를 적으므로 U3가 가장 최근
  변경 하나만 되돌리게 한다(`U3_PER_TARGET`에 넣지 않는다).
- 활동 `actor`는 메이트도 `secretary`다(8.2). 로그에는 id·개수만 남긴다: 메모 글, 기록 숫자는 넣지 않는다(14장).
"""

from __future__ import annotations

import logging
import re
from dataclasses import asdict
from datetime import date, timedelta
from typing import TYPE_CHECKING, Any

from my_planner.domain import EventKind, InboxAgent, RunContext, ToolEvent
from my_planner.harness.mate_context import (
    build_mate_preamble,
    trace_dict,
    workout_traces,
)
from my_planner.harness.redact import redact
from my_planner.status.xp import LABEL_WORKOUT_LOG, XP_WORKOUT_LOG
from my_planner.store.db import transaction
from my_planner.store.repos.workout import LogItem, PlanItem
from my_planner.tools._base import _err, _tool
from my_planner.tools.activity import SUPERSEDED, register_undo
from my_planner.tools.confirmations import confirm_workout_log_delete_summary

if TYPE_CHECKING:
    from datetime import time

    from my_planner.clock import Clock
    from my_planner.store.repos.activity import ConfirmsRepo
    from my_planner.store.repos.tasks import TasksRepo
    from my_planner.store.repos.workout import BodyNote, Plan, WorkoutLog, WorkoutRepo
    from my_planner.tools.core import Tools

log = logging.getLogger(__name__)

# 스펙 13장
BODY_NOTES_MAX = 30
PLAN_SESSIONS_MAX = 7
SESSION_ITEMS_MAX = 12
LOG_ITEMS_MAX = 20
LOG_BACKDATE_DAYS = 6  # 오늘에서 뺄 수 있는 최대 날 수(오늘 포함 7일, 8.2)
LIST_DAYS_MAX = 180
LIST_DAYS_DEFAULT = 28
LIST_TRACES_MAX = 60

BODY_KINDS = ("equipment", "injury", "preference", "availability", "other")
NOTE_TEXT_MAX = 120
PLAN_TITLE_MAX, PLAN_NOTE_MAX = 30, 300
SESSION_LABEL_MAX = 20
ITEM_NAME_MAX = 30
LOG_TITLE_MAX, LOG_NOTE_MAX = 30, 200
NAME_QUERY_MAX = 30
CURRENT_PLAN_TARGET = "workout_plan:current"  # 모든 플랜 변경의 공통 대상(7.2)
_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_LOG_FIELDS = ("title", "date", "session_id", "effort", "note", "items")

# 부록 A
MSG_NOTES_FULL = "몸 메모는 30개까지예요. 오래된 것을 정리해 주세요."
MSG_LOG_RANGE = "일주일 안의 기록만 남길 수 있어요."
# 입력 오류(부록 A 밖, 습관 도구와 같은 꼴)
MSG_NO_WORKOUT = "운동 기록을 다룰 수 없어요."
MSG_NOTE_KIND = "kind는 equipment, injury, preference, availability, other 중 하나예요."
MSG_NOTE_TEXT = f"몸 메모는 1~{NOTE_TEXT_MAX}자로 써 주세요."
MSG_NO_NOTE = "없는 몸 메모예요."
MSG_PLAN_TITLE = f"플랜 제목은 1~{PLAN_TITLE_MAX}자로 써 주세요."
MSG_PLAN_NOTE = f"플랜 메모는 {PLAN_NOTE_MAX}자까지예요."
MSG_SESSIONS = f"sessions는 0~{PLAN_SESSIONS_MAX}개의 배열로 보내 주세요."
MSG_POSITIONS = "세션 position은 1부터 차례로 하나씩 써 주세요."
MSG_LOG_TITLE = f"기록 제목은 1~{LOG_TITLE_MAX}자로 써 주세요."
MSG_LOG_NOTE = f"기록 메모는 {LOG_NOTE_MAX}자까지예요."
MSG_DATE = "date는 YYYY-MM-DD 형식으로 알려 주세요."
MSG_EFFORT = "effort는 1~5 사이 정수예요."
MSG_NO_SESSION = "없는 세션이에요."
MSG_LOG_ITEMS = f"items는 0~{LOG_ITEMS_MAX}개의 배열로 보내 주세요."
MSG_NO_LOG = "없는 운동 기록이에요."
MSG_NOTHING = "바꿀 내용을 알려 주세요."
MSG_DAYS = f"days는 1~{LIST_DAYS_MAX} 사이 정수예요."
MSG_NAME = f"name은 1~{NAME_QUERY_MAX}자의 글이에요."


def body_note_target(note_id: int) -> str:
    return f"body_note:{note_id}"


def workout_plan_target(plan_id: int) -> str:
    return f"workout_plan:{plan_id}"


def workout_log_target(log_id: int) -> str:
    return f"workout_log:{log_id}"


def workout_day_ref(d: date) -> str:
    """X13 원장 `source_ref`(10장). 이룬 순간 출처 `workout:<id>`와 겹치지 않는 머리말."""
    return f"workout_day:{d.isoformat()}"


def _is_int(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _is_num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _text(v: Any, lo: int, hi: int) -> str | None:
    """앞뒤 공백을 뺀 `lo`~`hi`자 글, 아니면 None."""
    if not isinstance(v, str):
        return None
    t = v.strip()
    return t if lo <= len(t) <= hi else None


def _opt_text(v: Any, hi: int, msg: str) -> str | None:
    """None 또는 `hi`자까지의 글(빈 글은 None). 틀리면 `ValueError(msg)`."""
    if v is None:
        return None
    if not isinstance(v, str) or len(v.strip()) > hi:
        raise ValueError(msg)
    return v.strip() or None


def _opt_int(v: Any, lo: int, hi: int, msg: str) -> int | None:
    if v is None:
        return None
    if not _is_int(v) or not lo <= v <= hi:
        raise ValueError(msg)
    return v


def _opt_num(v: Any, lo: float, hi: float, msg: str) -> float | None:
    if v is None:
        return None
    if not _is_num(v) or not lo <= v <= hi:
        raise ValueError(msg)
    return float(v)


def _plan_item(raw: Any, where: str) -> PlanItem:
    """7.3 표 한 줄. 틀리면 `ValueError(문구)`."""
    keys = {"name", "sets", "reps", "weight_kg", "minutes", "note"}
    if not isinstance(raw, dict) or set(raw) - keys:
        raise ValueError(f"{where}: 운동은 name, sets, reps, weight_kg, minutes, note 칸만 써 주세요.")
    name = _text(raw.get("name"), 1, ITEM_NAME_MAX)
    if name is None:
        raise ValueError(f"{where}: 운동 이름은 1~{ITEM_NAME_MAX}자로 써 주세요.")
    sets = _opt_int(raw.get("sets"), 1, 10, f"{where}: sets는 1~10 또는 null이에요.")
    reps = raw.get("reps")
    if reps is not None:
        reps = _text(reps, 1, 10)
        if reps is None:
            raise ValueError(f"{where}: reps는 1~10자의 글(\"10\", \"8-10\", \"최대\") 또는 null이에요.")
    weight = _opt_num(raw.get("weight_kg"), 0, 500, f"{where}: weight_kg는 0~500, 0.5 단위 또는 null이에요.")
    if weight is not None and (weight * 2) != int(weight * 2):
        raise ValueError(f"{where}: weight_kg는 0~500, 0.5 단위 또는 null이에요.")
    minutes = _opt_int(raw.get("minutes"), 1, 180, f"{where}: minutes는 1~180 또는 null이에요.")
    note = _opt_text(raw.get("note"), 60, f"{where}: note는 60자까지예요.")
    return PlanItem(name, sets, reps, weight, minutes, note)


def _session(raw: Any) -> tuple[int, str, tuple[int, ...] | None, list[PlanItem]]:
    """(position, label, weekdays, items). 틀리면 `ValueError(문구)`."""
    if not isinstance(raw, dict) or set(raw) - {"position", "label", "weekdays", "items"}:
        raise ValueError("세션은 position, label, weekdays, items 칸만 써 주세요.")
    pos = raw.get("position")
    if not _is_int(pos):
        raise ValueError(MSG_POSITIONS)
    where = f"{pos}번 세션"
    label = _text(raw.get("label"), 1, SESSION_LABEL_MAX)
    if label is None:
        raise ValueError(f"{where}: 이름(label)은 1~{SESSION_LABEL_MAX}자로 써 주세요.")
    wd = raw.get("weekdays")
    if wd is not None:
        if (
            not isinstance(wd, list) or not wd or not all(_is_int(w) and 0 <= w <= 6 for w in wd)
            or len(set(wd)) != len(wd)
        ):
            raise ValueError(f"{where}: weekdays는 0(월)~6(일) 정수의 겹치지 않는 배열 또는 null이에요.")
        wd = tuple(sorted(wd))
    items = raw.get("items")
    if not isinstance(items, list) or not 1 <= len(items) <= SESSION_ITEMS_MAX:
        raise ValueError(f"{where}: 운동(items)은 1~{SESSION_ITEMS_MAX}개예요.")
    return pos, label, wd, [_plan_item(i, where) for i in items]


def _log_item(raw: Any, n: int) -> LogItem:
    """8.1 `workout_log_items` CHECK 범위. 틀리면 `ValueError(문구)`."""
    where = f"{n}번째 운동"
    keys = {"name", "sets", "reps", "weight_kg", "minutes", "distance_km"}
    if not isinstance(raw, dict) or set(raw) - keys:
        raise ValueError(f"{where}: name, sets, reps, weight_kg, minutes, distance_km 칸만 써 주세요.")
    name = _text(raw.get("name"), 1, ITEM_NAME_MAX)
    if name is None:
        raise ValueError(f"{where}: 운동 이름은 1~{ITEM_NAME_MAX}자로 써 주세요.")
    return LogItem(
        name,
        _opt_int(raw.get("sets"), 1, 20, f"{where}: sets는 1~20 또는 null이에요."),
        _opt_int(raw.get("reps"), 1, 200, f"{where}: reps는 1~200 정수 또는 null이에요."),
        _opt_num(raw.get("weight_kg"), 0, 500, f"{where}: weight_kg는 0~500 또는 null이에요."),
        _opt_int(raw.get("minutes"), 1, 600, f"{where}: minutes는 1~600 또는 null이에요."),
        _opt_num(raw.get("distance_km"), 0, 200, f"{where}: distance_km는 0~200 또는 null이에요."),
    )


def _log_items(v: Any) -> list[LogItem]:
    if v is None:
        return []
    if not isinstance(v, list) or len(v) > LOG_ITEMS_MAX:
        raise ValueError(MSG_LOG_ITEMS)
    return [_log_item(raw, n) for n, raw in enumerate(v, start=1)]


def _num_out(v: float | None) -> int | float | None:
    """결과의 무게·거리: 16.0 → 16."""
    return int(v) if v is not None and float(v).is_integer() else v


def note_dict(n: BodyNote) -> dict[str, Any]:
    return {"id": n.id, "kind": n.kind, "text": n.text}


def plan_dict(p: Plan) -> dict[str, Any]:
    return {
        "id": p.id, "title": p.title, "note": p.note,
        "sessions": [
            {
                "id": s.id, "position": s.position, "label": s.label,
                "weekdays": list(s.weekdays) if s.weekdays is not None else None,
                "items": [{**asdict(i), "weight_kg": _num_out(i.weight_kg)} for i in s.items],
            }
            for s in p.sessions
        ],
    }


def _log_items_out(items: tuple[LogItem, ...] | list[LogItem]) -> list[dict[str, Any]]:
    return [
        {**asdict(i), "weight_kg": _num_out(i.weight_kg), "distance_km": _num_out(i.distance_km)} for i in items
    ]


def log_dict(g: WorkoutLog) -> dict[str, Any]:
    return {
        "id": g.id, "date": g.date.isoformat(), "title": g.title, "session_id": g.session_id, "effort": g.effort,
        "note": g.note, "items": _log_items_out(g.items),
    }


def _log_before(g: WorkoutLog, fields: set[str]) -> dict[str, Any]:
    """되돌리기 `before`: 바뀐 칸의 이전 값(JSON 모양)."""
    full = {
        "title": g.title, "date": g.date.isoformat(), "session_id": g.session_id, "effort": g.effort,
        "note": g.note, "items": [asdict(i) for i in g.items],
    }
    return {k: full[k] for k in fields}


def _log_fields_from_json(before: dict[str, Any]) -> dict[str, Any]:
    out = dict(before)
    if "date" in out:
        out["date"] = date.fromisoformat(out["date"])
    if "items" in out:
        out["items"] = [LogItem(**i) for i in out["items"]]
    return out


class WorkoutTools:
    """메이트 도구 여덟 개. `Tools`의 공통 부품(`today`, `_record`, `_request_confirm`, `_chat_confirm`)을 쓴다."""

    workout: WorkoutRepo | None

    if TYPE_CHECKING:
        tasks: TasksRepo
        status: Any
        clock: Clock
        tz: Any
        boundary: time
        conditions: Any
        body: Any
        events: Any
        confirms: ConfirmsRepo | None

        def today(self) -> date: ...
        def _record(self, ctx: RunContext, kind: str, target: str | None, summary: str | None,
                    undo: dict[str, Any] | None, *, targets: list[str] | None = None) -> None: ...
        def _agent_event(self, ctx: RunContext, kind: EventKind, ref: str, area: str | None = None, *,
                         handoff_to: InboxAgent | None = None) -> None: ...
        def _request_confirm(self, ctx: RunContext, action: str, args: dict[str, Any], summary: str,
                             button: str) -> dict[str, Any]: ...
        def _chat_confirm(self, ctx: RunContext, args: dict[str, Any], summary: str, button: str,
                          *, action: str = ...) -> dict[str, Any]: ...
        def _by_brain(self, ctx: RunContext) -> bool: ...  # `EventTools`: 확인 토큰으로 적용하는 것이 아니다

    # --- 공통 ---

    def _log_date(self, v: Any) -> date:
        """기록 날짜. 기본 논리적 오늘, 오늘−6 ~ 오늘만(8.2). 틀리면 `ValueError(문구)`."""
        today = self.today()
        if v is None:
            return today
        if not (isinstance(v, str) and _ISO_DATE.fullmatch(v)):
            raise ValueError(MSG_DATE)
        try:
            d = date.fromisoformat(v)
        except ValueError:
            raise ValueError(MSG_DATE) from None
        if not today - timedelta(days=LOG_BACKDATE_DAYS) <= d <= today:
            raise ValueError(MSG_LOG_RANGE)
        return d

    def _session_id(self, v: Any) -> int | None:
        assert self.workout is not None
        if v is None:
            return None
        if not _is_int(v) or not self.workout.has_session(v):
            raise ValueError(MSG_NO_SESSION)
        return v

    def _workout_log(self, id: Any) -> WorkoutLog | None:
        assert self.workout is not None
        return self.workout.log(id) if _is_int(id) else None

    # --- 읽기 ---

    @_tool
    def get_mate_context(self, ctx: RunContext) -> dict[str, Any]:
        """앞머리(5.5)와 같은 글을 지금 값으로."""
        text = build_mate_preamble(
            now=self.clock.now(), tz=self.tz, boundary=self.boundary, conditions=self.conditions,
            body=self.body, events=self.events, workout=self.workout, tasks=self.tasks, habits=self.habits,
        )
        return {"text": text}

    @_tool
    def list_workouts(self, ctx: RunContext, days: Any = LIST_DAYS_DEFAULT, name: Any = None) -> dict[str, Any]:
        """오늘 포함 `days`일(기본 28, 최대 180)의 지우지 않은 기록, 최근 것부터. `name`은 운동 이름 부분 일치.

        `traces`는 같은 기간의 비서 쪽 운동 흔적(습관 체크·끝낸 할 일, 최대 60개). `name`이 있으면 제목 부분 일치로 거른다."""
        if self.workout is None:
            return _err(MSG_NO_WORKOUT)
        n = LIST_DAYS_DEFAULT if days is None else days
        if not _is_int(n) or not 1 <= n <= LIST_DAYS_MAX:
            return _err(MSG_DAYS)
        q = None
        if name is not None:
            q = _text(name, 1, NAME_QUERY_MAX)
            if q is None:
                return _err(MSG_NAME)
        today = self.today()
        since = today - timedelta(days=n - 1)
        logs = self.workout.logs(since, today, name=q)
        traces = workout_traces(
            tasks=self.tasks, habits=self.habits, since=since, until=today, tz=self.tz, boundary=self.boundary,
        )
        if q is not None:
            traces = [x for x in traces if q in x.title]
        traces = traces[:LIST_TRACES_MAX]
        log.info("workouts_listed", extra={"count": len(logs), "traces": len(traces)})
        return {"logs": [log_dict(g) for g in logs], "traces": [trace_dict(x) for x in traces]}

    # --- 몸 메모 (6장) ---

    @_tool
    def save_body_note(self, ctx: RunContext, kind: Any = None, text: Any = None, id: Any = None) -> dict[str, Any]:
        """더하기(`id` 없음) 또는 고치기. 같은 `kind`·`text`가 있으면 새로 더하지 않고 그 메모. 활동·이벤트 없음(6.3)."""
        if self.workout is None:
            return _err(MSG_NO_WORKOUT)
        if kind not in BODY_KINDS:
            return _err(MSG_NOTE_KIND)
        t = _text(redact(text)[0] if isinstance(text, str) else text, 1, NOTE_TEXT_MAX)
        if t is None:
            return _err(MSG_NOTE_TEXT)
        now = self.clock.now()
        if id is not None:
            current = self.workout.note(id) if _is_int(id) else None
            if current is None:
                return _err(MSG_NO_NOTE)
            same = self.workout.find_note(kind, t)
            if same is not None and same.id != current.id:  # 다른 메모와 같아지면 중복 없이 그 메모(더하기와 같다)
                return {"note": note_dict(same)}
            with transaction(self.workout.conn):
                self.workout.update_note(current.id, kind, t, now)
            got = self.workout.note(current.id)
            assert got is not None
            log.info("body_note_saved", extra={"note_id": got.id, "updated": True})
            return {"note": note_dict(got)}
        same = self.workout.find_note(kind, t)
        if same is not None:
            return {"note": note_dict(same)}
        if self.workout.count_notes() >= BODY_NOTES_MAX:
            return _err(MSG_NOTES_FULL)
        with transaction(self.workout.conn):
            n = self.workout.add_note(kind, t, now)
        log.info("body_note_saved", extra={"note_id": n.id, "updated": False})
        return {"note": note_dict(n)}

    @_tool
    def drop_body_note(self, ctx: RunContext, id: Any = None) -> dict[str, Any]:
        """소프트 삭제. 확인 없이 바로, 활동 `body_note_dropped`(되돌리기, 6.3). `summary`에 메모 글은 넣지 않는다."""
        if self.workout is None:
            return _err(MSG_NO_WORKOUT)
        n = self.workout.note(id) if _is_int(id) else None
        if n is None:
            return _err(MSG_NO_NOTE)
        with transaction(self.workout.conn):
            self.workout.drop_note(n.id, self.clock.now())
            self._record(ctx, "body_note_dropped", body_note_target(n.id), "몸 메모 지움", {"note_id": n.id})
        ctx.events.append(ToolEvent("body_note_dropped", None, {"note_id": n.id}))
        log.info("body_note_dropped", extra={"note_id": n.id})
        return {"id": n.id, "dropped": True}

    # --- 플랜 (7장) ---

    @_tool
    def set_workout_plan(
        self, ctx: RunContext, title: Any = None, note: Any = None, sessions: Any = None,
    ) -> dict[str, Any]:
        """플랜을 통째로 바꾼다(7.2). `sessions=[]`이면 지금 플랜을 내린다("플랜 없이 할래")."""
        if self.workout is None:
            return _err(MSG_NO_WORKOUT)
        if not isinstance(sessions, list) or len(sessions) > PLAN_SESSIONS_MAX:
            return _err(MSG_SESSIONS)
        now = self.clock.now()
        if not sessions:
            current = self.workout.current_plan()
            if current is None:
                return {"plan": None}  # 바꿀 것이 없다(활동 없음)
            with transaction(self.workout.conn):
                cleared = self.workout.clear_plan(now)
                assert cleared == current.id
                self._record(
                    ctx, "workout_plan_set", CURRENT_PLAN_TARGET, "운동 플랜 내림", {"cleared_id": cleared},
                    targets=[CURRENT_PLAN_TARGET, workout_plan_target(cleared)],
                )
            ctx.events.append(ToolEvent("workout_plan_set", None, {"plan_id": cleared, "cleared": True}))
            log.info("workout_plan_cleared", extra={"plan_id": cleared})
            return {"plan": None}
        t = _text(title, 1, PLAN_TITLE_MAX)
        if t is None:
            return _err(MSG_PLAN_TITLE)
        try:
            n = _opt_text(note, PLAN_NOTE_MAX, MSG_PLAN_NOTE)
            checked = [_session(s) for s in sessions]
        except ValueError as e:
            return _err(str(e))
        checked.sort(key=lambda s: s[0])
        if [s[0] for s in checked] != list(range(1, len(checked) + 1)):
            return _err(MSG_POSITIONS)
        with transaction(self.workout.conn):
            prev, new = self.workout.replace_plan(t, n, [(label, wd, items) for _, label, wd, items in checked], now)
            targets = [CURRENT_PLAN_TARGET, *([workout_plan_target(prev)] if prev is not None else []),
                       workout_plan_target(new)]
            self._record(
                ctx, "workout_plan_set", CURRENT_PLAN_TARGET, "운동 플랜 바꿈", {"new_id": new, "prev_id": prev},
                targets=targets,
            )
        ctx.events.append(ToolEvent("workout_plan_set", None, {"plan_id": new, "cleared": False}))
        log.info("workout_plan_set", extra={"plan_id": new, "sessions": len(checked)})
        got = self.workout.plan(new)
        assert got is not None
        return {"plan": plan_dict(got)}

    # --- 기록 (8장) ---

    @_tool
    def log_workout(
        self, ctx: RunContext, title: Any = None, date: Any = None, session_id: Any = None, effort: Any = None,
        note: Any = None, items: Any = None,
    ) -> dict[str, Any]:
        """기록 하나. 날짜는 기본 오늘, 오늘−6 ~ 오늘. 그 날짜의 첫 기록이면 X13(10장)."""
        if self.workout is None:
            return _err(MSG_NO_WORKOUT)
        t = _text(title, 1, LOG_TITLE_MAX)
        if t is None:
            return _err(MSG_LOG_TITLE)
        try:
            d = self._log_date(date)
            sid = self._session_id(session_id)
            eff = _opt_int(effort, 1, 5, MSG_EFFORT)
            n = _opt_text(note, LOG_NOTE_MAX, MSG_LOG_NOTE)
            rows = _log_items(items)
        except ValueError as e:
            return _err(str(e))
        now = self.clock.now()
        with transaction(self.workout.conn):
            g = self.workout.add_log(d, t, sid, eff, n, rows, now)
            self._record(ctx, "workout_logged", workout_log_target(g.id), f"운동 기록: {t}", {"log_id": g.id})
            self._agent_event(ctx, "workout_logged", f"workout:{g.id}", "health")
            if self.status is not None:  # 상태창 저장소가 없으면(시험) 쌓지 않는다
                self.status.grant(
                    at=now, logical_date=d, source_kind="workout_log", source_ref=workout_day_ref(d),
                    amount=XP_WORKOUT_LOG, label=LABEL_WORKOUT_LOG, area="health", gain=ctx.xp,
                )
        ctx.events.append(ToolEvent("workout_logged", None, {"log_id": g.id, "title": t}))
        log.info("workout_logged", extra={"log_id": g.id, "items": len(rows)})
        return {"log": log_dict(g)}

    @_tool
    def update_workout_log(self, ctx: RunContext, id: Any = None, **fields: Any) -> dict[str, Any]:
        """넘긴 칸만 고친다. `items`를 넘기면 줄 전체를 바꾼다. 바뀌는 것이 없으면 `already`."""
        if self.workout is None:
            return _err(MSG_NO_WORKOUT)
        unknown = set(fields) - set(_LOG_FIELDS)
        if unknown:
            return _err(f"바꿀 수 없는 항목이 있어요: {', '.join(sorted(unknown))}")
        if not fields:
            return _err(MSG_NOTHING)
        g = self._workout_log(id)
        if g is None:
            return _err(MSG_NO_LOG)
        changes: dict[str, Any] = {}
        try:
            if "title" in fields:
                t = _text(fields["title"], 1, LOG_TITLE_MAX)
                if t is None:
                    raise ValueError(MSG_LOG_TITLE)
                changes["title"] = t
            if "date" in fields:
                changes["date"] = self._log_date(fields["date"])
            if "session_id" in fields:
                changes["session_id"] = self._session_id(fields["session_id"])
            if "effort" in fields:
                changes["effort"] = _opt_int(fields["effort"], 1, 5, MSG_EFFORT)
            if "note" in fields:
                changes["note"] = _opt_text(fields["note"], LOG_NOTE_MAX, MSG_LOG_NOTE)
            if "items" in fields:
                changes["items"] = _log_items(fields["items"])
        except ValueError as e:
            return _err(str(e))
        prior = {k: getattr(g, k) for k in _LOG_FIELDS}
        prior["items"] = list(g.items)
        changes = {k: v for k, v in changes.items() if v != prior[k]}
        if not changes:
            return {"log": log_dict(g), "already": True}
        before = _log_before(g, set(changes))
        title = changes.get("title", g.title)
        with transaction(self.workout.conn):
            self.workout.update_log(g.id, self.clock.now(), **changes)
            self._record(
                ctx, "workout_log_updated", workout_log_target(g.id), f"운동 기록 고침: {title}",
                {"log_id": g.id, "before": before},
            )
            self._agent_event(ctx, "workout_logged", f"workout:{g.id}", "health")
            if "date" in changes and self.status is not None:  # 옮긴 날도 그날의 첫 기록이면 X13. 옛 날짜의 경험치는 그대로
                self.status.grant(
                    at=self.clock.now(), logical_date=changes["date"], source_kind="workout_log",
                    source_ref=workout_day_ref(changes["date"]), amount=XP_WORKOUT_LOG, label=LABEL_WORKOUT_LOG,
                    area="health", gain=ctx.xp,
                )
        ctx.events.append(ToolEvent("workout_log_updated", None, {"log_id": g.id, "title": title}))
        log.info("workout_log_updated", extra={"log_id": g.id, "fields": sorted(changes)})
        got = self.workout.log(g.id)
        assert got is not None
        return {"log": log_dict(got)}

    @_tool
    def delete_workout_log(self, ctx: RunContext, id: Any = None) -> dict[str, Any]:
        """소프트 삭제. 두뇌가 부르면 언제나 확인 카드(8.2): 아무것도 바꾸지 않고 확인 토큰만. 경험치는 그대로(10장)."""
        if self.workout is None:
            return _err(MSG_NO_WORKOUT)
        g = self._workout_log(id)
        if g is None:
            return _err(MSG_NO_LOG)
        if self._by_brain(ctx):
            if self.confirms is None:
                return _err(MSG_NO_WORKOUT)
            summary = confirm_workout_log_delete_summary(g.title, g.date)
            button = f"운동 기록 지우기: {g.title}"
            if ctx.run_turn and ctx.run_id is not None:
                return self._request_confirm(ctx, "delete_workout_log", {"id": g.id}, summary, button)
            return self._chat_confirm(ctx, {"id": g.id}, summary, button, action="delete_workout_log")
        with transaction(self.workout.conn):
            self.workout.delete_log(g.id, self.clock.now())
            self._record(ctx, "workout_log_deleted", workout_log_target(g.id), f"운동 기록 지움: {g.title}",
                         {"log_id": g.id})
        log.info("workout_log_deleted", extra={"log_id": g.id})
        return {"id": g.id, "deleted": True}


# --- 되돌리기 (7.2, 8.2, 6.3). 상한(메모 30개)은 보지 않고 이전 상태로만 돌린다 ---


def _undo_body_note_dropped(tools: Tools, undo: dict[str, Any], ctx: RunContext) -> str | None:
    assert tools.workout is not None
    try:
        tools.workout.restore_note(undo["note_id"])
    except KeyError:
        return SUPERSEDED
    return None


def _undo_workout_plan_set(tools: Tools, undo: dict[str, Any], ctx: RunContext) -> str | None:
    """비우기는 `cleared_at`을 NULL로, 바꾸기는 앞 플랜을 다시 지금 플랜으로. U3가 가장 최근 변경만 남긴다."""
    assert tools.workout is not None
    try:
        if "cleared_id" in undo:
            tools.workout.undo_clear(undo["cleared_id"])
        else:
            tools.workout.undo_replace(undo["new_id"], undo["prev_id"], tools.clock.now())
    except KeyError:
        return SUPERSEDED
    return None


def _undo_workout_logged(tools: Tools, undo: dict[str, Any], ctx: RunContext) -> str | None:
    """소프트 삭제. 경험치는 그대로(U6). 이미 지운 기록이면 superseded."""
    assert tools.workout is not None
    try:
        tools.workout.delete_log(undo["log_id"], tools.clock.now())
    except KeyError:
        return SUPERSEDED
    return None


def _undo_workout_log_updated(tools: Tools, undo: dict[str, Any], ctx: RunContext) -> str | None:
    assert tools.workout is not None
    try:
        tools.workout.update_log(undo["log_id"], tools.clock.now(), **_log_fields_from_json(undo["before"]))
    except KeyError:
        return SUPERSEDED
    return None


def _undo_workout_log_deleted(tools: Tools, undo: dict[str, Any], ctx: RunContext) -> str | None:
    assert tools.workout is not None
    try:
        tools.workout.restore_log(undo["log_id"])
    except KeyError:
        return SUPERSEDED
    return None


for _kind, _handler in (
    ("body_note_dropped", _undo_body_note_dropped),
    ("workout_plan_set", _undo_workout_plan_set),
    ("workout_logged", _undo_workout_logged),
    ("workout_log_updated", _undo_workout_log_updated),
    ("workout_log_deleted", _undo_workout_log_deleted),
):
    register_undo(_kind, _handler)
