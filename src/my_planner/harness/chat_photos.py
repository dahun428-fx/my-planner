"""채팅에 사진 (SP10 스펙 5.5): 받은 메시지 본문의 사진 표시와 두뇌 입력.

- 원문 기록·`inbound` 본문은 `[사진 #12] [사진 #13] {글}`만(사진 바이트·경로 없음, 6장). 사진은 보낸 순서이고,
  다시 보내기·시작 때 다시 넣기(`PhotosRepo.for_message`, 넣은 순서)가 같은 본문과 같은 입력을 만든다.
- 두뇌 입력: 사진마다 `{"type": "text", "text": "[사진 #12]"}` 바로 뒤 이미지 블록, 맨 끝에 글 블록(지시문·앞머리·
  `## 메시지` 전체). 메시지 글이 없으면 `(사진 {n}장)`이다. 그래서 두뇌가 `create_memo(photo_ids=[12])`를 부를 수 있다.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from my_planner.harness.photo_reader import UserContent, image_block

MESSAGE_PHOTOS_MAX = 4  # 메시지당(5.1). 5장 이상이면 422 `too_many_photos`

_MARKS = re.compile(r"^(?:\[사진 #(\d+)\](?: |$))+")


def photo_mark(photo_id: int) -> str:
    return f"[사진 #{photo_id}]"


def photo_body(photo_ids: Sequence[int], text: str) -> str:
    """`[사진 #12] [사진 #13] {글}`. 사진이 없으면 글 그대로, 글이 없으면 표시만."""
    marks = " ".join(photo_mark(i) for i in photo_ids)
    if not marks:
        return text
    return f"{marks} {text}" if text else marks


def message_text(body: str, photo_ids: Sequence[int], *, count: int | None = None) -> str:
    """본문에서 앞의 사진 표시를 뗀 메시지 글. 사진만 있었으면 `(사진 {n}장)`(5.5). `count`: 두뇌에 실제로 넣은
    사진 수(읽힌 사진만). 0이면 사진만 있던 메시지는 빈 글이다."""
    if not photo_ids:
        return body
    text = strip_marks(body, photo_ids)
    n = len(photo_ids) if count is None else count
    return text if text.strip() or n == 0 else f"(사진 {n}장)"


def strip_marks(body: str, photo_ids: Sequence[int]) -> str:
    """본문 앞의 `[사진 #id]` 표시(그 사진들 그대로일 때만)를 뗀 글. 사진만이면 `""`."""
    marks = photo_body(photo_ids, "")
    return body.removeprefix(marks).removeprefix(" ") if marks and body.startswith(marks) else body


def leading_photo_ids(text: str) -> list[int]:
    """원문 기록 사용자 줄 앞의 `[사진 #id]` 표시들(`GET /conversations/{id}/messages`의 `photos`, 5.3)."""
    m = _MARKS.match(text)
    return [int(i) for i in re.findall(r"\[사진 #(\d+)\]", m.group(0))] if m else []


def photo_content(prompt: str, images: Sequence[tuple[int, bytes]]) -> str | UserContent:
    """두뇌 입력. 붙일 이미지가 없으면 지금처럼 글 그대로(글만 오면 지금 경로, 5.5)."""
    if not images:
        return prompt
    content: UserContent = []
    for pid, data in images:
        content.append({"type": "text", "text": photo_mark(pid)})
        content.append(image_block(data))
    content.append({"type": "text", "text": prompt})
    return content
