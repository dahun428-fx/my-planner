"""하루 끝 판단 (SP14 스펙 1장 3, 6.1~6.3, 12장).

하루 한 번, 아래층 상대마다 안 읽은 받은편지함을 읽고 관찰 한 줄을 0~2개 남긴다(`write_note`). 사용자에게는 아무것도
보내지 않는다(원문 기록·알림·푸시·텔레그램·`runs` 없음, 1장 4). 디스패처의 `_DayendJob`이 이것들을 부른다.

받은편지함 읽음 표시, 보관 기한 정리, `app_state`의 `agent_dayend_*` 키 쓰기는 이 모듈에서만 한다
(쓰기 경로 감시, `tests/test_write_paths.py`). 로그에는 상대·개수·결과만 남긴다(글·`ref` 없음).
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Literal

from my_planner.clock import Clock
from my_planner.domain import InboxAgent
from my_planner.harness import prompts
from my_planner.harness.inbox import event_line, handoff_texts
from my_planner.panel import budget, lifecycle, predictions
from my_planner.store.db import transaction

if TYPE_CHECKING:
    from my_planner.harness.brain import BrainResult
    from my_planner.store.repos.agents import AgentEvent, AgentNote, AgentsRepo
    from my_planner.store.repos.state import StateRepo

log = logging.getLogger(__name__)

DAYEND_LOOKBACK_DAYS = 7  # 따라잡기: 최대 7일치 받은편지함(6.1)
DAYEND_MAX_TURNS = 3
DAYEND_MAX_ATTEMPTS = 2  # 두 번 해도 안 되면 본 것으로(6.2, SP8 순간과 같은 규칙)
DAYEND_EVENTS_MAX = 100
DAYEND_PAST_NOTES = 3

DAYEND_AGENTS: tuple[InboxAgent, ...] = ("mate", "manager")  # 이 순서로(SP15: 하루 두뇌 호출 2회까지)
DAYEND_PROMPTS: dict[InboxAgent, str] = {"mate": "mate.md", "manager": "manager.md"}

DAYEND_DAY_KEY = "agent_dayend_day:{agent}"  # 마지막으로 두뇌를 부른 논리적 날짜
DAYEND_ATTEMPTS_KEY = "agent_dayend_attempts:{agent}"

# 두뇌 없는 코드 단계(SP15). 판단 전에 늘 돈다. 단계마다 따로 트랜잭션. 제안·예측 상태를 닫은 뒤 주간 수를 정한다
CodeStep = Callable[[sqlite3.Connection, Clock, date], None]
DAYEND_CODE_STEPS: list[CodeStep] = [
    lifecycle.update_suggestions, predictions.check_predictions, budget.settle_week,
]

_WEEKDAY = "월화수목금토일"
_NONE = "- 없음"


@dataclass(frozen=True)
class DayendInput:
    text: str
    event_ids: tuple[int, ...]  # 성공하면 본 것으로 표시할 줄(입력 밖의 창 안 줄 포함)
    events: int  # 입력에 실은 사건 수


# --- 입력 (6.2) ---


def build_dayend_input(
    today: date, events: list[AgentEvent], past: list[AgentNote], handoffs: Mapping[str, str] | None = None,
) -> str:
    """판단하는 날(어제), 새로 생긴 것(오래된 것부터), 지난 관찰(최신 먼저). 빈 섹션은 `- 없음`.

    `handoffs`는 받은 넘김의 `ref`(`note:<id>`) → 관찰 글. 그 줄 끝에 붙는다(`event_line`)."""
    texts = handoffs or {}
    day = today - timedelta(days=1)
    return "\n".join([
        "## 판단하는 날",
        f"{day.isoformat()} ({_WEEKDAY[day.weekday()]})",
        "",
        "## 새로 생긴 것",
        *([event_line(e, texts.get(e.ref)) for e in events] or [_NONE]),
        "",
        "## 지난 관찰",
        *([f"- {n.day.isoformat()} {n.text}" for n in past] or [_NONE]),
    ])


def prepare(
    repo: AgentsRepo, state: StateRepo, agent: InboxAgent, today: date, now: datetime
) -> DayendInput | Literal["already", "empty"]:
    """한 트랜잭션: 7일보다 이른 안 읽은 줄을 본 것으로, 그날 이미 불렀으면 `already`, 안 읽은 줄이 없으면 `empty`."""
    since = today - timedelta(days=DAYEND_LOOKBACK_DAYS)
    with transaction(repo.conn):
        repo.mark_seen_before(agent, since, now)
        if state.get(DAYEND_DAY_KEY.format(agent=agent)) == today.isoformat():
            return "already"
        unseen = repo.unseen(agent, since)  # 최신 먼저
        if not unseen:
            return "empty"
        shown = list(reversed(unseen[:DAYEND_EVENTS_MAX]))
        past = repo.notes(agent, date.min, limit=DAYEND_PAST_NOTES)
        texts = handoff_texts(repo, shown)
    return DayendInput(
        text=build_dayend_input(today, shown, past, texts), event_ids=tuple(e.id for e in unseen), events=len(shown),
    )


def mark_called(state: StateRepo, agent: InboxAgent, today: date) -> None:
    """그날 두뇌를 불렀다(하루 한 번, T5). 호출 전에 적는다."""
    with transaction(state.conn):
        state.set(DAYEND_DAY_KEY.format(agent=agent), today.isoformat())


def dayend_system_prompt(agent: InboxAgent) -> str:
    """그 상대의 지시문 + 빈 줄 + `agent_dayend.md`(6.2)."""
    return f"{prompts.load(DAYEND_PROMPTS[agent])}\n\n{prompts.load('agent_dayend.md')}"


# --- 판정 (6.2, 12장) ---


def _attempts(state: StateRepo, agent: InboxAgent) -> int:
    raw = state.get(DAYEND_ATTEMPTS_KEY.format(agent=agent))
    try:
        return int(raw) if raw is not None else 0
    except ValueError:
        return 0


def settle(
    repo: AgentsRepo, state: StateRepo, agent: InboxAgent, today: date, inp: DayendInput, result: BrainResult,
    notes_written: int, now: datetime,
) -> Literal["ok", "retry", "failed", "limited"]:
    """`ok`이거나 관찰·넘김을 저장했으면(`notes_written`에 넘김 수 포함) 본 것으로. 사용 한도·로그인 문제면 그대로. 그 밖은 시도 + 1(2회면 본 것으로)."""
    key = DAYEND_ATTEMPTS_KEY.format(agent=agent)
    if result.status == "ok" or notes_written > 0:
        with transaction(repo.conn):
            repo.mark_seen(agent, inp.event_ids, now)
            state.set(key, "0")
        return "ok"
    if result.status in ("rate_limited", "auth_error"):
        return "limited"
    attempts = _attempts(state, agent) + 1
    with transaction(repo.conn):
        if attempts >= DAYEND_MAX_ATTEMPTS:
            repo.mark_seen(agent, inp.event_ids, now)
            state.set(key, "0")
        else:
            state.set(key, str(attempts))
    if attempts >= DAYEND_MAX_ATTEMPTS:
        log.warning("agent_dayend_failed", extra={"agent": agent, "events": inp.events})
        return "failed"
    return "retry"


# --- 보관 (5.1) ---


def prune(repo: AgentsRepo, today: date, now: datetime) -> dict[str, int]:
    """사건 90일, 본 받은편지함 줄 30일, 관찰 365일. 로그에는 개수만."""
    with transaction(repo.conn):
        got = repo.prune(today, now)
    log.info("agent_tables_pruned", extra=dict(got))
    return got


def run_code_steps(conn: sqlite3.Connection, clock: Clock, today: date) -> None:
    """`DAYEND_CODE_STEPS`를 차례로. 단계마다 따로 트랜잭션, 예외는 종류만 남기고 다음 단계로."""
    for step in DAYEND_CODE_STEPS:
        try:
            with transaction(conn):
                step(conn, clock, today)
        except Exception as e:  # noqa: BLE001 - 한 단계가 다른 단계와 판단을 막지 않는다
            log.warning("agent_dayend_step_error", extra={
                "step": getattr(step, "__name__", type(step).__name__), "error_type": type(e).__name__,
            })
