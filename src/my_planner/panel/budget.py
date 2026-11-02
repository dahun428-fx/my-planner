"""주간 제안 수 (SP15 스펙 7.3). 규칙은 순수 함수, 한 주의 값은 월요일 첫 하루 끝 코드 단계가 정해 `app_state`에 둔다.

주(`week`)는 논리적 날짜(04:00 경계)의 ISO 주. 부르는 쪽이 논리적 날짜를 넘긴다(`week_key`는 날짜만 받는다).
완료율·거절률·상한 숫자는 사용자에게 보이지 않는다. 로그에는 주와 수만 남긴다.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from datetime import date, timedelta

from my_planner.clock import Clock, period_bounds, period_of
from my_planner.store.repos.panel import PanelRepo
from my_planner.store.repos.state import StateRepo

log = logging.getLogger(__name__)

BUDGET_START = 2
BUDGET_MIN = 1
BUDGET_MAX = 5
BUDGET_WARMUP_WEEKS = 4
BUDGET_WINDOW_WEEKS = 4
BUDGET_KEY = "panel_budget:{week}"  # `app_state`, 값은 정수 글

_MIN_N = 3
_UP_DONE_RATE = 0.7
_UP_REJECT_RATE = 0.3
_DOWN_DONE_RATE = 0.4
_DOWN_REJECT_RATE = 0.5


def week_key(d: date) -> str:
    """ISO 주 `YYYY-Www`(두 자리 주)."""
    return period_of("week", d)


def week_monday(week: str) -> date:
    return period_bounds("week", week)[0]


def weeks_before(week: str, n: int) -> list[str]:
    """`week` 바로 앞 `n`주, 오래된 것부터(`week`는 빼고)."""
    monday = week_monday(week)
    return [week_key(monday - timedelta(weeks=k)) for k in range(n, 0, -1)]


@dataclass(frozen=True)
class WindowCounts:
    """창 안 제안의 상태별 개수. 아직 `proposed`인 것은 넣지 않는다."""

    accepted: int
    done: int
    postponed: int
    dismissed: int
    expired: int

    @property
    def n(self) -> int:
        return self.accepted + self.done + self.postponed + self.dismissed + self.expired


def next_budget(prev: int, w: WindowCounts) -> int:
    """스펙 7.3. 받은 채 열린 `accepted`는 `n`에는 들고 완료율에는 들지 않는다. 결과는 1~5."""
    n = w.n
    if n < _MIN_N:
        return prev
    closed = w.done + w.postponed
    done_rate = w.done / closed if closed > 0 else None
    reject_rate = (w.dismissed + w.expired) / n
    nxt = prev
    if done_rate is not None and done_rate >= _UP_DONE_RATE and reject_rate < _UP_REJECT_RATE:
        nxt = prev + 1
    elif (done_rate is not None and done_rate < _DOWN_DONE_RATE) or reject_rate >= _DOWN_REJECT_RATE:
        nxt = prev - 1
    return max(BUDGET_MIN, min(BUDGET_MAX, nxt))


def _window(repo: PanelRepo, week: str) -> WindowCounts:
    counts = dict.fromkeys(("accepted", "done", "postponed", "dismissed", "expired"), 0)
    for s in repo.in_weeks(weeks_before(week, BUDGET_WINDOW_WEEKS)):
        if s.state in counts:
            counts[s.state] += 1
    return WindowCounts(**counts)


def _stored(state: StateRepo, week: str) -> int | None:
    raw = state.get(BUDGET_KEY.format(week=week))
    return int(raw) if raw is not None else None


def compute_week_budget(repo: PanelRepo, state: StateRepo, week: str) -> int:
    """제안이 한 번도 없거나 첫 제안 주부터 4주 안이면 2. 아니면 지난 주 값(저장값, 없으면 같은 규칙으로 거슬러
    계산)과 지난 4주 창으로 `next_budget`."""
    first = repo.first_week()
    if first is None:
        return BUDGET_START
    warm_end = week_monday(first) + timedelta(weeks=BUDGET_WARMUP_WEEKS)

    def warm(w: str) -> bool:
        return week_monday(w) < warm_end

    # 저장값이 있거나 처음 4주인 주까지 거슬러 간 뒤, 앞으로 오며 계산한다(재귀 없이)
    pending: list[str] = []
    cur = week
    while not warm(cur):
        if cur != week and (got := _stored(state, cur)) is not None:
            budget = got
            break
        pending.append(cur)
        cur = weeks_before(cur, 1)[0]
    else:
        budget = BUDGET_START
    for w in reversed(pending):
        budget = next_budget(budget, _window(repo, w))
    return budget


def settle_week(conn: sqlite3.Connection, clock: Clock, today: date) -> None:
    """하루 끝 코드 단계: 이번 주 값이 없으면 정해 저장한다(한 주에 한 번 = 그 주 첫 판단). 있으면 그대로."""
    state = StateRepo(conn, clock)
    week = week_key(today)
    key = BUDGET_KEY.format(week=week)
    if state.get(key) is not None:
        return
    budget = compute_week_budget(PanelRepo(conn, clock), state, week)
    state.set(key, str(budget))
    log.info("panel_budget_set", extra={"week": week, "budget": budget})


def budget_for(repo: PanelRepo, state: StateRepo, today: date) -> int:
    """이번 주 수: 저장값, 없으면 계산값(저장하지 않는다)."""
    week = week_key(today)
    got = _stored(state, week)
    return got if got is not None else compute_week_budget(repo, state, week)


def remaining(repo: PanelRepo, state: StateRepo, today: date) -> int:
    """이번 주 남은 제안 수. 이번 주에 낸 제안은 상태와 상관없이 모두 센다."""
    return max(0, budget_for(repo, state, today) - repo.count_in_week(week_key(today)))
