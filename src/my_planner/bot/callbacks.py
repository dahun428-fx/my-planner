"""인라인 버튼 누름 (스펙 5.7). 두뇌를 거치지 않는다.

`apply`(디스패처의 즉시 갈래 `Dispatcher.apply_action`, SP3-4 스펙 4.3)가 있으면 그것으로 바꾼다
(`actor = user`, `channel = telegram`: 활동 기록이 함께 남는다). 없으면 SP1처럼 도구 함수를 직접 부른다.
답 문구는 어느 쪽이든 SP1 그대로다.

콜백 데이터: `d:c:<task_id>`(추가), `d:x:<task_id>`(빼기), `d:all:<conversation_id>`(전부 추가),
`c:<YYYY-MM-DD>:<1-5>`(그 날짜의 컨디션. 지난 날짜의 버튼도 그 날짜에 기록한다).
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from datetime import date
from typing import TYPE_CHECKING, Any, Literal

from telegram import CallbackQuery

from my_planner.clock import Clock
from my_planner.domain import RunContext, TaskStatus
from my_planner.store.transcripts import TranscriptStore
from my_planner.tools.actions import ActionRequest, ActionResult
from my_planner.tools.confirmations import draft_dropped_reply, render_confirmations
from my_planner.tools.core import Tools

if TYPE_CHECKING:
    from my_planner.harness.conversations import ConversationRouter

log = logging.getLogger(__name__)

CallbackResult = Literal["confirmed", "dropped", "recorded", "stale", "ignored", "unknown"]
Apply = Callable[[ActionRequest], ActionResult]

STALE_REPLY = "이미 정리된 할 일이에요."
_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


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
    if not _ISO_DATE.fullmatch(parts[1]):  # fromisoformat은 20261023, 2026-W43-5도 받는다
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
    router: ConversationRouter | None = None,
    apply: Apply | None = None,
) -> CallbackResult:
    """버튼 하나를 처리한다. 무엇을 하든 `query.answer()`를 꼭 한 번 부른다.

    1. 사용자가 아니면 무시한다. 2. 이미 초안이 아니면 바꾸지 않고 "이미 정리된 할 일이에요."라고 답한다.
    3. 바꾼 것은 원문 기록(`[-]`)에 `[버튼] 확정: {제목}`, `[버튼] 빼기: {제목}`으로 남긴다.
    4. 계획 대화에서 제안한 초안의 버튼이면 그 계획 대화의 활동으로 기록한다(2시간 만료, 스펙 5.7).
    """
    reply: str | None = None  # finally에서 꼭 한 번 보낸다
    try:
        if query.from_user is None or query.from_user.id != owner_id:
            # 사용자가 아니면 아무것도 바꾸지 않는다. 발신자 ID만 남긴다(본문, 이름 없이).
            log.info("callback_ignored", extra={"from_id": query.from_user.id if query.from_user else None})
            return "ignored"
        if (cond := _parse_condition(query.data)) is not None:
            d, score = cond
            out, _ = _run(tools, apply, "record_condition", {"score": score, "date": d.isoformat()})
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
        if router is not None:
            router.touch_plan(n if action == "all" else tools.tasks.proposed_conversation_id(n))
        if action == "all":
            ids = [i for i in tools.tasks.proposed_task_ids(n) if _is_draft(tools, i)]
        else:
            ids = [n] if _is_draft(tools, n) else []
        if not ids:  # 이미 정리됐다: 상태를 바꾸지 않는다
            reply = STALE_REPLY
            return "stale"

        # 순서: 상태 커밋 → 원문 기록 → (finally) answer. answer가 안 돼도 기록은 남는다.
        if action == "x":
            out, _ = _run(tools, apply, "drop_task", {"id": n})
            result: CallbackResult = "dropped"
            lines = [f"[버튼] 빼기: {out['title']}"] if "error" not in out else []
            reply = draft_dropped_reply(out["title"]) if "error" not in out else None
        else:
            out, confirmation = _run(tools, apply, "confirm_tasks", {"ids": ids})
            result = "confirmed"
            lines = [f"[버튼] 확정: {t['title']}" for t in out.get("confirmed", [])]
            reply = confirmation
        log.info("callback_handled", extra={"action": action, "task_ids": ids})
        if lines:
            _transcript(transcripts, clock, "\n".join(lines))
        return result
    finally:
        await _answer(query, reply)


def _run(tools: Tools, apply: Apply | None, action: str, args: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
    """동작 하나를 하고 (도구 결과, 확인 문구)를 돌려준다. 거절이면 결과에 `error`가 있다."""
    if apply is not None:
        res = apply(ActionRequest(action, args, actor="user", channel="telegram"))
        if res.status != "applied":
            return {"error": res.body.get("error", {}).get("message", "")}, None
        return res.body["result"], res.body.get("confirmation")
    ctx = RunContext(conversation_id=None, run_id=None)
    out = getattr(tools, action)(ctx, **args)
    return out, render_confirmations(ctx.events, tools.today()) or None


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
