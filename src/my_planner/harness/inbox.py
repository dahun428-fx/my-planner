"""받은편지함 사건 줄 (SP14 스펙 6.2, 7장). 하루 끝 판단 입력과 즉시 판단 블록이 같은 줄 모양을 쓴다.

줄에는 종류·`ref`(id)·영역·날짜만 있다(제목·본문·값 없음, 스펙 1장 8). 넘김(`handoff`, `ref = note:<id>`)만 끝에 그
관찰 글을 붙인다(SP15: 두뇌가 쓴 120자 관찰이라 사용자 제목·본문이 아니다).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from my_planner.domain import InboxAgent
    from my_planner.store.repos.agents import AgentEvent, AgentsRepo

INBOX_BLOCK_MAX = 30  # 즉시 판단 블록의 줄 수 상한(최신부터)
INBOX_WINDOW_DAYS = 7  # 오늘 포함 이 날수 앞까지의 사건(`day >= today - 7일`)
INBOX_BLOCK_HEAD = "## 새로 생긴 것 (지난 대화 뒤)"


def event_line(e: AgentEvent, handoff_text: str | None = None) -> str:
    """`- {kind} {ref} · {area} · {day}`. 영역이 없으면 그 칸을 뺀다. 넘김 줄에 글이 있으면 끝에 ` · "{글}"`."""
    parts = [f"{e.kind} {e.ref}", *([e.area] if e.area else []), e.day.isoformat()]
    if e.kind == "handoff" and handoff_text:
        parts.append(f'"{handoff_text}"')
    return "- " + " · ".join(parts)


def handoff_texts(repo: AgentsRepo, events: Iterable[AgentEvent]) -> dict[str, str]:
    """사건 가운데 넘김(`note:<id>`)의 관찰 글, `ref` → 글. 지워진 관찰은 빠진다."""
    ids = {
        int(n): e.ref for e in events
        if e.kind == "handoff" and (n := e.ref.removeprefix("note:")) != e.ref and n.isdigit()
    }
    return {ids[i]: note.text for i, note in repo.notes_by_ids(ids).items()}


def event_lines(repo: AgentsRepo, events: list[AgentEvent]) -> list[str]:
    texts = handoff_texts(repo, events)
    return [event_line(e, texts.get(e.ref)) for e in events]


@dataclass(frozen=True)
class InboxBlock:
    text: str
    event_ids: tuple[int, ...]


def inbox_block(repo: AgentsRepo, agent: InboxAgent, today: date) -> InboxBlock | None:
    """안 읽은 사건의 최신 `INBOX_BLOCK_MAX`줄(글은 오래된 것부터). 없으면 None. 읽음 표시는 부르는 쪽이 한다."""
    events = repo.unseen(agent, today - timedelta(days=INBOX_WINDOW_DAYS), limit=INBOX_BLOCK_MAX)
    if not events:
        return None
    events.reverse()
    text = INBOX_BLOCK_HEAD + "\n" + "\n".join(event_lines(repo, events))
    return InboxBlock(text, tuple(e.id for e in events))
