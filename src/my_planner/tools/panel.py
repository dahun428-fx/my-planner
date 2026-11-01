"""패널 쓰기 도구 (SP15 스펙 5.4, 7장, 9장, 10장). `Tools`가 이 mixin을 상속한다.

라이프 매니저 대화(`ctx.agent == "manager"`, `ctx.kind == "chat"`)에서만 쓴다.
- `propose_suggestion`: 서버가 모양·근거(`panel.evidence`)·주간 수(`panel.budget`)·버리기 이유 규칙(7.4)을 확인한 뒤
  `panel_suggestions`에 한 줄을 쓰고 `suggestion_proposed` 사건을 남긴다. 카드(`ui_panel_suggestion`)는 하네스 조각이다.
  거절(`rejected`)은 두뇌가 고쳐 다시 낼 수 있게 이유 코드를 싣고, 한 호출에 거절 둘이면 더 받지 않는다(7.2 다시 내기 1회).
- `save_statement`: 내가 한 말 한 줄(확인 카드 없음). 식별 정보는 저장하지 않는다.
- `record_prediction`: 숫자 지표·축의 예측 하나(한 대화 2개).
- `save_life_report`는 계획 Task 13이 채운다.

로그에는 결과 코드·영역·종류·지표 이름만 남긴다(제목·근거 글·말·예측 숫자 없음, 스펙 13장).
"""

from __future__ import annotations

import logging
import math
import re
import sqlite3
import unicodedata
from datetime import date, timedelta
from typing import TYPE_CHECKING, Any

from my_planner.domain import Area, RunContext, TaskStatus, ToolEvent
from my_planner.harness.redact import redact
from my_planner.panel.budget import remaining, week_key
from my_planner.panel.evidence import (
    PANEL_EXTRA_BANNED,
    check_evidence,
    evidence_href,
    parse_evidence,
)
from my_planner.standing.metrics import METRICS
from my_planner.standing.score import AREAS, AXES
from my_planner.status.xp import AREA_LABELS
from my_planner.store.db import transaction
from my_planner.tools._base import _err, _tool
from my_planner.tools.activity import (
    SUPERSEDED,
    habit_target,
    record_activity,
    register_undo,
    task_target,
)
from my_planner.tools.confirmations import habit_kind_label
from my_planner.tools.habits import (
    HABIT_ACTIVE_MAX,
    HABIT_TITLE_MAX,
    MSG_CAP,
    MSG_DUPLICATE,
    MSG_TITLE_LONG,
)
from my_planner.tools.moments import _bad_char
from my_planner.tools.ui import banned_words

if TYPE_CHECKING:
    from my_planner.clock import Clock
    from my_planner.domain import EventKind
    from my_planner.store.repos.activity import ActivityRepo
    from my_planner.store.repos.habits import Habit, HabitsRepo
    from my_planner.store.repos.panel import PanelRepo, Suggestion
    from my_planner.store.repos.state import StateRepo
    from my_planner.store.repos.tasks import Task, TasksRepo
    from my_planner.tools.core import Tools

log = logging.getLogger(__name__)

__all__ = ["DISMISS_REASONS", "PANEL_EXTRA_BANNED", "PanelTools", "normalize_title", "suggestion_view"]

SUGGESTION_TITLE_MAX = 60
SUGGESTION_DUE_MAX_DAYS = 60
SUGGESTION_SIZE_MIN, SUGGESTION_SIZE_MAX = 5, 120
NOT_INTERESTED_DAYS = 30
STATEMENT_TEXT_MAX = 200
PREDICTIONS_PER_CONVERSATION = 2
PREDICTION_MAX_AHEAD_DAYS = 365
AXIS_MIN, AXIS_MAX = 0, 100  # `axis:<축>` 예측 범위(축 점수 0~100)
PANEL_REJECTS_MAX = 2  # 한 호출의 거절 수: 처음 하나 + 다시 내기 하나(7.2)

# 전문가 키(Global Constraints 순서). `mcp_adapter.EXPERT_TOOLS`의 키와 같다(시험이 본다)
EXPERT_KEYS: tuple[str, ...] = ("career", "finance", "health", "image", "relationship", "psych")
STATEMENT_KINDS = ("fact", "preference", "decision")

MSG_NOT_HERE = "쓸 수 없는 도구예요."
MSG_NO_PANEL = "패널 기록을 쓸 수 없어요."
MSG_RETRY_USED = "이번 메시지에서는 더 낼 수 없어요. 질문으로 바꿔 주세요."
MSG_UNKNOWN_REF = "없는 기록을 근거로 댔어요. 참조를 고쳐 주세요."
MSG_NO_PERSONAL = "내 기록이나 내가 한 말 근거가 없어요. 질문으로 바꾸거나 근거를 더해 주세요."
MSG_BUDGET = "이번 주 제안은 다 냈어요."
MSG_TOO_BIG_AGAIN = "지난번에 너무 크다고 버렸어요. {n}분 이하로 줄여 주세요."
MSG_NOT_INTERESTED = f"{NOT_INTERESTED_DAYS}일 안에 관심 없다고 버린 제안이에요."
MSG_KIND = "kind는 task 또는 habit이에요."
MSG_TITLE = f"title은 {SUGGESTION_TITLE_MAX}자 안의 한 줄이에요."
MSG_AREA = f"area는 {', '.join(AREAS)} 가운데 하나예요."
MSG_SIZE = f"size_min은 {SUGGESTION_SIZE_MIN}~{SUGGESTION_SIZE_MAX} 사이 정수(분)예요."
MSG_PER_WEEK_HABIT = "습관이면 per_week는 1~7 사이 정수예요."
MSG_PER_WEEK_TASK = "할 일에는 per_week를 쓰지 않아요."
MSG_DUE_HINT = f"due_hint는 오늘부터 {SUGGESTION_DUE_MAX_DAYS}일 안의 YYYY-MM-DD예요."
MSG_EXPERTS = f"experts는 {', '.join(EXPERT_KEYS)} 가운데 겹치지 않게 1~{len(EXPERT_KEYS)}개예요."
MSG_BANNED = "쓰지 않는 말이 있어요: {word}"
MSG_ST_KIND = "kind는 fact, preference, decision 가운데 하나예요."
MSG_ST_AREA = f"area는 비우거나 {', '.join(AREAS)} 가운데 하나예요."
MSG_ST_TEXT = f"text는 {STATEMENT_TEXT_MAX}자 안의 한 줄이에요."
MSG_ST_KEY = "결정에는 key(영문 소문자와 _ 3~30자)가 있어야 해요."
MSG_ST_KEY_ONLY_DECISION = "key는 결정에만 써요."
MSG_ST_SECRET = "식별 정보는 저장하지 않아요."
MSG_ST_DECISION_EXISTS = "이미 있는 결정이에요."
MSG_ST_KEY_USED = "예전에 쓴 결정 키예요. 다른 키를 써 주세요."
MSG_PR_METRIC = "metric은 숫자 측정값 이름이나 axis:<축>이에요."
MSG_PR_VALUE = "predicted가 그 지표 범위의 숫자가 아니에요."
MSG_PR_DUE = f"due는 내일부터 {PREDICTION_MAX_AHEAD_DAYS}일 안의 YYYY-MM-DD예요."
MSG_PR_CAP = f"예측은 한 대화에 {PREDICTIONS_PER_CONVERSATION}개까지예요."

# 받기·버리기·말 지우기(계획 Task 9, `/actions`)
DISMISS_REASONS = ("no_time", "not_interested", "already", "too_big", "none")
DISMISS_STATEMENT_COUNT = 2  # 같은 영역·같은 이유 버림이 이 수가 되면 말 한 줄(7.4)
DISMISS_STATEMENTS = {
    "too_big": "{area} 제안이 너무 크다고 두 번 버렸어요.",
    "no_time": "{area} 제안을 시간이 없다고 두 번 버렸어요.",
    "not_interested": "{area} 제안에 관심 없다고 두 번 버렸어요.",
    "already": "{area} 제안을 이미 하고 있다고 두 번 버렸어요.",
}
MSG_DECIDED = "이미 정한 제안이에요."
MSG_NO_SUGGESTION = "없는 제안이에요."
MSG_REASON = f"reason은 {', '.join(DISMISS_REASONS)} 가운데 하나예요."
MSG_NO_STATEMENT = "없는 말이에요."
MSG_RETIRED = "이미 지운 말이에요."
SUMMARY_ACCEPTED = "✓ 제안 받음 · {title}"
SUMMARY_DISMISSED = "✓ 제안 버림 · {title}"
SUMMARY_RETIRED = "✓ 내가 한 말 지움"

_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DECISION_KEY = re.compile(r"^[a-z_]{3,30}$")


def normalize_title(t: str) -> str:
    """공백·문장부호·밑줄을 지우고 소문자(7.4 `not_interested`의 "비슷한 제목")."""
    return "".join(c for c in t if not (c.isspace() or c == "_" or unicodedata.category(c).startswith("P"))).lower()


def suggestion_view(conn: sqlite3.Connection, s: Suggestion) -> dict[str, Any]:
    """카드 출력과 API(계획 Task 9)가 같이 쓰는 제안 모양. 근거마다 앱 링크(`href`, 없으면 `None`)."""
    return {
        "id": s.id, "kind": s.kind, "title": s.title, "area": s.area, "size_min": s.size_min, "per_week": s.per_week,
        "due_hint": s.due_hint.isoformat() if s.due_hint is not None else None, "experts": list(s.experts),
        "evidence": [
            {"type": e["type"], "ref": e["ref"], "note": e["note"], "href": evidence_href(conn, e["ref"])}
            for e in s.evidence
        ],
        "state": s.state, "week": s.week,
    }


def _in_manager_chat(ctx: RunContext) -> bool:
    """라이프 매니저 대화 안. 대화 id가 없으면(`source_ref`·대화별 상한을 쓸 수 없다) 쓰지 않는다."""
    return ctx.agent == "manager" and ctx.kind == "chat" and ctx.conversation_id is not None


def _int(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _banned(text: str) -> str | None:
    """카드 글 금지어(`banned_words()` + `PANEL_EXTRA_BANNED`). 오류 문구에는 그 낱말만 넣는다."""
    for word in (*banned_words(), *PANEL_EXTRA_BANNED):
        if word in text:
            return MSG_BANNED.format(word=word)
    return None


def _line(v: Any, hi: int) -> str | None:
    """앞뒤 공백을 뺀 1~`hi`자 한 줄, 아니면 `None`."""
    if not isinstance(v, str):
        return None
    v = v.strip()
    return v if 1 <= len(v) <= hi and not _bad_char(v) else None


def _day(v: Any) -> date | None:
    if not isinstance(v, str) or not _DATE.match(v):
        return None
    try:
        return date.fromisoformat(v)
    except ValueError:
        return None


class PanelTools:
    """라이프 매니저의 쓰기 도구(제안 카드, 내가 한 말, 예측, 인생 리포트)."""

    if TYPE_CHECKING:
        clock: Clock
        state: StateRepo | None
        tasks: TasksRepo
        habits: HabitsRepo | None
        activity: ActivityRepo | None

        def today(self) -> date: ...
        def _export(self) -> None: ...
        def _agent_event(self, ctx: RunContext, kind: EventKind, ref: str, area: str | None = None) -> None: ...
        def _duplicate(self, title: str, own: int | None = None) -> bool: ...
        def _event_data(self, t: Task) -> dict[str, Any]: ...
        @staticmethod
        def _habit_data(h: Habit, label: str | None = None, day: date | None = None) -> dict[str, Any]: ...
        @staticmethod
        def _habit_title(v: Any) -> str: ...

    panel: PanelRepo | None

    # --- 제안 (7장) ---

    def _reject(self, ctx: RunContext, code: str, msg: str, area: Any, kind: Any) -> dict[str, Any]:
        ctx.panel_rejects += 1
        log.info("panel_suggestion", extra={  # 두뇌가 준 값은 정해진 키일 때만 로그에(`retry_used`는 모양 검사 전)
            "result": code, "area": area if area in AREAS else None, "kind": kind if kind in ("task", "habit") else None,
        })
        return {"error": msg, "rejected": code}

    @_tool
    def propose_suggestion(
        self, ctx: RunContext, kind: Any = None, title: Any = None, area: Any = None, size_min: Any = None,
        per_week: Any = None, due_hint: Any = None, experts: Any = None, evidence: Any = None,
    ) -> dict[str, Any]:
        if not _in_manager_chat(ctx):
            return _err(MSG_NOT_HERE)
        if self.panel is None or self.state is None:
            return _err(MSG_NO_PANEL)
        if ctx.panel_rejects >= PANEL_REJECTS_MAX:
            return self._reject(ctx, "retry_used", MSG_RETRY_USED, area, kind)
        today = self.today()
        # 모양(거절이 아니라 보통 오류, 세지 않는다)
        if kind not in ("task", "habit"):
            return _err(MSG_KIND)
        title_s = _line(title, SUGGESTION_TITLE_MAX)
        if title_s is None:
            return _err(MSG_TITLE)
        if (bad := _banned(title_s)) is not None:
            return _err(bad)
        if kind == "habit" and len(title_s) > HABIT_TITLE_MAX:
            return _err(MSG_TITLE_LONG)  # 받을 수 없는 카드가 되지 않게(습관 제목 한도)
        if area not in AREAS:
            return _err(MSG_AREA)
        if not _int(size_min) or not SUGGESTION_SIZE_MIN <= size_min <= SUGGESTION_SIZE_MAX:
            return _err(MSG_SIZE)
        if kind == "habit" and not (_int(per_week) and 1 <= per_week <= 7):
            return _err(MSG_PER_WEEK_HABIT)
        if kind == "task" and per_week is not None:
            return _err(MSG_PER_WEEK_TASK)
        due = None
        if due_hint is not None:
            due = _day(due_hint)
            if due is None or not today <= due <= today + timedelta(days=SUGGESTION_DUE_MAX_DAYS):
                return _err(MSG_DUE_HINT)
        if (
            not isinstance(experts, list) or not 1 <= len(experts) <= len(EXPERT_KEYS)
            or not all(isinstance(e, str) and e in EXPERT_KEYS for e in experts) or len(set(experts)) != len(experts)
        ):
            return _err(MSG_EXPERTS)
        items = parse_evidence(evidence)
        if isinstance(items, str):
            return _err(items)
        panel = self.panel
        # 근거(7.2): 서버가 늘 다시 본다. 저장하는 것은 검사한 항목뿐이다
        checked = check_evidence(panel.conn, items, today=today)
        if checked == "unknown_ref":
            return self._reject(ctx, checked, MSG_UNKNOWN_REF, area, kind)
        if checked == "no_personal_evidence":
            return self._reject(ctx, checked, MSG_NO_PERSONAL, area, kind)
        # 주간 수 검사와 아래 INSERT 사이에 `await`가 없다: 도구 호출은 동기로 돌아서 다른 호출이 끼어들지 않는다
        if remaining(panel, self.state, today) == 0:
            return self._reject(ctx, "budget_exhausted", MSG_BUDGET, area, kind)
        last = panel.latest_in_area(area)
        if last is not None and last.state == "dismissed" and last.dismiss_reason == "too_big":
            half = last.size_min // 2
            if size_min > half:
                return self._reject(ctx, "too_big_again", MSG_TOO_BIG_AGAIN.format(n=half), area, kind)
        now = self.clock.now()
        norm, team = normalize_title(title_s), set(experts)
        for s in panel.dismissed(area, "not_interested", now - timedelta(days=NOT_INTERESTED_DAYS)):
            if set(s.experts) == team and normalize_title(s.title) == norm:
                return self._reject(ctx, "not_interested_recent", MSG_NOT_INTERESTED, area, kind)
        with transaction(panel.conn):
            sid = panel.add_suggestion(
                conversation_id=ctx.conversation_id, kind=kind, title=title_s, area=area, size_min=size_min,
                per_week=per_week, due_hint=due, experts=experts,
                evidence=[{"type": it.type, "ref": it.ref, "note": it.note} for it in items],
                week=week_key(today), now=now,
            )
        ctx.events.append(ToolEvent("suggestion_proposed", None, {"id": sid}))
        log.info("panel_suggestion", extra={"result": "ok", "area": area, "kind": kind})
        return {"ok": True, "id": sid, "remaining": remaining(panel, self.state, today)}

    # --- 내가 한 말 (5.4) ---

    @_tool
    def save_statement(
        self, ctx: RunContext, kind: Any = None, area: Any = None, text: Any = None, key: Any = None
    ) -> dict[str, Any]:
        if not _in_manager_chat(ctx):
            return _err(MSG_NOT_HERE)
        if self.panel is None:
            return _err(MSG_NO_PANEL)
        if kind not in STATEMENT_KINDS:
            return _err(MSG_ST_KIND)
        if area is not None and area not in AREAS:
            return _err(MSG_ST_AREA)
        line = _line(text, STATEMENT_TEXT_MAX)
        if line is None:
            return _err(MSG_ST_TEXT)
        if (bad := _banned(line)) is not None:
            return _err(bad)
        if redact(line)[1]:
            return _err(MSG_ST_SECRET)
        if kind == "decision":
            if not isinstance(key, str) or not _DECISION_KEY.match(key):
                return _err(MSG_ST_KEY)
        elif key is not None:
            return _err(MSG_ST_KEY_ONLY_DECISION)
        panel = self.panel
        if kind == "decision" and panel.decision(key) is not None:
            return _err(MSG_ST_DECISION_EXISTS)
        same = panel.find_active(kind, area, line)
        if same is not None:
            return {"ok": True, "ref": _statement_ref(same.kind, same.id, same.key)}
        try:
            with transaction(panel.conn):
                sid = panel.add_statement(
                    kind, area, line, key=key, source_ref=f"conversation:{ctx.conversation_id}", now=self.clock.now()
                )
        except sqlite3.IntegrityError as e:  # 지운 결정의 키(`key`는 지운 줄까지 UNIQUE). 다른 제약은 그대로 올린다
            if "owner_statements.key" not in str(e):
                raise
            return _err(MSG_ST_KEY_USED)
        log.info("panel_statement", extra={"kind": kind, "id": sid})
        return {"ok": True, "ref": _statement_ref(kind, sid, key)}

    # --- 예측 (9장) ---

    @_tool
    def record_prediction(
        self, ctx: RunContext, metric: Any = None, predicted: Any = None, due: Any = None
    ) -> dict[str, Any]:
        if not _in_manager_chat(ctx):
            return _err(MSG_NOT_HERE)
        if self.panel is None:
            return _err(MSG_NO_PANEL)
        if not isinstance(metric, str):
            return _err(MSG_PR_METRIC)
        axis = metric.removeprefix("axis:") if metric.startswith("axis:") else None
        d = METRICS.get(metric)
        if axis is not None:
            if axis not in AXES:
                return _err(MSG_PR_METRIC)
        elif d is None or d.kind != "num" or metric.startswith("profile_"):
            return _err(MSG_PR_METRIC)
        if isinstance(predicted, bool) or not isinstance(predicted, int | float) or not math.isfinite(predicted):
            return _err(MSG_PR_VALUE)
        lo, hi = (AXIS_MIN, AXIS_MAX) if d is None else (d.lo, d.hi)
        if not (lo <= predicted <= hi):  # type: ignore[operator]
            return _err(MSG_PR_VALUE)
        today = self.today()
        due_d = _day(due)
        if due_d is None or not today + timedelta(days=1) <= due_d <= today + timedelta(days=PREDICTION_MAX_AHEAD_DAYS):
            return _err(MSG_PR_DUE)
        panel = self.panel
        assert ctx.conversation_id is not None  # `_in_manager_chat`
        if panel.count_for_conversation(ctx.conversation_id) >= PREDICTIONS_PER_CONVERSATION:
            return _err(MSG_PR_CAP)
        with transaction(panel.conn):
            pid = panel.add_prediction(
                metric, float(predicted), due_d, conversation_id=ctx.conversation_id, now=self.clock.now()
            )
        log.info("panel_prediction", extra={"metric": metric})
        return {"ok": True, "id": pid}

    # --- 받기·버리기·말 지우기 (계획 Task 9, `/actions`) ---

    def _open_suggestion(self, id: Any) -> Suggestion | dict[str, Any]:
        """트랜잭션 안에서: `proposed`인 제안, 아니면 오류(없으면 404 `not_found`, 정했으면 `rejected`)."""
        s = self.panel.suggestion(id) if self.panel is not None and _int(id) else None
        if s is None:
            return {"error": MSG_NO_SUGGESTION, "error_code": "not_found"}
        if s.state != "proposed":
            return _err(MSG_DECIDED)
        return s

    @_tool
    def accept_suggestion(self, ctx: RunContext, id: Any = None) -> dict[str, Any]:
        """받기(7.1): 할 일(`planned_for = due_hint` 또는 오늘) 또는 습관을 만들고 제안을 `accepted`로. 경험치는 없다
        (할 일 완료 때 X1만). 상태 확인과 쓰기가 한 트랜잭션이라 두 번 눌러도 한 번만 만든다."""
        if self.panel is None:
            return _err(MSG_NO_PANEL)
        panel = self.panel
        now = self.clock.now()
        with transaction(panel.conn):
            s = self._open_suggestion(id)
            if isinstance(s, dict):
                return s
            if s.kind == "task":
                t = self.tasks.create(
                    title=s.title, areas=[Area(s.area)], status=TaskStatus.open,
                    planned_for=max(s.due_hint, self.today()) if s.due_hint is not None else self.today(),  # 늦게 받아도 지난 날이 아니게
                )
                self.tasks.log_tool_event(ctx.run_id, ctx.conversation_id, t.id, "task_added",
                                          inbound_id=ctx.inbound_id, data=self._event_data(t))
                self._agent_event(ctx, "task_added", task_target(t.id), s.area)
                made = task_target(t.id)
            else:
                out = self._accept_habit(ctx, s)
                if isinstance(out, dict):
                    return out
                made = out
            if not panel.set_state(s.id, "accepted", now=now, result_ref=made, only_from="proposed"):
                raise RuntimeError("suggestion state changed inside the transaction")
            self._agent_event(ctx, "suggestion_accepted", _suggestion_ref(s.id), s.area)
            record_activity(
                self.activity, ctx, kind="suggestion_accepted", target=_suggestion_ref(s.id),
                summary=SUMMARY_ACCEPTED.format(title=s.title), risk="low",
                undo={"suggestion_id": s.id, "result_ref": made}, targets=[_suggestion_ref(s.id), made],
            )
        log.info("panel_decided", extra={"result": "accepted", "id": s.id, "kind": s.kind})
        self._export()
        return {"ok": True, "result_ref": made}

    def _accept_habit(self, ctx: RunContext, s: Suggestion) -> str | dict[str, Any]:
        """트랜잭션 안에서: 습관 하나(`per_week == 7`이면 매일). 습관 규칙(제목 길이, 같은 제목, 10개)은 그대로 본다."""
        if self.habits is None:
            return _err(MSG_NO_PANEL)
        try:
            title = self._habit_title(s.title)
        except ValueError as e:
            return _err(str(e))
        if self._duplicate(title):
            return _err(MSG_DUPLICATE)
        if self.habits.count_active() >= HABIT_ACTIVE_MAX:
            return _err(MSG_CAP)
        kind, target = ("daily", None) if s.per_week == 7 else ("weekly", s.per_week)
        h = self.habits.add(title, s.area, kind, target, self.clock.now())
        self.tasks.log_tool_event(ctx.run_id, ctx.conversation_id, None, "habit_added", inbound_id=ctx.inbound_id,
                                  data=self._habit_data(h, habit_kind_label(kind, target)))
        return habit_target(h.id)

    @_tool
    def dismiss_suggestion(self, ctx: RunContext, id: Any = None, reason: Any = "none") -> dict[str, Any]:
        """버리기(7.4): 이유와 함께 `dismissed`. 같은 영역·같은 이유가 (이것 포함) 2회가 되면 말 한 줄(`preference`)."""
        if self.panel is None:
            return _err(MSG_NO_PANEL)
        if reason not in DISMISS_REASONS:
            return _err(MSG_REASON)
        panel = self.panel
        now = self.clock.now()
        statement_id: int | None = None
        with transaction(panel.conn):
            s = self._open_suggestion(id)
            if isinstance(s, dict):
                return s
            if not panel.set_state(s.id, "dismissed", now=now, dismiss_reason=reason, only_from="proposed"):
                raise RuntimeError("suggestion state changed inside the transaction")
            self._agent_event(ctx, "suggestion_dismissed", _suggestion_ref(s.id), s.area)
            if reason != "none" and panel.count_dismissed(s.area, reason) == DISMISS_STATEMENT_COUNT:
                text = DISMISS_STATEMENTS[reason].format(area=AREA_LABELS[s.area])
                if panel.find_active("preference", s.area, text) is None:
                    statement_id = panel.add_statement(
                        "preference", s.area, text, source_ref=_suggestion_ref(s.id), now=now
                    )
            targets = [_suggestion_ref(s.id)]
            if statement_id is not None:
                targets.append(_statement_target(statement_id))
            record_activity(
                self.activity, ctx, kind="suggestion_dismissed", target=_suggestion_ref(s.id),
                summary=SUMMARY_DISMISSED.format(title=s.title), risk="low",
                undo={"suggestion_id": s.id, "statement_id": statement_id}, targets=targets,
            )
        log.info("panel_decided", extra={"result": "dismissed", "id": s.id, "reason": reason,
                                         "statement": statement_id is not None})
        return {"ok": True, "statement_id": statement_id}

    @_tool
    def retire_statement(self, ctx: RunContext, id: Any = None) -> dict[str, Any]:
        """내가 한 말 지우기(5.4): `retired_at`만 채운다. 결정도 지울 수 있다. 지운 말은 근거로 쓰지 못한다."""
        if self.panel is None:
            return _err(MSG_NO_PANEL)
        panel = self.panel
        with transaction(panel.conn):
            st = panel.statement(id) if _int(id) else None
            if st is None:
                return {"error": MSG_NO_STATEMENT, "error_code": "not_found"}
            if not panel.retire(st.id, self.clock.now()):
                return _err(MSG_RETIRED)
            record_activity(
                self.activity, ctx, kind="statement_retired", target=_statement_target(st.id),
                summary=SUMMARY_RETIRED, risk="low", undo={"statement_id": st.id},
            )
        log.info("panel_statement_retired", extra={"id": st.id, "kind": st.kind})
        return {"ok": True}

    # --- 인생 리포트 (10장) ---

    @_tool
    def save_life_report(self, ctx: RunContext, **_: Any) -> dict[str, Any]:
        return _err("아직 없어요.")


def _statement_ref(kind: str, sid: int, key: str | None) -> str:
    return f"decision:{key}" if kind == "decision" and key else f"statement:{sid}"


def _suggestion_ref(sid: int) -> str:
    return f"suggestion:{sid}"


def _statement_target(sid: int) -> str:
    return f"statement:{sid}"


# --- 되돌리기 (계획 Task 9). 사건(`agent_events`)은 지우지 않는다(SP14 5.2) ---


def _undo_suggestion_accepted(tools: Tools, undo: dict[str, Any], ctx: RunContext) -> str | None:
    """만든 할 일(또는 습관)을 소프트 삭제하고 제안을 `proposed`로. 할 일이 끝났거나 습관에 체크가 있으면 superseded."""
    assert tools.panel is not None
    ref: str = undo["result_ref"]
    kind, _, raw = ref.partition(":")
    if kind == "task":
        t = tools.tasks.get(int(raw))
        if t is None or t.status is TaskStatus.done:
            return SUPERSEDED
        tools.tasks.restore(t.id, status=t.status, completed_at=t.completed_at, deleted_at=tools.clock.now())
    else:
        assert tools.habits is not None
        hid = int(raw)
        if tools.habits.get(hid) is None or tools.habits.has_checks(hid):
            return SUPERSEDED
        tools.habits.soft_delete(hid, tools.clock.now())
    if not tools.panel.reopen(undo["suggestion_id"], only_from="accepted"):
        return SUPERSEDED  # 하루 끝 단계가 이미 `done`·`postponed`로 옮겼다
    return None


def _undo_suggestion_dismissed(tools: Tools, undo: dict[str, Any], ctx: RunContext) -> str | None:
    """제안을 `proposed`로, 그때 만든 말은 지운다(`retired_at`)."""
    assert tools.panel is not None
    if not tools.panel.reopen(undo["suggestion_id"], only_from="dismissed"):
        return SUPERSEDED
    if undo.get("statement_id") is not None:
        tools.panel.retire(undo["statement_id"], tools.clock.now())
    return None


def _undo_statement_retired(tools: Tools, undo: dict[str, Any], ctx: RunContext) -> str | None:
    assert tools.panel is not None
    return None if tools.panel.unretire(undo["statement_id"]) else SUPERSEDED


for _kind, _handler in (
    ("suggestion_accepted", _undo_suggestion_accepted),
    ("suggestion_dismissed", _undo_suggestion_dismissed),
    ("statement_retired", _undo_statement_retired),
):
    register_undo(_kind, _handler)
