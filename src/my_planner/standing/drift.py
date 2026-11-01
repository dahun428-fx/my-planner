"""하락 이유 나누기 (SP13-04, 스펙 9.2): 영역 위치 변화 Δ를 세상이 바뀐 몫(Δw)과 내가 바뀐 몫(Δm)으로 가른다.

Δw = (앞 값, 지금 기준표·나이) − (앞 값, 앞 기준표·나이), Δm = (지금 값, 지금 기준표) − (앞 값, 지금 기준표).
`profile_*`(태어난 해·성별·권역·직군) 고침은 세상 몫에 넣는다. 지우기는 내 변화가 아니다(ADR 0006): 기준선보다
새 측정값이 낸 값 변화만 내 몫이다. "새"는 `StandingRepo.latest`와 같은 순서 (측정일, id)로 가른다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

# 지표(목록 지표는 "cert:<키>")마다 고른 측정값의 순서 열쇠 (측정일 ISO, id). `StandingRepo.latest`와 같은 순서다
Order = dict[str, tuple[str, int]]

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


def _cert_key(text: str) -> str:
    return text.split(":")[0]


def _certs_mine(before: list[str], now: list[str], before_order: Order, now_order: Order) -> list[str]:
    """기준선 자격 목록에 그보다 새 자격만 얹는다. 지운 자격은 기준선 값으로 남는다."""
    out = {_cert_key(c): c for c in before}
    for c in now:
        k = _cert_key(c)
        b, n = before_order.get(f"cert:{k}"), now_order.get(f"cert:{k}")
        if k not in out or b is None or n is None or n > b:
            out[k] = c
    return list(out.values())


def _mine(before: Values, now: Values, before_order: Order, now_order: Order) -> Values:
    """지금 쪽에서 기준선보다 새 측정값이 아닌 값(기준선 값을 지워 되살아난 옛 값)은 기준선 값으로 둔다."""
    out = dict(now)
    for k, v in now.items():
        old = before.get(k)
        if k == "cert" and isinstance(v, list) and isinstance(old, list):
            out[k] = _certs_mine(old, v, before_order, now_order)
            continue
        b, n = before_order.get(k), now_order.get(k)
        if b is not None and n is not None and n < b:
            out[k] = before[k]
    return out


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
    before_order: Order | None = None,
    now_order: Order | None = None,
) -> Drift | None:
    before, now = _fill(before_values, now_values)
    now = _mine(before, now, before_order or {}, now_order or {})
    world_values = {**before, **{k: v for k, v in now.items() if k.startswith("profile_")}}
    start = _pos(before, before_bench, before_day, area)
    same_values_new_bench = _pos(world_values, now_bench, today, area)
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
