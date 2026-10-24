"""시험용 AI SDK UI message stream 파서 (SP3-4 스펙 6.4.1, 16장 "기준 응답").

`parse_sse(body)`는 조각 목록을 돌려주고, 규칙에 어긋나면 `StreamFormatError`를 올린다:
- 사건은 빈 줄로 나뉜다. `:`로 시작하는 줄은 주석(`: ping`)이라 건너뛴다. 사건마다 `data: ` 줄 하나.
- 첫 조각은 `start`, 마지막 조각은 `finish`, 그 뒤 `data: [DONE]`으로 끝난다.
- `text-start`/`text-delta`/`text-end`는 같은 `id`로 짝을 이룬다(열기 전 조각, 두 번 열기, 닫지 않음은 오류).
- `tool-output-available`/`tool-output-error`는 앞서 나온 같은 `toolCallId`의 `tool-input-available`에만,
  입력마다 출력은 하나다. 끝날 때 출력이 없는 입력도 오류다.
- 조각 종류는 AI SDK UI message stream의 것(`data-*` 포함)만.
- `start-step`/`finish-step`은 짝이 맞아야 한다.

`normalize_sse(body)`는 `messageId` 값만 `<id>`로 바꾼다(기준 응답과 바이트 단위로 비교할 때).
"""

from __future__ import annotations

import json
import re
from typing import Any

KNOWN_TYPES = frozenset({
    "start", "finish", "abort", "error", "message-metadata",
    "start-step", "finish-step",
    "text-start", "text-delta", "text-end",
    "reasoning-start", "reasoning-delta", "reasoning-end",
    "tool-input-start", "tool-input-delta", "tool-input-available", "tool-input-error",
    "tool-output-available", "tool-output-error",
    "source-url", "source-document", "file",
})
_MESSAGE_ID = re.compile(rb'"messageId":"[^"]*"')


class StreamFormatError(AssertionError):
    pass


def _events(body: bytes) -> list[str]:
    text = body.decode("utf-8")
    if not text.endswith("\n\n"):
        raise StreamFormatError("스트림이 빈 줄로 끝나지 않는다")
    out: list[str] = []
    for block in text[:-2].split("\n\n"):
        lines = [ln for ln in block.split("\n") if not ln.startswith(":")]
        if not lines:
            continue  # 주석만 있는 사건(`: ping`)
        if len(lines) != 1 or not lines[0].startswith("data: "):
            raise StreamFormatError(f"data 줄 하나가 아닌 사건: {block!r}")
        out.append(lines[0][len("data: "):])
    return out


def parse_sse(body: bytes) -> list[dict[str, Any]]:
    events = _events(body)
    if not events or events[-1] != "[DONE]":
        raise StreamFormatError("data: [DONE]으로 끝나지 않는다")
    if "[DONE]" in events[:-1]:
        raise StreamFormatError("[DONE]이 끝이 아닌 곳에 있다")
    chunks: list[dict[str, Any]] = []
    for raw in events[:-1]:
        c = json.loads(raw)
        if not isinstance(c, dict) or not isinstance(c.get("type"), str):
            raise StreamFormatError(f"조각 모양이 아니다: {raw!r}")
        t = c["type"]
        if t not in KNOWN_TYPES and not t.startswith("data-"):
            raise StreamFormatError(f"규격 밖 조각 종류: {t}")
        chunks.append(c)
    if not chunks or chunks[0]["type"] != "start":
        raise StreamFormatError("첫 조각이 start가 아니다")
    if chunks[-1]["type"] != "finish":
        raise StreamFormatError("마지막 조각이 finish가 아니다")
    if any(c["type"] in ("start", "finish") for c in chunks[1:-1]):
        raise StreamFormatError("start/finish가 가운데에 있다")
    open_text: set[str] = set()
    seen_text: set[str] = set()
    inputs: dict[str, int] = {}  # toolCallId → 출력 수
    step_open = False
    for c in chunks:
        t = c["type"]
        if t == "start-step":
            if step_open:
                raise StreamFormatError("start-step이 겹친다")
            step_open = True
        elif t == "finish-step":
            if not step_open:
                raise StreamFormatError("열지 않은 단계의 finish-step")
            step_open = False
        elif t == "text-start":
            if c["id"] in seen_text:
                raise StreamFormatError(f"같은 글 id를 다시 연다: {c['id']}")
            open_text.add(c["id"])
            seen_text.add(c["id"])
        elif t in ("text-delta", "text-end"):
            if c.get("id") not in open_text:
                raise StreamFormatError(f"열지 않은 글 id: {c.get('id')}")
            if t == "text-delta" and not isinstance(c.get("delta"), str):
                raise StreamFormatError("text-delta에 delta가 없다")
            if t == "text-end":
                open_text.discard(c["id"])
        elif t == "tool-input-available":
            cid = c.get("toolCallId")
            if not isinstance(cid, str) or cid in inputs:
                raise StreamFormatError(f"도구 호출 id가 없거나 겹친다: {cid}")
            if not isinstance(c.get("toolName"), str) or "input" not in c:
                raise StreamFormatError("tool-input-available에 toolName/input이 없다")
            inputs[cid] = 0
        elif t in ("tool-output-available", "tool-output-error"):
            cid = c.get("toolCallId")
            if cid not in inputs:
                raise StreamFormatError(f"입력 없는 도구 출력: {cid}")
            inputs[cid] += 1
            if inputs[cid] > 1:
                raise StreamFormatError(f"도구 출력이 둘: {cid}")
    if open_text:
        raise StreamFormatError(f"닫지 않은 글: {sorted(open_text)}")
    if step_open:
        raise StreamFormatError("닫지 않은 단계")
    missing = [cid for cid, n in inputs.items() if n == 0]
    if missing:
        raise StreamFormatError(f"출력이 없는 도구 호출: {missing}")
    return chunks


def normalize_sse(body: bytes) -> bytes:
    return _MESSAGE_ID.sub(b'"messageId":"<id>"', body)


def types(chunks: list[dict[str, Any]]) -> list[str]:
    return [c["type"] for c in chunks]
