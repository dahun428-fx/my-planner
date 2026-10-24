from __future__ import annotations

import filecmp
import os
import sqlite3
from pathlib import Path

import pytest

from my_planner_medic import dbfile


def make_db(path: Path, version: int, rows: int = 1) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE TABLE IF NOT EXISTS t(a)")
    conn.executemany("INSERT INTO t VALUES(?)", [(i,) for i in range(rows)])
    conn.execute(f"PRAGMA user_version={version}")
    conn.commit()
    conn.close()


def test_schema_version_reads_user_version_without_writing(tmp_path: Path) -> None:
    db = tmp_path / "planner.db"
    make_db(db, 7)
    before = db.read_bytes()
    assert dbfile.schema_version(db) == 7
    assert db.read_bytes() == before


def test_schema_version_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(sqlite3.Error):
        dbfile.schema_version(tmp_path / "nope.db")
    assert not (tmp_path / "nope.db").exists()


def test_backup_to_copies_through_wal_and_leaves_no_temp(tmp_path: Path) -> None:
    db = tmp_path / "planner.db"
    make_db(db, 2, rows=3)
    live = sqlite3.connect(db)  # 체크포인트 안 된 WAL 쓰기
    live.execute("PRAGMA wal_autocheckpoint=0")
    live.execute("INSERT INTO t VALUES(99)")
    live.commit()
    dest = tmp_path / "backups" / "pre-deploy-abc.db"
    dbfile.backup_to(db, dest)
    live.close()
    got = sqlite3.connect(dest)
    assert got.execute("SELECT count(*) FROM t").fetchone() == (4,)
    assert got.execute("PRAGMA user_version").fetchone() == (2,)
    got.close()
    assert sorted(p.name for p in dest.parent.iterdir()) == ["pre-deploy-abc.db"]


def test_move_with_wal_moves_all_present_and_never_overwrites(tmp_path: Path) -> None:
    db = tmp_path / "planner.db"
    db.write_bytes(b"main")
    Path(f"{db}-wal").write_bytes(b"wal")
    dest = tmp_path / "failed-x"
    dbfile.move_with_wal(db, dest)
    assert sorted(p.name for p in dest.iterdir()) == ["planner.db", "planner.db-wal"]
    assert not db.exists()
    db.write_bytes(b"again")
    with pytest.raises(FileExistsError):
        dbfile.move_with_wal(db, dest)
    assert (dest / "planner.db").read_bytes() == b"main"
    assert db.read_bytes() == b"again"


def test_restore_removes_wal_shm_and_copies(tmp_path: Path) -> None:
    src = tmp_path / "backup.db"
    make_db(src, 1)
    db = tmp_path / "planner.db"
    db.write_bytes(b"x")
    Path(f"{db}-wal").write_bytes(b"w")
    Path(f"{db}-shm").write_bytes(b"s")
    dbfile.restore(src, db)
    assert filecmp.cmp(src, db, shallow=False)
    assert not Path(f"{db}-wal").exists() and not Path(f"{db}-shm").exists()


def test_prune_keeps_newest(tmp_path: Path) -> None:
    for i in range(4):
        p = tmp_path / f"pre-deploy-{i}.db"
        p.write_bytes(b"x")
        os.utime(p, (1000 + i, 1000 + i))
        d = tmp_path / f"failed-{i}"
        d.mkdir()
        (d / "planner.db").write_bytes(b"x")
        os.utime(d, (1000 + i, 1000 + i))
    dbfile.prune(tmp_path, "pre-deploy-*.db", 2)
    dbfile.prune(tmp_path, "failed-*", 1)
    names = sorted(p.name for p in tmp_path.iterdir())
    assert names == ["failed-3", "pre-deploy-2.db", "pre-deploy-3.db"]
