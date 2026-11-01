"""결혼시장·직장시장 점수 (SP13-03). 없는 축은 빼고 남은 가중치로 나눈다."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from my_planner.standing.bench import Bench
from my_planner.standing.score import AXES, Axis, AxisScore, round_half_up


@dataclass(frozen=True)
class Market:
    score: int | None
    excluded: tuple[Axis, ...]


def market_scores(scores: Mapping[Axis, AxisScore], bench: Bench) -> dict[str, Market]:
    out: dict[str, Market] = {}
    for name in ("marriage", "career"):
        weights = bench.table("markets", name)
        have = [a for a in AXES if a in scores and a in weights]
        excluded = tuple(a for a in AXES if a in weights and a not in scores)
        total = sum(weights[a] for a in have)
        if not have or total == 0:
            out[name] = Market(None, excluded)
            continue
        value = sum(weights[a] * scores[a].score for a in have) / total
        out[name] = Market(max(0, min(100, round_half_up(value))), excluded)
    return out
