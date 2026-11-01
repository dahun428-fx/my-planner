"""기준표 읽기(SP13-02)."""
from __future__ import annotations

import shutil
from datetime import date
from pathlib import Path

from my_planner.standing import bench as bench_mod
from my_planner.standing.bench import interp, load_bench, load_bench_version

BENCH_DIR = Path(bench_mod.__file__).parent / "benchmarks"


def test_load_bench_2026() -> None:
    b = load_bench(date(2026, 11, 1))
    assert b.version == "2026.1"
    assert interp(6000, b.points("income", "national", "30_34")) == 50 + 25 * 1000 / 1600


def test_future_bench_not_used_yet(tmp_path: Path) -> None:
    shutil.copy(BENCH_DIR / "2026.toml", tmp_path / "2026.toml")
    text = (BENCH_DIR / "2026.toml").read_text(encoding="utf-8")
    text = text.replace('version = "2026.1"', 'version = "2027.1"').replace(
        'effective_from = "2026-11-01"', 'effective_from = "2027-11-01"'
    )
    (tmp_path / "2027.toml").write_text(text, encoding="utf-8")
    assert load_bench(date(2027, 1, 5), tmp_path).version == "2026.1"
    assert load_bench(date(2027, 11, 1), tmp_path).version == "2027.1"
    assert load_bench(date(2020, 1, 1), tmp_path).version == "2026.1"


def test_load_bench_version() -> None:
    b = load_bench_version("2026.1")
    assert b is not None and b.effective_from == date(2026, 11, 1)
    assert load_bench_version("1999.1") is None


def test_interp_edges() -> None:
    pts = ((0.0, 0.0), (10.0, 20.0), (20.0, 100.0))
    assert interp(-5, pts) == 0
    assert interp(99, pts) == 100
    assert interp(10, pts) == 20
    assert interp(15, pts) == 60


def test_estimate_and_table() -> None:
    b = load_bench(date(2026, 11, 1))
    assert b.estimate("height") is True
    assert b.table("saving")["missing"] == 25


def test_every_table_has_source() -> None:
    raw = load_bench(date(2026, 11, 1)).raw
    tables = [k for k in raw if k not in ("version", "effective_from")]
    assert tables
    for name in tables:
        t = raw[name]
        assert isinstance(t["source"], str) and t["source"].strip(), name
        assert isinstance(t["year"], int) and not isinstance(t["year"], bool), name
        assert t["url"].startswith("https://"), name
        assert isinstance(t["estimate"], bool), name
