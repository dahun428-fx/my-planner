"""기준표(SP13-02): 버전이 붙은 TOML을 읽고, 점 사이를 선형으로 잇는다."""
from __future__ import annotations

import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from itertools import pairwise
from pathlib import Path
from typing import Any

Points = tuple[tuple[float, float], ...]

_DEFAULT_DIR = Path(__file__).parent / "benchmarks"


@dataclass(frozen=True)
class Bench:
    version: str
    effective_from: date
    raw: Mapping[str, Any]

    def table(self, *path: str) -> Mapping[str, Any]:
        node: Any = self.raw
        for key in path:
            node = node[key]
        return node

    def points(self, *path: str) -> Points:
        node = self.table(*path)
        return tuple((float(x), float(y)) for x, y in node)  # type: ignore[misc]

    def estimate(self, *path: str) -> bool:
        """그 표(맨 위 키)의 estimate. 하위 경로를 줘도 표 단위로 본다."""
        return bool(self.raw[path[0]]["estimate"])


def _read(path: Path) -> Bench:
    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    return Bench(
        version=str(raw["version"]),
        effective_from=date.fromisoformat(str(raw["effective_from"])),
        raw=raw,
    )


def _all(directory: Path | None) -> list[Bench]:
    base = directory or _DEFAULT_DIR
    return sorted((_read(p) for p in base.glob("*.toml")), key=lambda b: b.effective_from)


def load_bench(today: date, directory: Path | None = None) -> Bench:
    """effective_from <= today 중 가장 늦은 것. 없으면 가장 이른 것."""
    benches = _all(directory)
    if not benches:
        raise FileNotFoundError("기준표가 없습니다")
    valid = [b for b in benches if b.effective_from <= today]
    return valid[-1] if valid else benches[0]


def load_bench_version(version: str, directory: Path | None = None) -> Bench | None:
    for b in _all(directory):
        if b.version == version:
            return b
    return None


def interp(x: float, pts: Points) -> float:
    if x <= pts[0][0]:
        return pts[0][1]
    if x >= pts[-1][0]:
        return pts[-1][1]
    for (x0, y0), (x1, y1) in pairwise(pts):
        if x0 <= x <= x1:
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return pts[-1][1]
