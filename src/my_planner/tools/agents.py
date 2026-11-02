"""관찰 도구 `write_note`·`hand_off` (SP14 스펙 1장 3, 6.2~6.3). `Tools`가 이 mixin을 상속한다.

둘 다 하루 끝 판단(`RunContext.kind == "dayend"`)에만 있다(`mcp_adapter.tool_names_for`). 여기서 한 번 더 막는다.
관찰 글은 `agent_notes`에만 쓴다: 도구 이벤트·로그에는 id·상대·`priority`만 남긴다.
넘기기는 `priority` 3인 관찰과 받는 쪽 받은편지함의 `handoff` 사건(`ref = note:<id>`)을 한 트랜잭션에 쓴다.
"""

from __future__ import annotations

import logging
import re
from datetime import date
from typing import TYPE_CHECKING, Any

from my_planner.domain import INBOX_AGENTS, EventKind, InboxAgent, RunContext, ToolEvent
from my_planner.panel.evidence import ref_exists, ref_type
from my_planner.store.db import transaction
from my_planner.tools._base import _err, _tool
from my_planner.tools.moments import _bad_char
from my_planner.tools.ui import banned_words

if TYPE_CHECKING:
    from my_planner.clock import Clock
    from my_planner.store.repos.agents import AgentsRepo

log = logging.getLogger(__name__)

NOTE_TEXT_MAX = 120  # 코드포인트
NOTES_PER_JUDGMENT = 2
HANDOFFS_PER_DAY = 2
NOTE_REFS_MAX = 5
NOTE_EXTRA_BANNED = ("%", "못 했", "못했")  # ADR 0006: 비율과 하지 않은 것 탓하기
# 글 검사의 줄바꿈·제어·방향 문자는 순간 글과 같다(`moments._bad_char`)
_REF = re.compile(r"^[a-z_]+:[0-9A-Za-z_:-]+$")

MSG_NOT_HERE = "쓸 수 없는 도구예요."
MSG_TOO_MANY = f"관찰은 한 번에 {NOTES_PER_JUDGMENT}개까지예요."
MSG_TEXT = f"관찰은 {NOTE_TEXT_MAX}자 안의 한 줄이에요."
MSG_BANNED = "관찰에 쓰지 않는 말이 있어요: {word}"
MSG_PRIORITY = "priority는 1(꼭 알림) 또는 2예요."
MSG_REFS = f"refs는 근거 참조(예: workout:12) 1~{NOTE_REFS_MAX}개예요."
MSG_REF_MISSING = "refs에 없는 기록이 있어요: {ref}"
MSG_TO = "넘길 상대는 mate 또는 manager이고, 자기 자신에게는 넘기지 않아요."
MSG_HANDOFF_CAP = f"넘기기는 하루 {HANDOFFS_PER_DAY}번까지예요."


def _check_text(text: Any) -> str | tuple[str]:
    """(앞뒤 공백 뺀 글,) 또는 오류 문구. 오류 문구에는 글을 넣지 않는다(금지어 자체만)."""
    if not isinstance(text, str):
        return MSG_TEXT
    text = text.strip()
    if not 1 <= len(text) <= NOTE_TEXT_MAX or _bad_char(text):
        return MSG_TEXT
    for word in (*banned_words(), *NOTE_EXTRA_BANNED):
        if word in text:
            return MSG_BANNED.format(word=word)
    return (text,)


def _check_refs(refs: Any) -> list[str] | None:
    if (
        not isinstance(refs, list)
        or not 1 <= len(refs) <= NOTE_REFS_MAX
        or not all(isinstance(r, str) and _REF.match(r) for r in refs)
    ):
        return None
    return list(dict.fromkeys(refs))


def _missing_ref(repo: AgentsRepo, agent: InboxAgent, refs: list[str], today: date) -> str | None:
    """가리키는 기록이 없는 첫 참조(모르는 접두어 포함). 행이 사라졌어도 이 상대 받은편지함 사건에 있으면 받는다."""
    for ref in refs:
        known = ref_type(ref) is not None or ref.startswith("note:")
        if known and ref_exists(repo.conn, ref, today=today):
            continue
        if known and repo.ref_in_inbox(agent, ref):
            continue
        return ref
    return None


class AgentTools:
    """`write_note`·`hand_off`(두뇌, 하루 끝 판단만). `Tools`의 공통 부품(`_agent_event`)을 쓴다."""

    agents: AgentsRepo | None

    if TYPE_CHECKING:
        clock: Clock

        def _agent_event(self, ctx: RunContext, kind: EventKind, ref: str, area: str | None = None, *,
                         handoff_to: InboxAgent | None = None) -> None: ...

    def _judging(self, ctx: RunContext) -> tuple[AgentsRepo, InboxAgent, date] | None:
        if ctx.kind != "dayend" or self.agents is None or ctx.dayend_day is None or ctx.agent not in INBOX_AGENTS:
            return None
        return self.agents, ctx.agent, ctx.dayend_day  # type: ignore[return-value]

    @_tool
    def write_note(self, ctx: RunContext, text: Any = None, priority: Any = None, refs: Any = None) -> dict[str, Any]:
        """관찰 한 줄(하루 끝 판단에서 0~2개). 틀린 호출은 세지 않는다."""
        judging = self._judging(ctx)
        if judging is None:
            return _err(MSG_NOT_HERE)
        repo, agent, day = judging
        if ctx.notes_written >= NOTES_PER_JUDGMENT:
            return _err(MSG_TOO_MANY)
        checked = _check_text(text)
        if isinstance(checked, str):
            return _err(checked)
        if isinstance(priority, bool) or priority not in (1, 2):
            return _err(MSG_PRIORITY)
        good_refs = _check_refs(refs)
        if good_refs is None:
            return _err(MSG_REFS)
        missing = _missing_ref(repo, agent, good_refs, day)
        if missing is not None:
            return _err(MSG_REF_MISSING.format(ref=missing))
        with transaction(repo.conn):
            note_id = repo.add_note(agent, day, checked[0], priority, good_refs, self.clock.now())
        ctx.notes_written += 1
        ctx.events.append(ToolEvent("note_written", None, {"id": note_id}))
        log.info("note_written", extra={"agent": agent, "priority": priority})
        return {"ok": True, "id": note_id}

    @_tool
    def hand_off(self, ctx: RunContext, to: Any = None, text: Any = None, refs: Any = None) -> dict[str, Any]:
        """다른 아래층 상대에게 넘기기(`priority` 3 관찰 + 받는 쪽 `handoff` 사건). 하루 2번까지."""
        judging = self._judging(ctx)
        if judging is None:
            return _err(MSG_NOT_HERE)
        repo, agent, day = judging
        if to not in INBOX_AGENTS or to == agent:
            return _err(MSG_TO)
        checked = _check_text(text)
        if isinstance(checked, str):
            return _err(checked)
        good_refs = _check_refs(refs)
        if good_refs is None:
            return _err(MSG_REFS)
        missing = _missing_ref(repo, agent, good_refs, day)
        if missing is not None:
            return _err(MSG_REF_MISSING.format(ref=missing))
        if repo.handoffs_on(agent, day) >= HANDOFFS_PER_DAY:
            return _err(MSG_HANDOFF_CAP)
        with transaction(repo.conn):
            note_id = repo.add_note(agent, day, checked[0], 3, good_refs, self.clock.now())
            self._agent_event(ctx, "handoff", f"note:{note_id}", None, handoff_to=to)
        log.info("note_handed_off", extra={"agent": agent, "to": to})
        return {"ok": True, "id": note_id}
