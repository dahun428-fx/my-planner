"""패널 제안 상태 갱신 (SP15 스펙 7.1). 하루 끝 코드 단계(`harness.dayend.DAYEND_CODE_STEPS`)의 첫 단계, 두뇌 없음.

- `proposed`로 `SUGGESTION_EXPIRE_DAYS`일이 지나면 `expired`.
- 받은 할 일(`result_ref = task:<id>`): 받은 뒤 그 할 일의 마지막 사건이 완료면 `done`, 늦춤이면 `postponed`,
  내려놓음이면 `dismissed`(`dismiss_reason = 'none'`, 계획 결정: 스펙에 없는 흐름이라 거절 쪽으로 센다).
- 받은 습관(`result_ref = habit:<id>`): 받은 뒤 체크가 하나라도 있으면 `done`(습관은 늦춤이 없다).

`decided_at`은 처음 정한 값 그대로 둔다(만료만 지금 시각). 로그에는 상태별 개수만 남긴다.
"""

from __future__ import annotations

import logging
import sqlite3
from collections import Counter
from datetime import date, timedelta

from my_planner.clock import Clock
from my_planner.store.repos.agents import AgentEvent, AgentsRepo
from my_planner.store.repos.panel import PanelRepo, Suggestion
from my_planner.tools.panel import SUGGESTION_EXPIRE_DAYS

log = logging.getLogger(__name__)

_TASK_KINDS = ("task_done", "task_postponed", "task_dropped")
_TASK_STATE = {"task_done": "done", "task_postponed": "postponed", "task_dropped": "dismissed"}


def _last_by_ref(events: list[AgentEvent], s: Suggestion) -> AgentEvent | None:
    """받은 뒤(`decided_at` 이후) 그 제안 결과의 마지막 사건."""
    assert s.decided_at is not None
    got = [e for e in events if e.ref == s.result_ref and e.occurred_at >= s.decided_at]
    return got[-1] if got else None


def update_suggestions(conn: sqlite3.Connection, clock: Clock, today: date) -> None:
    """부르는 쪽 트랜잭션 안에서. `today`는 쓰지 않는다(시각 비교는 `clock.now()`와 `decided_at`)."""
    panel = PanelRepo(conn, clock)
    now = clock.now()
    counts: Counter[str] = Counter()

    for s in panel.suggestions(state="proposed"):
        expired = s.created_at <= now - timedelta(days=SUGGESTION_EXPIRE_DAYS)
        if expired and panel.set_state(s.id, "expired", now=now, only_from="proposed"):
            counts["expired"] += 1

    open_ = [
        s for st in ("accepted", "postponed") for s in panel.suggestions(state=st)
        if s.result_ref is not None and s.decided_at is not None
    ]
    if open_:
        # 사건 `day`는 논리적 날짜다: UTC 날짜 하루 앞부터 읽고 시각(`occurred_at`)으로 거른다
        since = min(s.decided_at for s in open_ if s.decided_at is not None).date() - timedelta(days=1)
        agents = AgentsRepo(conn, clock)
        task_events = agents.events_since(_TASK_KINDS, since)
        habit_events = agents.events_since(["habit_checked"], since)
        for s in open_:
            new: str | None = None
            if s.result_ref is not None and s.result_ref.startswith("task:"):
                last = _last_by_ref(task_events, s)
                new = _TASK_STATE[last.kind] if last is not None else None
            elif s.state == "accepted" and s.result_ref is not None and s.result_ref.startswith("habit:"):
                new = "done" if _last_by_ref(habit_events, s) is not None else None
            if new is None or new == s.state:
                continue
            extra = {"dismiss_reason": "none"} if new == "dismissed" else {}
            if panel.set_state(s.id, new, now=now, decided=False, only_from=s.state, **extra):
                counts[new] += 1

    log.info("panel_suggestions_updated", extra={
        k: counts[k] for k in ("expired", "done", "postponed", "dismissed")
    })
