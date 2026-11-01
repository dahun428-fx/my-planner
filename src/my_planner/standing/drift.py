"""하락 이유 나누기 (SP13-04, 스펙 9.2): 영역 위치 변화 Δ를 세상이 바뀐 몫(Δw)과 내가 바뀐 몫(Δm)으로 가른다.

Δw = (앞 값, 지금 기준표·나이) − (앞 값, 앞 기준표·나이), Δm = (지금 값, 지금 기준표) − (앞 값, 지금 기준표).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from my_planner.standing.bench import Bench
from my_planner.standing.score import Values, area_positions, round_half_up, score_all

DRIFT_MIN = 5


@dataclass(frozen=True)
class Drift:
    delta: float
    world: float
    me: float


def _fill(a: Values, b: Values) -> tuple[Values, Values]:
    """한쪽에만 있는 지표를 다른 쪽에 같은 값으로 채운다(빈칸을 채우거나 지우는 것은 내 변화가 아니다, ADR 0006)."""
    return {**b, **a}, {**a, **b}


def _pos(values: Values, bench: Bench, today: date, area: str) -> float | None:
    return area_positions(score_all(values, bench, "national", today)).get(area)


def split(
    before_values: Values,
    before_bench: Bench,
    before_day: date,
    now_values: Values,
    now_bench: Bench,
    today: date,
    area: str,
) -> Drift | None:
    before, now = _fill(before_values, now_values)
    start = _pos(before, before_bench, before_day, area)
    same_values_new_bench = _pos(before, now_bench, today, area)
    end = _pos(now, now_bench, today, area)
    if start is None or end is None or same_values_new_bench is None:
        return None
    return Drift(delta=end - start, world=same_values_new_bench - start, me=end - same_values_new_bench)


def marks(d: Drift) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if d.me >= DRIFT_MIN or d.me <= -DRIFT_MIN:
        out.append({"kind": "me", "delta": round_half_up(d.me)})
    if d.world <= -DRIFT_MIN:
        out.append({"kind": "world", "delta": round_half_up(d.world)})
    return out


def debuff(d: Drift | None) -> bool:
    return d is not None and d.me <= -DRIFT_MIN
