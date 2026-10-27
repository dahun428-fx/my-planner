"""사진 읽기 (SP10 스펙 5.4): 사진 한 장의 글자를 옮겨 적는다.

- `PhotoReader`는 자리(seam)다. v1 구현은 `ClaudePhotoReader` 하나이고 설정 `photos.reader = "claude"`가 고른다
  (`build_reader`). SP11이 `LocalOcrPhotoReader`를 더한다.
- `ClaudePhotoReader`: 실행 종류 `photo_read`의 **도구 없는 한 번 호출**(`mcp_adapter.tool_names_for`가 빈 목록).
  SP9 요약(`summaries.summarize`)과 같은 틀이다: `persist_session=False`, `max_turns=1`, 세션 이어 가기 없음. 세션 파일
  지우기·`brain_calls`·`usage_state.photo_reads` 세기·두뇌 큐는 부르는 쪽(디스패처의 `_PhotoReadCaller`)이 한다.
- 입력은 사용자 메시지 하나: 이미지 블록(`base64`, `image/jpeg`) + 고정 지시(`prompts/photo_read.md`의 `## 지시`).
  지시문(system)은 같은 파일의 `## 역할`이다(스파이크 S2와 같은 두 덩이).
- 결과 검사: 출력의 모든 줄이 거절 틀(`photo_read.md` 끝의 `## 거절 틀`)이거나 `[읽을 수 없음]` 표시뿐이면(빈 출력 포함)
  `unreadable: true`, `text: ""`. 그 밖에는 앞뒤 공백을 뺀 출력을 8,000자에서 자른다.
- 로그에는 사진 id와 상태만 남긴다. 사진 바이트와 읽은 글은 남기지 않는다(6장).
"""

from __future__ import annotations

import base64
import logging
import re
from dataclasses import dataclass
from functools import cache
from typing import TYPE_CHECKING, Any, Protocol

from my_planner.domain import RunContext
from my_planner.harness import prompts
from my_planner.store.repos.photos import READ_TEXT_MAX

if TYPE_CHECKING:
    from my_planner.harness.brain import BrainResult

log = logging.getLogger(__name__)

# SDK 스트리밍 입력의 사용자 content 블록들(글·이미지). SDK의 출력용 `ContentBlock`과 다른 이름(5.4)
UserContent = list[dict[str, Any]]

PROMPT_FILE = "photo_read.md"
READ_MAX_CHARS = READ_TEXT_MAX  # 5.4: 넘으면 자른다(`photos.read_text` CHECK와 같은 값)
READ_MAX_TURNS = 1
UNREADABLE_MARK = "[읽을 수 없음]"
REFUSAL_MAX_CHARS = 200  # 이보다 긴 출력은 거절 틀에 대 보지 않는다(옮긴 글이다)


@dataclass(frozen=True)
class ReadResult:
    text: str
    unreadable: bool


class PhotoReader(Protocol):
    name: str  # "claude"

    async def read(self, photo_id: int, image: bytes) -> ReadResult: ...


class PhotoReadFailed(Exception):
    """두뇌가 답하지 못했다(사용 한도, 로그인, 시간 초과 등). 앱은 "다시 읽기" 띠를 보인다(7.1, 10장)."""

    def __init__(self, status: str) -> None:
        super().__init__(status)
        self.status = status


class PhotoReadLimit(Exception):
    """하루 사진 읽기 상한(`limits.daily_photo_reads`) 또는 하루 두뇌 호출 상한에 닿았다. 429 `photo_read_limit`(5.4)."""


class PhotoGone(Exception):
    """읽을 수 있는 사진이 아니다(없음, 뺌, 지운 메모·대화). 404."""


class PhotoReadBrain(Protocol):
    """두뇌 호출 자리(`summaries.SummaryBrain`과 같은 모양). 디스패처의 `_PhotoReadCaller`가 큐·셈·세션 지우기를 한다."""

    async def run(
        self, prompt: str | UserContent, *, session_id: str | None, run_ctx: RunContext,
        system_prompt: str | None = None, max_turns: int | None = None, persist_session: bool = True,
    ) -> BrainResult: ...


# --- 고정 지시 (`photo_read.md`) ---


@cache
def _sections() -> dict[str, str]:
    text = re.sub(r"<!--.*?-->", "", prompts.load(PROMPT_FILE), flags=re.DOTALL)
    parts: dict[str, str] = {}
    for chunk in re.split(r"^## ", text, flags=re.MULTILINE)[1:]:
        head, _, body = chunk.partition("\n")
        parts[head.strip()] = body.strip()
    return parts


def role() -> str:
    """지시문(system): `## 역할`."""
    return _sections()["역할"]


def instruction() -> str:
    """사진 뒤 글 블록: `## 지시`. 거절 틀은 싣지 않는다."""
    return _sections()["지시"]


@cache
def refusal_patterns() -> tuple[re.Pattern[str], ...]:
    """`## 거절 틀`의 `- \\`정규식\\`` 줄들."""
    found = re.findall(r"^- `(.+)`\s*$", _sections()["거절 틀"], flags=re.MULTILINE)
    return tuple(re.compile(p) for p in found)


def image_block(image: bytes) -> dict[str, Any]:
    """JPEG 바이트 하나의 이미지 블록(base64, 스파이크 S1 모양). 채팅 사진(5.5)도 같은 블록을 쓴다."""
    return {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                        "data": base64.b64encode(image).decode("ascii")}}


def photo_read_content(image: bytes) -> UserContent:
    """사용자 메시지 하나의 content: 이미지 블록 + 고정 지시(5.4, 스파이크 S1·S2 모양)."""
    return [image_block(image), {"type": "text", "text": instruction()}]


# --- 결과 검사 ---


def is_refusal(text: str) -> bool:
    """모든 줄이 거절 틀이거나 `[읽을 수 없음]` 표시뿐인가. 빈 출력도 그렇다.

    틀은 줄 머리에 묶은 1인칭 거절이고, 표시를 뺀 출력이 200자를 넘으면 거절로 보지 않는다. 한 줄이라도 옮긴 글자가
    있으면 아니다(간판의 "죄송합니다 오늘은 쉽니다", "Sorry, we are closed" 같은 줄은 읽은 것으로 본다).
    """
    patterns = refusal_patterns()
    if len(text.replace(UNREADABLE_MARK, "").strip()) > REFUSAL_MAX_CHARS:
        return False
    for line in text.splitlines():
        rest = line.replace(UNREADABLE_MARK, "").strip()
        if not rest:
            continue
        if not any(p.search(rest) for p in patterns):
            return False
    return True


def parse_read(text: str) -> ReadResult:
    out = text.strip()
    if is_refusal(out):
        return ReadResult(text="", unreadable=True)
    return ReadResult(text=out[:READ_MAX_CHARS], unreadable=False)


# --- 구현 ---


class ClaudePhotoReader:
    """구독 Claude(BE 두뇌)가 읽는다(D2). 도구 없음, 한 턴, 세션 파일을 남기지 않는다."""

    name = "claude"

    def __init__(self, brain: PhotoReadBrain) -> None:
        self._brain = brain

    async def read(self, photo_id: int, image: bytes) -> ReadResult:
        run_ctx = RunContext(
            None, None, kind="photo_read", actor="secretary", activity_channel="app", channel="app",
        )
        result = await self._brain.run(
            photo_read_content(image), session_id=None, run_ctx=run_ctx, system_prompt=role(),
            max_turns=READ_MAX_TURNS, persist_session=False,
        )
        if result.status != "ok":
            log.info("photo_read_failed", extra={"photo_id": photo_id, "status": result.status})
            raise PhotoReadFailed(result.status)
        return parse_read(result.text)


def build_reader(kind: str, brain: PhotoReadBrain) -> PhotoReader:
    """설정 `photos.reader`로 고른다. 지금은 `claude`뿐이다(SP11이 `local`, `local_then_claude`를 더한다)."""
    if kind == "claude":
        return ClaudePhotoReader(brain)
    raise ValueError(f"unknown photo reader: {kind}")
