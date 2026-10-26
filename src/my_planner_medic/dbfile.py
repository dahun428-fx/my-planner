"""planner.db 파일 다루기 (스펙 2장 예외, 5장 5·7단계, 보관).

medic이 `planner.db`를 바꾸는 유일한 길은 배포 롤백의 `move_with_wal` + `restore`이고, 그때 BE 작업은 꺼져 있다.
`schema_version`과 `backup_to`는 읽기 전용(`mode=ro`) 연결만 연다(체크포인트·WAL 삭제가 일어나지 않는다).
"""

from __future__ import annotations

import logging
import os
import shutil
import sqlite3
from contextlib import closing
from pathlib import Path

log = logging.getLogger(__name__)

SIDE_SUFFIXES = ("-wal", "-shm")


def _ro_uri(db: Path) -> str:
    return db.resolve().as_uri() + "?mode=ro"


def _side(db: Path, suffix: str) -> Path:
    return db.with_name(db.name + suffix)


def schema_version(db: Path) -> int:
    """`PRAGMA user_version`. 파일이 없거나 못 열면 `sqlite3.Error`(새 파일을 만들지 않는다)."""
    with closing(sqlite3.connect(_ro_uri(db), uri=True)) as conn:
        return int(conn.execute("PRAGMA user_version").fetchone()[0])


def backup_to(db: Path, dest: Path) -> None:
    """SQLite 백업 API로 `dest`에 복사한다. 임시 이름에 쓴 뒤 `os.replace`."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".tmp")
    tmp.unlink(missing_ok=True)
    try:
        with closing(sqlite3.connect(_ro_uri(db), uri=True)) as src, closing(sqlite3.connect(tmp)) as out:
            src.backup(out)
        os.replace(tmp, dest)
    finally:
        tmp.unlink(missing_ok=True)


def move_with_wal(db: Path, dest_dir: Path) -> None:
    """`db`, `db-wal`, `db-shm` 중 있는 것을 모두 `dest_dir`로 옮긴다. 이미 있는 파일은 덮지 않는다."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    files = [p for p in (db, *(_side(db, s) for s in SIDE_SUFFIXES)) if p.exists()]
    for p in files:
        if (dest_dir / p.name).exists():
            raise FileExistsError(str(dest_dir / p.name))
    for p in files:  # 본 파일 먼저: 중단되면 다음 시도가 남은 -wal·-shm을 옮긴다
        os.replace(p, dest_dir / p.name)


def move_leftovers(db: Path, dest_dir: Path) -> None:
    """본 파일은 이미 옮겨진 뒤: 남은 `-wal`·`-shm` 중 `dest_dir`에 없는 것만 옮긴다."""
    for s in SIDE_SUFFIXES:
        p = _side(db, s)
        if p.exists() and not (dest_dir / p.name).exists():
            os.replace(p, dest_dir / p.name)


def restore(src: Path, db: Path) -> None:
    """`db-wal`·`db-shm`을 지우고 `src`를 `db`로 복사한다(임시 이름 → `os.replace`)."""
    for s in SIDE_SUFFIXES:
        _side(db, s).unlink(missing_ok=True)
    tmp = db.with_name(db.name + ".restore-tmp")
    shutil.copyfile(src, tmp)
    os.replace(tmp, db)


def prune(dir: Path, pattern: str, keep: int) -> None:
    """`pattern`에 맞는 항목 중 최근(mtime) `keep`개만 남긴다. 폴더는 통째로 지운다."""
    if not dir.is_dir():
        return
    items = sorted(dir.glob(pattern), key=lambda p: (p.stat().st_mtime, p.name), reverse=True)
    for p in items[max(keep, 0):]:
        try:
            if p.is_dir() and not p.is_symlink():
                shutil.rmtree(p)
            else:
                p.unlink()
        except OSError as exc:
            log.warning("prune_failed %s (%s)", p.name, type(exc).__name__)
