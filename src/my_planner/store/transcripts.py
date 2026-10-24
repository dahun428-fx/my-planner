"""원문 기록 `data/transcripts/YYYY/MM/YYYY-MM-DD.md` (스펙 5.8). 덧붙이기만 한다.

본문은 쓰기 전에 호출하는 쪽이 `redact()`를 거친다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, tzinfo
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

from my_planner.clock import local, logical_date

Speaker = Literal["사용자", "비서"]
Channel = Literal["telegram", "app"]

# 클라이언트가 준 `message.id`로 쓸 수 있는 모양(스펙 6.4.6). 아니면 `u-<대화>-<|inbound_id|>`
_CLIENT_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def app_user_message_id(conversation_id: int, inbound_id: int, client_id: str | None = None) -> str:
    """앱 통로 사용자 줄의 id: 받은 `message.id`(모양이 맞으면), 아니면 `u-<대화>-<|inbound_id|>` (스펙 6.4.6)."""
    if client_id is not None and _CLIENT_ID.match(client_id):
        return client_id
    return f"u-{conversation_id}-{abs(inbound_id)}"


def app_secretary_message_id(conversation_id: int, inbound_id: int) -> str:
    """앱 통로 비서 줄의 id(`POST /chat`의 `start.messageId`): `m-<대화>-<|inbound_id|>` (스펙 6.4.1, 6.4.6)."""
    return f"m-{conversation_id}-{abs(inbound_id)}"


@dataclass
class TranscriptMessage:
    """대화 하나의 줄. `id`는 바뀌지 않는다(스펙 6.4.6): 머리글의 `#<id>`, 없으면 `l-<대화>-<n>`."""

    at: datetime
    speaker: Speaker
    text: str
    tools: list[str] = field(default_factory=list)
    channel: Channel = "telegram"
    id: str = ""


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
        *,
        channel: Channel = "telegram",
        message_id: str | None = None,
    ) -> None:
        """`channel="app"`이면 머리글 끝에 ` @app`(앞에 `#<message_id>`가 있으면 함께). 텔레그램 머리글은 SP1 그대로(7.4).

        `message_id`는 `inbound_id`가 있는 앱 줄에만 준다(`app_user_message_id`, `app_secretary_message_id`).
        """
        conv = f"[{conversation_id}]" if conversation_id is not None else "[-]"
        header = f"### {local(at, self.tz):%H:%M} {speaker} {conv}"
        if run_key:
            header += f" ({run_key})"
        if channel == "app":
            if message_id is not None:
                header += f" #{message_id}"
            header += " @app"
        lines = [header]
        lines += [f"> 도구: {name}" for name in tools or []]
        lines += ["", _escape_headers(text.rstrip("\n")), "", ""]
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

    def messages(self, conversation_id: int) -> list[TranscriptMessage]:
        """그 대화의 모든 줄을 원문 기록 순서(날짜 파일 순, 파일 안에서는 위에서부터)로 (스펙 6.4.6).

        `id`: 머리글에 `#<id>`가 있으면 그것, 아니면 `l-<대화>-<n>`(`n`은 `#<id>`가 있는 줄도 센 1부터의 번호).
        시각은 파일의 논리적 날짜와 머리글 `HH:MM`으로 만든다: 하루 경계 전의 `HH:MM`은 다음 달력 날이다.
        """
        zone = ZoneInfo(self.tz) if isinstance(self.tz, str) else self.tz
        out: list[TranscriptMessage] = []
        for path in sorted(self.root.rglob("*.md")):
            try:
                file_date = date.fromisoformat(path.stem)
            except ValueError:
                continue
            for e in _parse(path):
                if e.conversation != str(conversation_id):
                    continue
                hh, mm = int(e.hhmm[:2]), int(e.hhmm[3:])
                clock_time = time(hh, mm)
                day = file_date + timedelta(days=1) if clock_time < self.boundary else file_date
                text = "\n".join(
                    line[1:] if line.startswith(_HEADER_ESCAPE + "### ") else line for line in e.body_lines
                ).strip()
                out.append(
                    TranscriptMessage(
                        at=datetime.combine(day, clock_time, tzinfo=zone),
                        speaker=e.speaker,  # type: ignore[arg-type]
                        text=text,
                        tools=e.tools,
                        channel="app" if e.app else "telegram",
                        id=e.message_id or f"l-{conversation_id}-{len(out) + 1}",
                    )
                )
        return out

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


# 본문 줄이 `### `로 시작하면 머리글로 읽히지 않게 앞에 폭 없는 공백(U+200B)을 붙인다
_HEADER_ESCAPE = "\u200b"


def _escape_headers(text: str) -> str:
    return "\n".join(_HEADER_ESCAPE + line if line.startswith("### ") else line for line in text.split("\n"))


# `### 21:05 사용자 [44] (evening_checkin) #msg-abc @app`. 회차 표시, `#<id>`, ` @app`은 없을 수 있다
_HEADER = re.compile(
    r"^### (?P<hhmm>\d{2}:\d{2}) (?P<speaker>사용자|비서) \[(?P<conv>\d+|-)\]"
    r"(?: \((?P<run>[^)]*)\))?(?: #(?P<id>[A-Za-z0-9_-]{1,64}))?(?P<app> @app)?$"
)
_TOOL_PREFIX = "> 도구: "


@dataclass
class _Entry:
    hhmm: str
    speaker: str
    conversation: str
    message_id: str | None
    app: bool
    body_lines: list[str]  # 도구 줄은 뺀 본문 줄
    tools: list[str]


def _parse(path: Path) -> list[_Entry]:
    out: list[_Entry] = []
    cur: _Entry | None = None
    for line in path.read_text(encoding="utf-8").splitlines():
        m = _HEADER.match(line)
        if m:
            cur = _Entry(m["hhmm"], m["speaker"], m["conv"], m["id"], m["app"] is not None, [], [])
            out.append(cur)
        elif cur is not None:
            if line.startswith(_TOOL_PREFIX):
                cur.tools.append(line[len(_TOOL_PREFIX):].strip())
            else:
                cur.body_lines.append(line)
    return out


def _entries(path: Path, conversation_id: int) -> list[tuple[str, str, str]]:
    """파일의 (시각, 화자, 본문) 목록. 해당 대화의 것만, 도구 줄은 뺀다."""
    return [
        (e.hhmm, e.speaker, "\n".join(e.body_lines).strip())
        for e in _parse(path)
        if e.conversation == str(conversation_id)
    ]
