"""`standing import` 가져오기 (SP13-07). 고정 자료는 가짜 사람의 것만 쓴다."""

from __future__ import annotations

import io
import json
from datetime import UTC, datetime
from pathlib import Path

from my_planner import cli
from my_planner.clock import FakeClock
from my_planner.standing.importer import run_import
from my_planner.store.db import open_db
from tests.test_seed_life import HeldLock, NoLock

FIXTURE = Path(__file__).parent / "fixtures" / "standing_sample.json"
NOW = datetime(2026, 10, 24, 3, 0, tzinfo=UTC)


def fixture() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def write(tmp_path: Path, data: object) -> Path:
    p = tmp_path / "in.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


def run(root: Path, file: Path, *, dry_run: bool = False, lock=NoLock) -> tuple[int, str]:
    out = io.StringIO()
    code = run_import(root, file, dry_run=dry_run, out=out, lock_factory=lock, clock=FakeClock(NOW))
    return code, out.getvalue()


def count(root: Path, table: str, where: str = "1") -> int:
    if not (root / "state" / "planner.db").exists():
        return 0
    c = open_db(root / "state" / "planner.db")
    try:
        return c.execute(f"SELECT COUNT(*) FROM {table} WHERE {where}").fetchone()[0]
    finally:
        c.close()


def test_import_twice_same_rows(tmp_path):
    f = write(tmp_path, fixture())
    assert run(tmp_path, f) == (0, "imported: 43, skipped: 0\n")
    n = count(tmp_path, "standing_measures")
    assert n == 43
    assert run(tmp_path, f) == (0, "imported: 0, skipped: 43\n")
    assert count(tmp_path, "standing_measures") == n


def test_import_invalid_writes_nothing(tmp_path):
    data = fixture()
    data["measures"][3] = {"metric": "height_cm", "value": 987, "measured_on": "2026-10-01"}
    code, out = run(tmp_path, write(tmp_path, data))
    assert code == 5
    assert out.strip() == "invalid: 3 height_cm"
    assert "987" not in out
    assert count(tmp_path, "standing_measures") == 0


def test_import_grants_x14_and_snapshot(tmp_path):
    run(tmp_path, write(tmp_path, fixture()))
    assert count(tmp_path, "status_xp_ledger", "source_kind = 'standing' AND source_ref = 'standing:2026-Q4' "
                 "AND amount = 20 AND label = '측정값 기록'") == 1
    assert count(tmp_path, "standing_snapshots") > 0
    assert count(tmp_path, "standing_measures", "source_kind = 'import'") == 43
    assert count(tmp_path, "standing_measures", "metric = 'face_rating' AND reliability = 'low'") == 1


def test_import_dry_run(tmp_path):
    code, out = run(tmp_path, write(tmp_path, fixture()), dry_run=True)
    assert (code, out) == (0, "imported: 43, skipped: 0\n")
    assert not (tmp_path / "state" / "planner.db").exists()


def test_import_bad_file_code_6(tmp_path):
    assert run(tmp_path, write(tmp_path, [1]))[0] == 6
    assert run(tmp_path, write(tmp_path, {"version": 2, "measures": []}))[0] == 6
    assert run(tmp_path, tmp_path / "missing.json")[0] == 6


def test_import_running_code_3(tmp_path):
    assert run(tmp_path, write(tmp_path, fixture()), lock=HeldLock)[0] == 3


def test_cli_usage_mentions_standing():
    assert "standing import" in cli.USAGE


def test_import_dry_run_after_import(tmp_path):
    f = write(tmp_path, fixture())
    run(tmp_path, f)
    assert run(tmp_path, f, dry_run=True) == (0, "imported: 0, skipped: 43\n")


def test_import_dry_run_db_without_standing_tables(tmp_path):
    (tmp_path / "state").mkdir()
    open_db(tmp_path / "state" / "planner.db").close()  # 마이그레이션 전 빈 DB
    assert run(tmp_path, write(tmp_path, fixture()), dry_run=True) == (0, "imported: 43, skipped: 0\n")


def test_import_nothing_new_grants_nothing(tmp_path):
    f = write(tmp_path, fixture())
    run(tmp_path, f)
    xp, snaps = count(tmp_path, "status_xp_ledger"), count(tmp_path, "standing_snapshots")
    empty = write(tmp_path, {"version": 1, "measures": []})
    assert run(tmp_path, empty) == (0, "imported: 0, skipped: 0\n")
    run(tmp_path, f)  # 모두 중복
    assert (count(tmp_path, "status_xp_ledger"), count(tmp_path, "standing_snapshots")) == (xp, snaps)


def test_import_empty_on_fresh_db_grants_nothing(tmp_path):
    assert run(tmp_path, write(tmp_path, {"version": 1, "measures": []}))[0] == 0
    assert count(tmp_path, "status_xp_ledger", "source_kind = 'standing'") == 0
    assert count(tmp_path, "standing_snapshots") == 0
