"""DB 백업: 매일 첫 tick에 `state/backups/planner-YYYY-MM-DD.db`, 최근 `keep`개 보관 (스펙 7).

SQLite 백업 API(`conn.backup`)로 임시 이름에 쓴 뒤 원자적으로 이름을 바꾼다. 쓰는 도중 멈춰도
완성되지 않은 파일이 백업 이름으로 남지 않는다.
"""

from __future__ import annotations

import contextlib
import os
import re
import sqlite3
from datetime import date
from pathlib import Path

BACKUP_PREFIX = "planner-"
_BACKUP_RE = re.compile(r"^planner-\d{4}-\d{2}-\d{2}\.db$")


def backup_name(d: date) -> str:
    return f"{BACKUP_PREFIX}{d.isoformat()}.db"


def daily_backup(conn: sqlite3.Connection, backups_dir: Path, today: date, keep: int) -> Path | None:
    """오늘(논리적 날짜) 백업을 만들고 만든 경로를 돌려준다. 이미 있으면 None. 그 뒤 `keep`개만 남긴다."""
    backups_dir = Path(backups_dir)
    backups_dir.mkdir(parents=True, exist_ok=True)
    target = backups_dir / backup_name(today)
    if target.exists():
        _prune(backups_dir, keep)
        return None
    tmp = target.with_name(target.name + ".tmp")
    try:
        dest = sqlite3.connect(tmp)
        try:
            conn.backup(dest)
        finally:
            dest.close()
        os.replace(tmp, target)
    except BaseException:
        with contextlib.suppress(OSError):
            tmp.unlink()
        raise
    _prune(backups_dir, keep)
    return target


def _prune(backups_dir: Path, keep: int) -> None:
    """이름(날짜)순으로 가장 최근 `keep`개만 남긴다. 백업 이름이 아닌 파일은 건드리지 않는다."""
    found = sorted(p for p in backups_dir.iterdir() if _BACKUP_RE.match(p.name))
    for old in found[: max(len(found) - keep, 0)]:
        old.unlink()
