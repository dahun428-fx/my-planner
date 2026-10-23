"""원문 기록 `data/transcripts/YYYY/MM/YYYY-MM-DD.md` (스펙 5.8). 덧붙이기만 한다.

본문은 쓰기 전에 호출하는 쪽이 `redact()`를 거친다.
"""

from __future__ import annotations

from datetime import datetime, time, tzinfo
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
