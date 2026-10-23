"""원문 기록 `data/transcripts/YYYY/MM/YYYY-MM-DD.md` (스펙 5.8). 덧붙이기만 한다.

본문은 쓰기 전에 호출하는 쪽이 `redact()`를 거친다.
"""

from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta, tzinfo
from pathlib import Path
from typing import Literal

from my_planner.clock import local, logical_date

Speaker = Literal["사용자", "비서"]


class TranscriptStore:
    def __init__(self, data_dir: Path, tz: str | tzinfo, boundary: time) -> None:
        self.root = Path(data_dir).resolve() / "transcripts"
        self.tz = tz
        self.boundary = boundary

    def path_for(self, at: datetime) -> Path:
        d = logical_date(at, self.tz, self.boundary)
        return self.root / f"{d.year:04d}" / f"{d.month:02d}" / f"{d.isoformat()}.md"

    def append(
        self,
        at: datetime,
        speaker: Speaker,
        conversation_id: int | None,
        run_key: str | None,
        text: str,
        tools: list[str] | None = None,
    ) -> None:
        conv = f"[{conversation_id}]" if conversation_id is not None else "[-]"
        header = f"### {local(at, self.tz):%H:%M} {speaker} {conv}"
        if run_key:
            header += f" ({run_key})"
        lines = [header]
        lines += [f"> 도구: {name}" for name in tools or []]
        lines += ["", text.rstrip("\n"), "", ""]
        path = self.path_for(at)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(lines))

    def read_range(self, start: date, end: date, *, max_chars: int = 20000) -> str:
        """논리적 날짜 `start`~`end`(포함)의 원문 기록. 없는 날은 건너뛴다. 너무 길면 앞부분만."""
        parts: list[str] = []
        d = start
        while d <= end:
            path = self.root / f"{d.year:04d}" / f"{d.month:02d}" / f"{d.isoformat()}.md"
            if path.exists():
                parts.append(f"# {d.isoformat()}\n\n" + path.read_text(encoding="utf-8"))
            d += timedelta(days=1)
        return "\n".join(parts)[:max_chars]

    def recent(self, conversation_id: int, n: int = 20, *, skip_last: int = 0) -> str:
        """그 대화의 최근 n개 메시지를 시간순으로 `[HH:MM] 사용자: 본문` 형태로 돌려준다. 없으면 `""`.

        `skip_last`: 가장 최근 몇 개를 뺀다(방금 기록한 현재 메시지를 중복해 넣지 않으려고).
        """
        want = n + skip_last
        found: list[str] = []  # 최신 것부터
        for path in sorted(self.root.rglob("*.md"), reverse=True):
            if len(found) >= want:
                break
            for hhmm, speaker, body in reversed(_entries(path, conversation_id)):
                found.append(f"[{hhmm}] {speaker}: {body}")
                if len(found) >= want:
                    break
        return "\n".join(reversed(found[skip_last:]))


_HEADER = re.compile(r"^### (\d{2}:\d{2}) (사용자|비서) \[(\d+|-)\](?: \(.*\))?$")


def _entries(path: Path, conversation_id: int) -> list[tuple[str, str, str]]:
    """파일의 (시각, 화자, 본문) 목록. 해당 대화의 것만, 도구 줄은 뺀다."""
    out: list[tuple[str, str, str]] = []
    cur: tuple[str, str, str] | None = None
    lines: list[str] = []

    def flush() -> None:
        if cur is not None and cur[2] == str(conversation_id):
            body = "\n".join(line for line in lines if not line.startswith("> 도구: ")).strip()
            out.append((cur[0], cur[1], body))

    for line in path.read_text(encoding="utf-8").splitlines():
        m = _HEADER.match(line)
        if m:
            flush()
            cur, lines = (m.group(1), m.group(2), m.group(3)), []
        else:
            lines.append(line)
    flush()
    return out
