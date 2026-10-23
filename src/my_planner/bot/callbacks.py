"""인라인 버튼 누름 (스펙 5.7). 두뇌를 거치지 않고 하네스가 도구 함수를 직접 부른다.

콜백 데이터: `d:c:<task_id>`(추가), `d:x:<task_id>`(빼기), `d:all:<conversation_id>`(전부 추가),
`c:<YYYY-MM-DD>:<1-5>`(그 날짜의 컨디션. 지난 날짜의 버튼도 그 날짜에 기록한다).
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Literal

from telegram import CallbackQuery

from my_planner.clock import Clock
from my_planner.domain import RunContext, TaskStatus
from my_planner.store.transcripts import TranscriptStore
from my_planner.tools.confirmations import draft_dropped_reply, render_confirmations
from my_planner.tools.core import Tools

log = logging.getLogger(__name__)

CallbackResult = Literal["confirmed", "dropped", "recorded", "stale", "ignored", "unknown"]

STALE_REPLY = "이미 정리된 할 일이에요."


def _parse(data: str | None) -> tuple[str, int] | None:
    """`d:c:12` → ("c", 12). 모르는 모양이면 None."""
    parts = (data or "").split(":")
    if len(parts) == 3 and parts[0] == "d" and parts[1] in ("c", "x", "all") and parts[2].isdigit():
        return parts[1], int(parts[2])
    return None


def _parse_condition(data: str | None) -> tuple[date, int] | None:
    """`c:2026-10-23:4` → (date(2026, 10, 23), 4). 모르는 모양이면 None."""
    parts = (data or "").split(":")
    if len(parts) != 3 or parts[0] != "c" or parts[2] not in ("1", "2", "3", "4", "5"):
        return None
    try:
        return date.fromisoformat(parts[1]), int(parts[2])
    except ValueError:
        return None


def condition_reply(score: int) -> str:
    return f"컨디션 {score} 기록했어요."


async def handle_callback(
    query: CallbackQuery,
    owner_id: int,
    tools: Tools,
    *,
    transcripts: TranscriptStore,
    clock: Clock,
) -> CallbackResult:
    """버튼 하나를 처리한다. 무엇을 하든 `query.answer()`를 꼭 한 번 부른다.

    1. 사용자가 아니면 무시한다. 2. 이미 초안이 아니면 바꾸지 않고 "이미 정리된 할 일이에요."라고 답한다.
    3. 바꾼 것은 원문 기록(`[-]`)에 `[버튼] 확정: {제목}`, `[버튼] 빼기: {제목}`으로 남긴다.
    """
    reply: str | None = None  # finally에서 꼭 한 번 보낸다
    try:
        if query.from_user is None or query.from_user.id != owner_id:
            # 사용자가 아니면 아무것도 바꾸지 않는다. 발신자 ID만 남긴다(본문, 이름 없이).
            log.info("callback_ignored", extra={"from_id": query.from_user.id if query.from_user else None})
            return "ignored"
        if (cond := _parse_condition(query.data)) is not None:
            d, score = cond
            out = tools.record_condition(RunContext(conversation_id=None, run_id=None), score=score, date=d.isoformat())
            if "error" in out:
                log.info("callback_condition_error")
                return "unknown"
            _transcript(transcripts, clock, f"[버튼] 컨디션 {score}")
            reply = condition_reply(score)
            return "recorded"
        parsed = _parse(query.data)
        if parsed is None:
            log.info("callback_unknown")
            return "unknown"
        action, n = parsed
        if action == "all":
            ids = [i for i in tools.tasks.proposed_task_ids(n) if _is_draft(tools, i)]
        else:
            ids = [n] if _is_draft(tools, n) else []
        if not ids:  # 이미 정리됐다: 상태를 바꾸지 않는다
            reply = STALE_REPLY
            return "stale"

        # 순서: 상태 커밋 → 원문 기록 → (finally) answer. answer가 안 돼도 기록은 남는다.
        ctx = RunContext(conversation_id=None, run_id=None)
        if action == "x":
            out = tools.drop_task(ctx, id=n)
            result: CallbackResult = "dropped"
            lines = [f"[버튼] 빼기: {out['title']}"] if "error" not in out else []
        else:
            out = tools.confirm_tasks(ctx, ids=ids)
            result = "confirmed"
            lines = [f"[버튼] 확정: {t['title']}" for t in out.get("confirmed", [])]
        if action == "x":
            reply = draft_dropped_reply(out["title"]) if "error" not in out else None
        else:
            reply = render_confirmations(ctx.events, tools.today()) or None
        log.info("callback_handled", extra={"action": action, "task_ids": ids})
        if lines:
            _transcript(transcripts, clock, "\n".join(lines))
        return result
    finally:
        await _answer(query, reply)


def _transcript(transcripts: TranscriptStore, clock: Clock, text: str) -> None:
    """버튼은 대화 밖이라 `[-]`로 남긴다. 기록이 안 돼도 상태는 이미 바뀌었으니 넘어간다."""
    try:
        transcripts.append(clock.now(), "사용자", None, None, text)
    except OSError as e:
        log.warning("callback_transcript_failed", extra={"error_type": type(e).__name__})


async def _answer(query: CallbackQuery, text: str | None) -> None:
    """콜백에 답한다. 늦게 받은 누름("Query is too old")이나 네트워크 오류는 종류만 남기고 넘어간다."""
    try:
        await query.answer(text)
    except Exception as e:  # noqa: BLE001 - 답은 로딩 표시를 끄는 것뿐이다. 상태와 기록은 이미 끝났다
        log.warning("callback_answer_failed", extra={"error_type": type(e).__name__})


def _is_draft(tools: Tools, task_id: int) -> bool:
    t = tools.tasks.get(task_id)
    return t is not None and t.status is TaskStatus.draft
