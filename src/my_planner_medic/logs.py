"""BE JSON 줄 로그 읽기 (스펙 3.2). 부를 때마다 열고 닫는다.

핸들을 쥐고 있으면 Windows에서 BE의 자정 회전(rename)이 실패한다. 회전 파일 이름은 BE
`logging_setup`과 같다: `my-planner.jsonl` → `my-planner.jsonl.YYYY-MM-DD`.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ACTIVE = "my-planner.jsonl"
_ROTATED_RE = re.compile(r"^" + re.escape(ACTIVE) + r"\.\d{4}-\d{2}-\d{2}$")


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


_SIG_SEP = "#"
_SIG_READ = 64 * 1024  # 첫 줄은 이보다 짧다(로그 한 줄)


@dataclass(frozen=True)
class LogCursor:
    """`file`은 `my-planner.jsonl#<첫 줄 sha1 앞 12자>`. 첫 줄이 아직 완성되지 않았으면 서명 없이 `my-planner.jsonl`."""

    file: str
    offset: int

    @property
    def signature(self) -> str:
        return self.file.partition(_SIG_SEP)[2]


def signature(path: Path) -> str:
    """파일 첫 완성 줄의 서명. 비었거나 첫 줄이 반쯤이면 ""."""
    with path.open("rb") as fh:
        head = fh.read(_SIG_READ)
    nl = head.find(b"\n")
    return "" if nl < 0 else hashlib.sha1(head[: nl + 1]).hexdigest()[:12]


def _cursor(sig: str, offset: int) -> LogCursor:
    return LogCursor(f"{ACTIVE}{_SIG_SEP}{sig}" if sig else ACTIVE, offset)


def _rotated(log_dir: Path) -> list[Path]:
    """회전 파일, 오래된 것부터(이름의 날짜순)."""
    return sorted(p for p in log_dir.iterdir() if _ROTATED_RE.match(p.name))


def _complete_end(path: Path) -> int:
    _, end = _read_from(path, 0)
    return end


def _rotated_chunks(log_dir: Path, cursor: LogCursor, active_sig: str) -> tuple[list[bytes], bool]:
    """커서가 가리키던 파일이 회전됐으면 (읽을 회전 파일 조각들, True). 아니면 ([], False).

    - 서명이 둘 다 있으면 서명으로 판정한다. 다르면 회전 파일을 최근 것부터 찾아, 맞는 파일은 위치부터
      끝까지, 그보다 새 회전 파일은 처음부터 읽는다. 맞는 것이 없으면 지금 파일만 처음부터 읽는다.
    - 어느 한쪽 서명이 없으면(옛 커서, 첫 줄이 반쯤) 크기로 판정한다: 위치가 지금 파일보다 크면
      가장 최근 회전 파일의 남은 줄을 읽는다.
    """
    if cursor.signature and active_sig:
        if cursor.signature == active_sig:
            return [], False
        rotated = _rotated(log_dir)
        for i in range(len(rotated) - 1, -1, -1):
            if signature(rotated[i]) == cursor.signature:
                chunks = [_read_from(rotated[i], cursor.offset, final=True)[0]]
                chunks += [_read_from(p, 0, final=True)[0] for p in rotated[i + 1:]]
                return chunks, True
        return [], True
    if (log_dir / ACTIVE).stat().st_size >= cursor.offset:
        return [], False
    rotated = _rotated(log_dir)
    if rotated and rotated[-1].stat().st_size >= cursor.offset:
        return [_read_from(rotated[-1], cursor.offset, final=True)[0]], True
    return [], True


def read_new_lines(
    log_dir: Path, cursor: LogCursor | None
) -> tuple[list[dict[str, Any]], LogCursor, int]:
    """지난 위치 뒤의 새 레코드, 새 커서, 깨진 줄 수. 파일은 부를 때마다 열고 닫는다.

    - 커서가 없으면(첫 실행) 지금 파일의 끝(완성된 줄 끝)에서 시작한다. 지난 기록으로 이슈를 열지 않는다.
    - 회전 판정은 `_rotated_chunks`. 회전됐으면 회전 파일의 남은 줄을 한 번 읽고 새 파일은 처음부터 읽는다.
    """
    active = log_dir / ACTIVE
    if not active.exists():
        return [], LogCursor(ACTIVE, 0), 0
    active_sig = signature(active)
    if cursor is None:
        return [], _cursor(active_sig, _complete_end(active)), 0
    chunks, rotated = _rotated_chunks(log_dir, cursor, active_sig)
    chunk, end = _read_from(active, 0 if rotated else cursor.offset)
    records: list[dict[str, Any]] = []
    bad = 0
    for c in (*chunks, chunk):
        more, more_bad = _parse(c)
        records += more
        bad += more_bad
    return records, _cursor(active_sig, end), bad
