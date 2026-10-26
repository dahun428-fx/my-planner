"""대화 요약 (SP9 스펙 7.2, ADR 0014): 닫힌 앱 대화 하나에 제목(20자)과 요약(600자)을 붙인다.

- 두뇌 호출 한 번, **도구 없음**(`RunContext.kind = "summary"`), `max_turns = 1`, 세션 파일을 남기지 않는다.
- 입력은 그 대화의 원문 줄(`redact()` 거침, `input_max_chars`까지 뒤에서부터) + 이전 요약(있으면).
- 사용자 메시지가 1개 이하이고 비서 답이 200자 미만인 대화는 두뇌 없이 첫 사용자 메시지로 제목만 정한다(요약 `''`).
- 상한이나 두뇌 오류면 `None`. 부르는 쪽(디스패처)이 대체 제목을 적고 하루 한 번 작업이 다시 해 본다.
- 두뇌에 주는 요약(이어 가는 대화, resume 실패 대체, 말아 넣기, `find_conversations`)은 `redact()`를 거친다(7.5).

로그에는 대화 id와 결과만 남긴다(제목, 요약, 원문 없이).
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

from my_planner.domain import RunContext
from my_planner.harness import prompts
from my_planner.harness.redact import redact

if TYPE_CHECKING:
    from my_planner.harness.brain import BrainResult
    from my_planner.harness.photo_reader import UserContent
    from my_planner.store.repos.conversations import Conversation
    from my_planner.store.transcripts import TranscriptMessage

log = logging.getLogger(__name__)

TITLE_MAX = 20  # 7.2
SUMMARY_MAX = 600
LIST_SUMMARY_CHARS = 120  # `GET /conversations`의 요약 앞부분(7.6)
SHORT_REPLY_CHARS = 200  # 이보다 짧은 답 + 사용자 메시지 1개 이하면 두뇌를 부르지 않는다
SUMMARY_MAX_TURNS = 1
RETRY_DAYS = 7  # 하루 한 번 작업이 다시 해 보는 범위(최근 7일)
UNTITLED = "지난 대화"  # 사용자 줄이 하나도 없는 대화(회차 본문만 있는 경우)의 대체 제목

PAST_HEADING = "## 이 대화의 지난 내용"  # resume 실패 대체·말아 넣기(7.3, 7.4)
CONTINUED_HEADING = "## 이어 가는 지난 대화"  # 고른 계획·회차 대화에서 새로 연 `chat`(7.3)


@dataclass(frozen=True)
class Summary:
    title: str
    summary: str


class SummaryBrain(Protocol):
    async def run(
        self, prompt: str | UserContent, *, session_id: str | None, run_ctx: RunContext,
        system_prompt: str | None = None, max_turns: int | None = None, persist_session: bool = True,
    ) -> BrainResult: ...


def _one_line(text: str) -> str:
    return " ".join(text.split())


def fallback_title(lines: list[TranscriptMessage]) -> str:
    """첫 사용자 메시지의 앞 20자(줄바꿈은 공백 하나로, `redact()` 뒤). 사용자 줄이 없으면 "지난 대화"."""
    for m in lines:
        if m.speaker == "사용자":
            text = _one_line(redact(m.text)[0])
            if text:
                return text[:TITLE_MAX]
    return UNTITLED


def needs_brain(lines: list[TranscriptMessage]) -> bool:
    """짧은 대화(사용자 메시지 1개 이하, 비서 답 합쳐 200자 미만)는 두뇌 없이 제목만 정한다(7.2)."""
    users = sum(1 for m in lines if m.speaker == "사용자")
    replies = sum(len(m.text) for m in lines if m.speaker == "비서")
    return users > 1 or replies >= SHORT_REPLY_CHARS


def summary_input(lines: list[TranscriptMessage], prev_summary: str | None, max_chars: int) -> str:
    """두뇌 입력: 이전 요약(있으면) + 원문 줄. 줄은 뒤에서부터 `max_chars`까지 채운다(가린 뒤)."""
    picked: list[str] = []
    used = 0
    for m in reversed(lines):
        line = f"[{m.at:%m-%d %H:%M}] {m.speaker}: {redact(m.text)[0]}"
        if used + len(line) + 1 > max_chars:
            break
        picked.append(line)
        used += len(line) + 1
    parts = []
    if prev_summary:
        parts.append(f"## 이전 요약\n{redact(prev_summary)[0]}")
    parts.append("## 대화\n" + "\n".join(reversed(picked)))
    return "\n\n".join(parts)


_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$")


def parse_summary(text: str) -> Summary | None:
    """두뇌 답(JSON `{"title", "summary"}`)을 읽는다. 코드 블록 표시는 벗긴다. 제목은 20자, 요약은 600자로 자르고
    `redact()`를 거친다. 모양이 틀리거나 제목이 비면 None."""
    raw = _FENCE.sub("", text.strip())
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end < start:
        return None
    try:
        data: Any = json.loads(raw[start: end + 1])
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    title, summary = data.get("title"), data.get("summary")
    if not isinstance(title, str) or not isinstance(summary, str):
        return None
    title = _one_line(redact(title)[0])[:TITLE_MAX]
    summary = redact(summary.strip())[0][:SUMMARY_MAX]
    if not title:
        return None
    return Summary(title=title, summary=summary)


def summary_system_prompt() -> str:
    """`summarize.md` + 빈 줄 + `system.md`의 금지어 블록(하루 끝 순간 호출과 같은 방식)."""
    from my_planner.harness.moments import banned_words_block

    return f"{prompts.load('summarize.md')}\n\n{banned_words_block()}"


async def summarize(
    conv: Conversation, lines: list[TranscriptMessage], prev_summary: str | None, brain: SummaryBrain,
    *, max_chars: int = 8000,
) -> Summary | None:
    """대화 하나의 제목과 요약(7.2). 짧은 대화는 두뇌 없이 `fallback_title`(요약 `''`). 두뇌 오류면 None."""
    if not needs_brain(lines):
        return Summary(title=fallback_title(lines), summary="")
    run_ctx = RunContext(
        conv.id, None, kind="summary", actor="secretary", activity_channel="scheduler", channel="app",
    )
    try:
        result = await brain.run(
            summary_input(lines, prev_summary, max_chars), session_id=None, run_ctx=run_ctx,
            system_prompt=summary_system_prompt(), max_turns=SUMMARY_MAX_TURNS, persist_session=False,
        )
    except Exception as e:  # noqa: BLE001 - 요약이 안 돼도 대화는 그대로다. 종류만 남긴다
        log.warning("summary_error", extra={"conversation_id": conv.id, "error_type": type(e).__name__})
        return None
    if result.status != "ok":
        log.info("summary_failed", extra={"conversation_id": conv.id, "status": result.status})
        return None
    got = parse_summary(result.text)
    if got is None:
        log.info("summary_failed", extra={"conversation_id": conv.id, "status": "unparsed"})
    return got


def summary_block(heading: str, conv: Conversation) -> str:
    """두뇌에 주는 요약 한 덩이(`redact()` 거침). 요약이 비었으면 제목만, 둘 다 없으면 빈 글."""
    title = redact(conv.title)[0] if conv.title else ""
    body = redact(conv.summary)[0] if conv.summary else ""
    if not title and not body:
        return ""
    lines = [heading]
    if title:
        lines.append(f"제목: {title}")
    if body:
        lines.append(body)
    return "\n".join(lines)
