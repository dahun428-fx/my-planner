"""SQLite 연결과 마이그레이션 (스펙 4, 7: WAL, PRAGMA user_version + migrations/NNN_*.sql)."""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).parent / "migrations"
_MIGRATION_RE = re.compile(r"^(\d{3})_.+\.sql$")


def open_db(path: Path | str) -> sqlite3.Connection:
    """DB를 연다. WAL, foreign_keys=ON, Row 팩토리."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def _migrations() -> list[tuple[int, Path]]:
    found: list[tuple[int, Path]] = []
    for p in MIGRATIONS_DIR.iterdir():
        m = _MIGRATION_RE.match(p.name)
        if m:
            found.append((int(m.group(1)), p))
    found.sort()
    return found


def migrate(conn: sqlite3.Connection) -> int:
    """`user_version`보다 번호가 큰 마이그레이션만 번호순으로, 하나씩 트랜잭션 안에서 적용한다."""
    current = conn.execute("PRAGMA user_version").fetchone()[0]
    for number, path in _migrations():
        if number <= current:
            continue
        sql = path.read_text(encoding="utf-8")
        try:
            # executescript는 열린 트랜잭션을 먼저 커밋하고, 그 밖의 트랜잭션 제어는 하지 않는다.
            conn.executescript(f"BEGIN;\n{sql}\nPRAGMA user_version = {number};\nCOMMIT;")
        except Exception:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        current = number
    return current


def integrity_ok(conn: sqlite3.Connection) -> bool:
    """시작할 때의 무결성 검사. `quick_check`는 색인 대조를 빼서 빠르다. 결과가 "ok"이면 건강하다."""
    row = conn.execute("PRAGMA quick_check").fetchone()
    return row is not None and row[0] == "ok"
