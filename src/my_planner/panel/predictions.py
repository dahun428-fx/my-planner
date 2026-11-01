"""예측 맞춰 보기 (SP15 스펙 9.1). 하루 끝 코드 단계(`harness.dayend.DAYEND_CODE_STEPS`)의 둘째 단계, 두뇌 없음.

기한이 지난 예측마다 기한 ±`PREDICTION_WINDOW_DAYS`일 안의 측정값으로 `actual`을 채운다.
- 지표: 그 지표의 지우지 않은 측정값 가운데 창 안에서 가장 늦은 것의 값.
- `axis:<축>`: 창 안에 그 축의 입력 지표 측정값이 하나라도 있으면 지금 계산한 그 축의 `national` 점수. 입력 지표는
  점수 계산이 읽은 지표(`inputs`·`missing`, 프로필 빼고)와 그 축 영역(`AXIS_AREA`)의 지표(`metric_area`)다
  (계획 Task 14: 건강 축 예측은 창 안의 `body_fat_pct`로도 맞춰 본다).
값이 없으면 창이 열려 있는 동안(`today <= due + 창`) 그대로 둔다(앞머리 "측정 필요"). 창이 닫히면 `actual` 없이
`checked_at`만 채워 닫는다(다시 보지 않고 앞머리에서도 빠진다).

로그에는 채움·닫음 개수만 남긴다(지표 이름·값 없음, 스펙 13장).
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import date, timedelta

from my_planner.clock import Clock
from my_planner.standing import service as standing_service
from my_planner.standing.metrics import metric_area
from my_planner.standing.score import AXIS_AREA
from my_planner.store.repos.panel import PanelRepo, Prediction
from my_planner.store.repos.standing import Measure, StandingRepo

log = logging.getLogger(__name__)

PREDICTION_WINDOW_DAYS = 14
AXIS_PREFIX = "axis:"


def _in_window(m: Measure, p: Prediction) -> bool:
    return abs((m.measured_on - p.due).days) <= PREDICTION_WINDOW_DAYS


def _metric_actual(measures: list[Measure], p: Prediction) -> float | None:
    """`measures`는 지표·측정일 늦은 순(`StandingRepo.active`). 창 안 첫 숫자 값."""
    for m in measures:
        if m.metric == p.metric and m.value_num is not None and _in_window(m, p):
            return m.value_num
    return None


def _axis_actual(
    conn: sqlite3.Connection, clock: Clock, today: date, measures: list[Measure], p: Prediction,
    cache: dict[str, standing_service.StandingNow],
) -> float | None:
    if "now" not in cache:
        cache["now"] = standing_service.current(conn, clock, today)
    axis = p.metric.removeprefix(AXIS_PREFIX)
    score = cache["now"].scores["national"].get(axis)  # type: ignore[call-overload]
    if score is None:
        return None
    inputs = {k for k in (*score.inputs, *score.missing) if not k.startswith("profile_")}
    area = AXIS_AREA.get(axis)

    def feeds(metric: str) -> bool:
        return metric in inputs or (area is not None and metric_area(metric) == area)

    if not any(feeds(m.metric) and _in_window(m, p) for m in measures):
        return None
    return float(score.score)


def check_predictions(conn: sqlite3.Connection, clock: Clock, today: date) -> None:
    """부르는 쪽 트랜잭션 안에서. `today`는 논리적 오늘."""
    panel = PanelRepo(conn, clock)
    due = panel.due_unchecked(today)
    if not due:
        return
    now = clock.now()
    measures = StandingRepo(conn, clock).active()
    cache: dict[str, standing_service.StandingNow] = {}
    filled = closed = 0
    for p in due:
        if p.metric.startswith(AXIS_PREFIX):
            actual = _axis_actual(conn, clock, today, measures, p, cache)
        else:
            actual = _metric_actual(measures, p)
        if actual is not None:
            panel.set_actual(p.id, actual, now)
            filled += 1
        elif today > p.due + timedelta(days=PREDICTION_WINDOW_DAYS):
            panel.close_unmeasured(p.id, now)
            closed += 1
    log.info("panel_predictions_checked", extra={"filled": filled, "closed": closed})
