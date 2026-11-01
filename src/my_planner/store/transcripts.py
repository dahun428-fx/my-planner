"""원문 기록 `data/transcripts/YYYY/MM/YYYY-MM-DD.md` (스펙 5.8). 덧붙이기만 한다.

본문은 쓰기 전에 호출하는 쪽이 `redact()`를 거친다. 유일한 예외는 대화 지우기(SP9 7.7, `erase_conversation`)다:
그 대화의 줄을 `[지운 대화]` 한 줄로 바꿔 파일마다 다시 쓴다(임시 파일 + `os.replace`).
"""

from __future__ import annotations

import logging
import os
import re
import time as _time
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, tzinfo
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

from my_planner.clock import local, logical_date
from my_planner.domain import Agent

log = logging.getLogger(__name__)

Speaker = Literal["사용자", "비서", "운동메이트", "라이프 매니저", "전문가"]

# 대화 상대 → 원문 기록의 화자 이름(SP15 3장). 꼬리표는 ` @mate`·` @manager`(비서는 없음)
AGENT_SPEAKERS: dict[Agent, str] = {"secretary": "비서", "mate": "운동메이트", "manager": "라이프 매니저"}
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
        agent: Agent = "secretary",
    ) -> None:
        """`channel="app"`이면 머리글 끝에 ` @app`(앞에 `#<message_id>`가 있으면 함께). 텔레그램 머리글은 SP1 그대로(7.4).

        `message_id`는 `inbound_id`가 있는 앱 줄에만 준다(`app_user_message_id`, `app_secretary_message_id`).
        `agent="mate"`: 메이트 대화의 줄(사용자 줄도)이면 그 뒤에 ` @mate`(SP12 14장).
        `agent="manager"`: 라이프 매니저 대화의 줄이면 ` @manager`(SP15 13장).
        """
        conv = f"[{conversation_id}]" if conversation_id is not None else "[-]"
        header = f"### {local(at, self.tz):%H:%M} {speaker} {conv}"
        if run_key:
            header += f" ({run_key})"
        if channel == "app":
            if message_id is not None:
                header += f" #{message_id}"
            header += " @app"
        if agent == "mate":
            header += " @mate"
        elif agent == "manager":
            header += " @manager"
        lines = [header]
        lines += [f"> 도구: {name}" for name in tools or []]
        lines += ["", _escape_headers(text.rstrip("\n")), "", ""]
        path = self.path_for(at)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(lines))

    def read_range(
        self, start: date, end: date, *, max_chars: int = 20000, drop_app_secretary: bool = False,
        only_conversation: int | None = None, drop_mate: bool = False,
    ) -> str:
        """논리적 날짜 `start`~`end`(포함)의 원문 기록. 없는 날은 건너뛴다. 너무 길면 앞부분만.

        `drop_app_secretary`: 앱 대화의 비서 항목(머리글 끝 ` @app`)을 뺀다. 텔레그램 통로 두뇌의 `read_transcript`가
        쓴다: 앱 대화의 비서는 `get_status`로 받은 이룬 순간의 글을 옮겨 말했을 수 있다(SP8 1장 조건 7, 11장).
        `only_conversation`: 그 대화의 항목만 남긴다. 앱 통로 두뇌의 `read_transcript`가 쓴다: 다른 대화의 원문은
        주지 않는다(SP9 7.5, ADR 0014). 그날 그 대화의 항목이 없으면 그날 머리말도 넣지 않는다.
        `drop_mate`: 메이트·라이프 매니저 대화의 항목(머리글 끝 ` @mate`·` @manager`, 사용자 줄 포함)을 뺀다.
        비서의 `read_transcript`가 늘 쓴다: 비서가 메이트 대화의 원문(부상 글 등)도, 라이프 매니저 대화의 원문(돈·건강
        글 등)도 읽지 않는다(SP12 14장, SP15 13장, ADR 0014).
        """
        parts: list[str] = []
        d = start
        while d <= end:
            path = self.root / f"{d.year:04d}" / f"{d.month:02d}" / f"{d.isoformat()}.md"
            if path.exists():
                text = path.read_text(encoding="utf-8")
                if drop_app_secretary:
                    text = _without_app_secretary(text)
                if drop_mate:
                    text = _without_mate(text)
                if only_conversation is not None:
                    text = _only_conversation(text, str(only_conversation))
                if text.strip():
                    parts.append(f"# {d.isoformat()}\n\n" + text)
            d += timedelta(days=1)
        return "\n".join(parts)[:max_chars]

    def user_lines(self, day: date) -> list[tuple[str, str]]:
        """논리적 날짜 `day` 파일의 `사용자` 줄만 `(HH:MM, 본문)`으로, 오래된 것부터(두 통로, 이미 가린 글).

        하루 끝 순간 입력(SP8 6.3)이 쓴다. 비서 줄과 도구 줄은 넣지 않는다.
        """
        path = self.root / f"{day.year:04d}" / f"{day.month:02d}" / f"{day.isoformat()}.md"
        if not path.exists():
            return []
        return [
            (
                e.hhmm,
                "\n".join(
                    line[1:] if line.startswith(_HEADER_ESCAPE + "### ") else line for line in e.body_lines
                ).strip(),
            )
            for e in _parse(path)
            if e.speaker == "사용자"
        ]

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
        return "\n".join(self.recent_entries(conversation_id, n, skip_last=skip_last))

    def recent_entries(self, conversation_id: int, n: int = 20, *, skip_last: int = 0) -> list[str]:
        """`recent`의 메시지 목록(시간순, 메시지마다 한 항목). `n`이 0 이하면 빈 목록."""
        if n <= 0:
            return []
        want = n + skip_last
        found: list[str] = []  # 최신 것부터
        for path in sorted(self.root.rglob("*.md"), reverse=True):
            if len(found) >= want:
                break
            for hhmm, speaker, body in reversed(_entries(path, conversation_id)):
                found.append(f"[{hhmm}] {speaker}: {body}")
                if len(found) >= want:
                    break
        return list(reversed(found[skip_last:]))


ERASED_LINE = "[지운 대화]"  # 지운 대화의 줄 자리(SP9 7.7). 이어진 줄은 한 줄로 합친다. 읽을 때는 항목의 끝이다


def _day_path(root: Path, d: date) -> Path:
    return root / f"{d.year:04d}" / f"{d.month:02d}" / f"{d.isoformat()}.md"


def _erase_text(text: str, conversation: str) -> tuple[str, int]:
    """그 대화의 항목(머리글부터 다음 머리글 전까지)을 `[지운 대화]` 한 줄로. 이어진 것은 하나로. (새 글, 지운 항목 수)."""
    out: list[str] = []
    marker = ERASED_LINE + "\n\n"
    skipping = False
    count = 0
    for line in text.splitlines(keepends=True):
        bare = line.rstrip("\n")
        m = _HEADER.match(bare)
        if m is not None and m["conv"] == conversation:
            count += 1
            if not (out and out[-1] == marker):
                out.append(marker)
            skipping = True
            continue
        if m is not None or bare == ERASED_LINE:
            skipping = False
            if bare == ERASED_LINE and out and out[-1] == marker:
                skipping = True  # 앞서 지운 자리와 붙었다: 한 줄로
                continue
        if not skipping:
            out.append(line)
    return "".join(out), count


ERASE_RETRY_DELAYS: tuple[float, ...] = (0.2, 0.5, 1.0)  # 파일을 다른 프로그램이 잡고 있을 때 다시 해 보는 간격(초)


@dataclass(frozen=True)
class EraseResult:
    erased: int  # 지운 항목 수
    failed: tuple[date, ...]  # 다시 해 봐도 못 바꾼 날(하루 한 번 작업이 다시 해 본다)


def _erase_day(path: Path, conversation: str) -> int:
    text, n = _erase_text(path.read_text(encoding="utf-8"), conversation)
    if n:
        tmp = path.with_name(path.name + ".tmp")
        with tmp.open("w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        try:
            os.replace(tmp, path)
        except OSError:
            tmp.unlink(missing_ok=True)  # 임시 파일을 남기지 않는다(다음에 다시 만든다)
            raise
    return n


def erase_conversation(transcripts_dir: Path, conversation_id: int, from_day: date, to_day: date) -> EraseResult:
    """논리적 날짜 `from_day`~`to_day`(포함) 파일에서 그 대화의 줄을 `[지운 대화]`로 바꾼다(SP9 7.7).

    파일마다 같은 폴더의 임시 파일에 쓰고 `os.replace`로 바꿔 넣는다(쓰다 멈춰도 반쯤 쓴 파일이 남지 않는다).
    파일마다 따로 한다: `OSError`(Windows에서 편집기·백신·동기화가 파일을 잡고 있을 때)면 `ERASE_RETRY_DELAYS`
    간격으로 다시 해 보고, 그래도 안 되면 그날을 `failed`에 넣고 다음 날 파일로 간다. 이미 지운 날은 0(여러 번 해도 같다).
    """
    root = Path(transcripts_dir)
    total = 0
    failed: list[date] = []
    d = from_day
    while d <= to_day:
        path = _day_path(root, d)
        for attempt in range(len(ERASE_RETRY_DELAYS) + 1):
            if not path.exists():
                break
            try:
                total += _erase_day(path, str(conversation_id))
                break
            except OSError as e:
                if attempt == len(ERASE_RETRY_DELAYS):
                    log.warning("transcript_erase_error", extra={
                        "conversation_id": conversation_id, "day": d.isoformat(), "error_type": type(e).__name__,
                    })
                    failed.append(d)
                else:
                    _time.sleep(ERASE_RETRY_DELAYS[attempt])
        d += timedelta(days=1)
    return EraseResult(total, tuple(failed))


# 본문 줄이 `### `로 시작하면 머리글로 읽히지 않게 앞에 폭 없는 공백(U+200B)을 붙인다
_HEADER_ESCAPE = "\u200b"


def _escape_headers(text: str) -> str:
    return "\n".join(_HEADER_ESCAPE + line if line.startswith("### ") else line for line in text.split("\n"))


# `### 21:05 사용자 [44] (evening_checkin) #msg-abc @app`. 회차 표시, `#<id>`, ` @app`은 없을 수 있다.
# 메이트 대화는 ` @app @mate`(SP12 14장), 라이프 매니저 대화는 ` @app @manager`(SP15 13장)
_HEADER = re.compile(
    r"^### (?P<hhmm>\d{2}:\d{2}) (?P<speaker>사용자|비서|운동메이트|라이프 매니저|전문가) \[(?P<conv>\d+|-)\]"
    r"(?: \((?P<run>[^)]*)\))?(?: #(?P<id>[A-Za-z0-9_-]{1,64}))?(?P<app> @app)?(?P<mate> @mate)?(?P<manager> @manager)?$"
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


def _without_app_secretary(text: str) -> str:
    """머리글이 `비서`이고 ` @app`인 항목(머리글과 본문, 다음 머리글 전까지)을 뺀 원문. 나머지 줄은 그대로."""
    out: list[str] = []
    skip = False
    for line in text.splitlines(keepends=True):
        m = _HEADER.match(line.rstrip("\n"))
        if m:
            skip = m["speaker"] == "비서" and m["app"] is not None
        elif line.rstrip("\n") == ERASED_LINE:
            skip = False
        if not skip:
            out.append(line)
    return "".join(out)


def _without_mate(text: str) -> str:
    """머리글 끝이 ` @mate`·` @manager`인 항목(메이트·라이프 매니저 대화의 줄, 다음 머리글 전까지)을 뺀 원문."""
    out: list[str] = []
    skip = False
    for line in text.splitlines(keepends=True):
        m = _HEADER.match(line.rstrip("\n"))
        if m:
            skip = m["mate"] is not None or m["manager"] is not None
        elif line.rstrip("\n") == ERASED_LINE:
            skip = False
        if not skip:
            out.append(line)
    return "".join(out)


def _only_conversation(text: str, conversation: str) -> str:
    """머리글의 대화가 `conversation`인 항목(머리글과 본문, 다음 머리글이나 `[지운 대화]` 전까지)만 남긴 원문."""
    out: list[str] = []
    keep = False
    for line in text.splitlines(keepends=True):
        m = _HEADER.match(line.rstrip("\n"))
        if m:
            keep = m["conv"] == conversation
        elif line.rstrip("\n") == ERASED_LINE:
            keep = False
            continue
        if keep:
            out.append(line)
    return "".join(out)


def _parse(path: Path) -> list[_Entry]:
    out: list[_Entry] = []
    cur: _Entry | None = None
    for line in path.read_text(encoding="utf-8").splitlines():
        m = _HEADER.match(line)
        if m:
            cur = _Entry(m["hhmm"], m["speaker"], m["conv"], m["id"], m["app"] is not None, [], [])
            out.append(cur)
        elif line == ERASED_LINE:
            cur = None  # 지운 대화 자리: 앞 항목의 본문에 붙지 않는다(SP9 7.7)
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
