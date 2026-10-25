"""SQLite 연결과 마이그레이션 (스펙 4, 7: WAL, PRAGMA user_version + migrations/NNN_*.sql)."""

from __future__ import annotations

import logging
import re
import sqlite3
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).parent / "migrations"
_MIGRATION_RE = re.compile(r"^(\d{3})_.+\.sql$")

# 연결마다 지금 트랜잭션 깊이(키: id(conn)). 이벤트 루프 스레드 하나에서만 쓴다(스펙 4.3).
_DEPTH: dict[int, int] = {}
# 가장 바깥 트랜잭션이 커밋된 뒤에 부를 일(키: id(conn)). 깊이마다 목록 하나(맨 끝이 지금 SAVEPOINT):
# 그 깊이가 롤백되면 그 목록을 버리고, 풀리면(RELEASE) 바깥 목록에 합친다(`after_commit`)
_AFTER: dict[int, list[list[Callable[[], None]]]] = {}
log = logging.getLogger(__name__)
_WRITE_RE = re.compile(r"^\s*(INSERT|UPDATE|DELETE|REPLACE)\b", re.IGNORECASE)


def is_write(sql: str) -> bool:
    """데이터를 바꾸는 문 하나(`INSERT`, `UPDATE`, `DELETE`, `REPLACE`)인가. 마이그레이션 스크립트(`BEGIN;…`)는 아니다."""
    return _WRITE_RE.match(sql) is not None


def open_db(path: Path | str, *, on_write: Callable[[str], None] | None = None) -> sqlite3.Connection:
    """DB를 연다. WAL, foreign_keys=ON, Row 팩토리.

    `on_write`(시험 이음매, SP3-4 16장 쓰기 경로 감시): 데이터를 바꾸는 문마다 그 SQL로 부른다(`set_trace_callback`).
    부른 자리의 호출 스택은 그 쓰기를 한 코드다. 운영에서는 쓰지 않는다.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    if on_write is not None:
        conn.set_trace_callback(lambda sql: on_write(sql) if is_write(sql) else None)
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


def after_commit(conn: sqlite3.Connection, fn: Callable[[], None]) -> None:
    """`fn`을 그 연결의 가장 바깥 트랜잭션이 커밋된 뒤에 부른다. 트랜잭션 밖이면 바로 부른다. 롤백되면 부르지 않는다.

    롤백될 수 있는 변경(예: 답한 회차)에 딸린 바깥 일(버튼 거두기 걸기)을 커밋 뒤로 미룬다. 안쪽 SAVEPOINT에서
    걸었고 그 SAVEPOINT가 롤백되면, 바깥이 예외를 잡고 커밋해도 부르지 않는다.
    """
    stack = _AFTER.get(id(conn))
    if _DEPTH.get(id(conn), 0) and stack:
        stack[-1].append(fn)
    else:
        fn()


def _run_after(fns: list[Callable[[], None]]) -> None:
    """커밋 뒤의 일을 하나씩. 하나가 실패해도 커밋은 이미 됐다: 종류만 남기고 나머지를 부른다."""
    for fn in fns:
        try:
            fn()
        except Exception as e:  # noqa: BLE001 - 커밋된 변경을 실패로 돌려주지 않는다
            log.warning("after_commit_error", extra={"error_type": type(e).__name__})


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
        stack = _AFTER.setdefault(key, [[]])
        stack.append([])
        try:
            yield
        except BaseException:
            conn.execute(f"ROLLBACK TO {name}")
            conn.execute(f"RELEASE {name}")
            stack.pop()  # 롤백된 SAVEPOINT에서 건 일은 버린다
            raise
        else:
            conn.execute(f"RELEASE {name}")
            done = stack.pop()
            stack[-1].extend(done)
        finally:
            _DEPTH[key] = depth
        return
    if not conn.in_transaction:
        conn.execute("BEGIN IMMEDIATE")
    _DEPTH[key] = 1
    _AFTER[key] = [[]]
    try:
        yield
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        _DEPTH.pop(key, None)
        stack = _AFTER.pop(key, [[]])
    _run_after(stack[0])


class MigrationGapError(RuntimeError):
    """마이그레이션 파일 번호가 1부터 빈칸 없이 이어지지 않는다(스펙 SP9 11장). 적용 전에 거부한다."""


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
    migrations = _migrations()
    for expected, (number, _) in enumerate(migrations, start=1):
        if number == expected - 1:
            raise MigrationGapError(f"duplicate migration {number:03d}")
        if number != expected:
            raise MigrationGapError(f"missing migration {expected:03d}")
    for number, path in migrations:
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
