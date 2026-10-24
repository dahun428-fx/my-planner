"""BE JSON 줄 로그 읽기 (스펙 3.2). 부를 때마다 열고 닫는다.

핸들을 쥐고 있으면 Windows에서 BE의 자정 회전(rename)이 실패한다. 회전 파일 이름은 BE
`logging_setup`과 같다: `my-planner.jsonl` → `my-planner.jsonl.YYYY-MM-DD`.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ACTIVE = "my-planner.jsonl"
_ROTATED_RE = re.compile(r"^" + re.escape(ACTIVE) + r"\.\d{4}-\d{2}-\d{2}$")


@dataclass(frozen=True)
class LogCursor:
    file: str
    offset: int


def _read_from(path: Path, offset: int, *, final: bool = False) -> tuple[bytes, int]:
    """`offset`부터 끝까지 읽어 완성된 줄(마지막 `\\n`까지)과 그 끝 위치를 돌려준다.

    `final`(회전이 끝나 더 쓰이지 않는 파일)이면 줄 끝이 없는 마지막 줄도 넣는다.
    """
    with path.open("rb") as fh:
        fh.seek(offset)
        data = fh.read()
    end = len(data) if final else data.rfind(b"\n") + 1  # 반쯤 쓰인 마지막 줄은 다음 회차로 미룬다
    return data[:end], offset + end


def _parse(chunk: bytes) -> tuple[list[dict[str, Any]], int]:
    records: list[dict[str, Any]] = []
    bad = 0
    for raw in chunk.split(b"\n"):
        raw = raw.strip()
        if not raw:
            continue
        try:
            rec = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            bad += 1
            continue
        if isinstance(rec, dict):
            records.append(rec)
        else:
            bad += 1
    return records, bad


def _newest_rotated(log_dir: Path) -> Path | None:
    rotated = sorted(p for p in log_dir.iterdir() if _ROTATED_RE.match(p.name))
    return rotated[-1] if rotated else None


def _complete_end(path: Path) -> int:
    _, end = _read_from(path, 0)
    return end


def read_new_lines(
    log_dir: Path, cursor: LogCursor | None
) -> tuple[list[dict[str, Any]], LogCursor, int]:
    """지난 위치 뒤의 새 레코드, 새 커서, 깨진 줄 수.

    - 커서가 없으면(첫 실행) 지금 파일의 끝(완성된 줄 끝)에서 시작한다. 지난 기록으로 이슈를 열지 않는다.
    - 읽던 위치가 지금 파일 크기보다 크면 회전된 것으로 본다: 가장 최근 회전 파일의 남은 줄을 한 번
      읽고, 새 파일은 처음부터 읽는다.
    """
    active = log_dir / ACTIVE
    if not active.exists():
        return [], LogCursor(ACTIVE, 0), 0
    if cursor is None:
        return [], LogCursor(ACTIVE, _complete_end(active)), 0
    records: list[dict[str, Any]] = []
    bad = 0
    offset = cursor.offset
    if active.stat().st_size < offset:
        rotated = _newest_rotated(log_dir)
        if rotated is not None and rotated.stat().st_size >= offset:
            chunk, _ = _read_from(rotated, offset, final=True)
            records, bad = _parse(chunk)
        offset = 0
    chunk, end = _read_from(active, offset)
    more, more_bad = _parse(chunk)
    return records + more, LogCursor(ACTIVE, end), bad + more_bad
