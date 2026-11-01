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

from my_planner.domain import RunContext, ToolEvent
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
from my_planner.store.db import transaction
from my_planner.tools._base import _err, _tool
from my_planner.tools.moments import _bad_char
from my_planner.tools.ui import banned_words

if TYPE_CHECKING:
    from my_planner.clock import Clock
    from my_planner.store.repos.panel import PanelRepo, Suggestion
    from my_planner.store.repos.state import StateRepo

log = logging.getLogger(__name__)

__all__ = ["PANEL_EXTRA_BANNED", "PanelTools", "normalize_title", "suggestion_view"]

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

        def today(self) -> date: ...

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

    # --- 인생 리포트 (10장) ---

    @_tool
    def save_life_report(self, ctx: RunContext, **_: Any) -> dict[str, Any]:
        return _err("아직 없어요.")


def _statement_ref(kind: str, sid: int, key: str | None) -> str:
    return f"decision:{key}" if kind == "decision" and key else f"statement:{sid}"
