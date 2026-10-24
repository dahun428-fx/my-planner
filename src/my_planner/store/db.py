"""SQLite 연결과 마이그레이션 (스펙 4, 7: WAL, PRAGMA user_version + migrations/NNN_*.sql)."""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).parent / "migrations"
_MIGRATION_RE = re.compile(r"^(\d{3})_.+\.sql$")

# 연결마다 지금 트랜잭션 깊이(키: id(conn)). 이벤트 루프 스레드 하나에서만 쓴다(스펙 4.3).
_DEPTH: dict[int, int] = {}


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


def open_ro(path: Path | str) -> sqlite3.Connection:
    """읽기 전용 연결(스펙 4.3). Windows 경로를 `file:` 뒤에 그대로 붙이면 열리지 않아 `Path.as_uri()`로 만든다."""
    conn = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[None]:
    """연결 단위 트랜잭션. 가장 바깥에서만 `BEGIN IMMEDIATE`·커밋·롤백한다.

    안쪽은 `SAVEPOINT`로 합류한다: 안쪽에서 예외가 나면 안쪽의 쓰기만 되돌리고(`ROLLBACK TO`) 예외를 올린다.
    바깥이 그 예외를 잡고 계속해도 안쪽에서 일부만 한 쓰기는 커밋되지 않는다. 커밋은 바깥에서 한 번뿐이다.

    저장소 함수가 바깥 트랜잭션 안에서 불려도 그 자리에서 커밋하지 않는다(예전 연결 컨텍스트 관리자는 커밋했다).
    바깥에서 이미 암묵 트랜잭션이 열려 있으면(sqlite3 기본 모드의 DML) 새로 열지 않고 그것을 끝낸다:
    예전 연결 컨텍스트 관리자와 같은 결과다.
    """
    key = id(conn)
    depth = _DEPTH.get(key, 0)
    if depth:
        name = f"tx_{depth}"
        conn.execute(f"SAVEPOINT {name}")
        _DEPTH[key] = depth + 1
        try:
            yield
        except BaseException:
            conn.execute(f"ROLLBACK TO {name}")
            conn.execute(f"RELEASE {name}")
            raise
        else:
            conn.execute(f"RELEASE {name}")
        finally:
            _DEPTH[key] = depth
        return
    if not conn.in_transaction:
        conn.execute("BEGIN IMMEDIATE")
    _DEPTH[key] = 1
    try:
        yield
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        _DEPTH.pop(key, None)


def _migrations() -> list[tuple[int, Path]]:
    found: list[tuple[int, Path]] = []
    for p in MIGRATIONS_DIR.iterdir():
        m = _MIGRATION_RE.match(p.name)
        if m:
            found.append((int(m.group(1)), p))
    found.sort()
    return found


def migrate(conn: sqlite3.Connection, *, upto: int | None = None) -> int:
    """`user_version`보다 번호가 큰 마이그레이션만 번호순으로, 하나씩 트랜잭션 안에서 적용한다.

    `upto`를 주면 그 번호까지만 적용한다(옛 판 DB를 만드는 시험용).
    """
    current = conn.execute("PRAGMA user_version").fetchone()[0]
    for number, path in _migrations():
        if number <= current or (upto is not None and number > upto):
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


LATEST_VERSION: int = max(n for n, _ in _migrations())


def integrity_ok(conn: sqlite3.Connection) -> bool:
    """시작할 때의 무결성 검사. `quick_check`는 색인 대조를 빼서 빠르다. 결과가 "ok"이면 건강하다."""
    row = conn.execute("PRAGMA quick_check").fetchone()
    return row is not None and row[0] == "ok"
