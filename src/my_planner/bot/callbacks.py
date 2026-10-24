"""인라인 버튼 누름 (스펙 5.7). 두뇌를 거치지 않는다.

`apply`(디스패처의 즉시 갈래 `Dispatcher.apply_action`, SP3-4 스펙 4.3)가 있으면 그것으로 바꾼다
(`actor = user`, `channel = telegram`: 활동 기록이 함께 남는다). 없으면 SP1처럼 도구 함수를 직접 부른다.
답 문구는 어느 쪽이든 SP1 그대로다.

콜백 데이터: `d:c:<task_id>`(추가), `d:x:<task_id>`(빼기), `d:all:<conversation_id>`(전부 추가),
`c:<YYYY-MM-DD>:<1-5>`(그 날짜의 컨디션. 지난 날짜의 버튼도 그 날짜에 기록한다),
`k:a:<token>`(회차 차례의 확인: 토큰의 `action`·`args`를 그대로 적용), `k:x:<token>`(그대로 두기, SP3-4 10.1 A5·A6),
`m:c:<id>`·`m:x:<id>`·`m:all:<conversation_id>`(사건 초안 저장·빼기·전부 저장), `h:c:<id>`·`h:x:<id>`(챕터 초안,
SP3-4 10장·11.3), `l:<YYYY-MM>:n:<0-10>`·`l:<YYYY-MM>:f:<0-10>`·`l:<YYYY-MM>:f:skip`(회고 단계의 사다리 지금·5년 뒤·
건너뛰기, SP3-4 11.1. 버튼에 든 달에 기록한다), `hb:<habit_id>:<YYYY-MM-DD>`(그 날짜의 습관 체크 토글, SP7 5.7.
누른 메시지의 `hb:` 버튼 글자를 지금 DB 상태로 다시 그린다. 챕터 `h:`와는 `parts[0]`이 달라 겹치지 않는다).

회고 단계(`review`, `harness.review_steps.ReviewFlow`): 월말 회고 묶음 메시지의 컨디션 누름은 토스트 대신 새 메시지로
답하고 사다리 1단계를 붙인다(회차마다 한 번, 계획 빈 곳 12). 사다리 누름은 그 달 월말 회고의 답장 창 안이면 다음
단계를 새 메시지로 보내고, 창 뒤면 기록만 한다(토스트). 단계 메시지는 하루 3회 상한에 세지 않는다.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from dataclasses import replace
from datetime import date
from typing import TYPE_CHECKING, Any, Literal

from telegram import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import BadRequest

from my_planner.clock import Clock
from my_planner.domain import RunContext, TaskStatus
from my_planner.status.xp import XpGain
from my_planner.store.transcripts import TranscriptStore
from my_planner.tools.actions import (
    CHAPTER_GONE,
    MILESTONE_GONE,
    STALE_TOKEN,
    ActionRequest,
    ActionResult,
)
from my_planner.tools.confirmations import (
    condition_summary,
    draft_dropped_reply,
    level_line,
    render_confirmations,
)
from my_planner.tools.core import Tools

if TYPE_CHECKING:
    from my_planner.harness.conversations import ConversationRouter
    from my_planner.harness.review_steps import NextStep, ReviewFlow
    from my_planner.store.repos.activity import ConfirmsRepo
    from my_planner.store.repos.channels import DeliveriesRepo
    from my_planner.store.repos.runs import RunsRepo

log = logging.getLogger(__name__)

CallbackResult = Literal[
    "confirmed", "dropped", "declined", "recorded", "skipped", "stale", "ignored", "unknown"
]
Apply = Callable[[ActionRequest], ActionResult]
MarkAnswered = Callable[..., object]  # `Dispatcher.mark_answered(run_id, channel, *, gain=None)`

STALE_REPLY = "이미 정리된 할 일이에요."
_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
# 토큰은 `ct_` + `secrets.token_urlsafe(16)`(22자): 콜백 데이터 29바이트(64바이트 이하)
_CONFIRM = re.compile(r"k:(?P<op>[ax]):(?P<token>ct_[A-Za-z0-9_-]{22})")
_LADDER = re.compile(r"l:(?P<period>\d{4}-(?:0[1-9]|1[0-2])):(?P<field>[nf]):(?P<value>10|[0-9]|skip)")


def _parse(data: str | None) -> tuple[str, int] | None:
    """`d:c:12` → ("c", 12). 모르는 모양이면 None."""
    parts = (data or "").split(":")
    if len(parts) == 3 and parts[0] == "d" and parts[1] in ("c", "x", "all") and parts[2].isdigit():
        return parts[1], int(parts[2])
    return None


def _parse_curve(data: str | None) -> tuple[str, str, int] | None:
    """`m:c:7` → ("m", "c", 7), `h:x:3` → ("h", "x", 3), `m:all:41` → ("m", "all", 41). 모르는 모양이면 None."""
    parts = (data or "").split(":")
    if len(parts) != 3 or not parts[2].isdigit():
        return None
    if (parts[0] == "m" and parts[1] in ("c", "x", "all")) or (parts[0] == "h" and parts[1] in ("c", "x")):
        return parts[0], parts[1], int(parts[2])
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


def _parse_habit(data: str | None) -> tuple[int, date] | None:
    """`hb:12:2026-10-24` → (12, date(2026, 10, 24)). 모르는 모양이면 None. `h:c:3`(챕터)은 습관이 아니다."""
    parts = (data or "").split(":")
    if len(parts) != 3 or parts[0] != "hb" or not (parts[1].isascii() and parts[1].isdecimal()):
        return None
    if not _ISO_DATE.fullmatch(parts[2]):  # fromisoformat은 20261024, 2026-W43-6도 받는다
        return None
    try:
        return int(parts[1]), date.fromisoformat(parts[2])
    except ValueError:
        return None


def _parse_confirm(data: str | None) -> tuple[str, str] | None:
    """`k:a:ct_…` → ("a", "ct_…"). 모르는 모양이면 None."""
    m = _CONFIRM.fullmatch(data or "")
    return (m["op"], m["token"]) if m is not None else None


def _parse_ladder(data: str | None) -> tuple[str, Literal["n", "f"], int | None] | None:
    """`l:2026-11:n:6` → ("2026-11", "n", 6), `l:2026-11:f:skip` → ("2026-11", "f", None). 모르는 모양이면 None."""
    m = _LADDER.fullmatch(data or "")
    if m is None or (m["field"] == "n" and m["value"] == "skip"):
        return None
    field: Literal["n", "f"] = "n" if m["field"] == "n" else "f"
    return m["period"], field, None if m["value"] == "skip" else int(m["value"])


def condition_reply(score: int) -> str:
    return condition_summary(score)  # 활동 한 줄과 같은 문구(SP1)


async def handle_callback(
    query: CallbackQuery,
    owner_id: int,
    tools: Tools,
    *,
    transcripts: TranscriptStore,
    clock: Clock,
    router: ConversationRouter | None = None,
    apply: Apply | None = None,
    deliveries: DeliveriesRepo | None = None,
    mark_answered: MarkAnswered | None = None,
    confirms: ConfirmsRepo | None = None,
    review: ReviewFlow | None = None,
    runs: RunsRepo | None = None,
) -> CallbackResult:
    """버튼 하나를 처리한다. 무엇을 하든 `query.answer()`를 꼭 한 번 부른다.

    1. 사용자가 아니면 무시한다. 2. 이미 초안이 아니면 바꾸지 않고 "이미 정리된 할 일이에요."라고 답한다.
    3. 바꾼 것은 원문 기록(`[-]`)에 `[버튼] 확정: {제목}`, `[버튼] 빼기: {제목}`으로 남긴다.
    4. 계획 대화에서 제안한 초안의 버튼이면 그 계획 대화의 활동으로 기록한다(2시간 만료, 스펙 5.7).
    5. 회차 메시지에 붙은 버튼으로 바꿨으면 그 회차의 답이다(SP3-4 6.4.5, 처음 한 번 `mark_answered`).
    6. 확인 버튼(`k:`)은 즉시 갈래로만 처리한다. 쓰였거나 만료됐거나 대상이 그 뒤 바뀐 토큰은 적용하지 않고
       "이미 정리된 제안이에요."(10.1 A6).
    """
    reply: str | None = None  # finally에서 꼭 한 번 보낸다
    # 이 누름이 스스로 적은 경험치만 센다(즉시 갈래 응답의 `xp.level_up`, 회차 답 기록). 그 사이 다른 갈래가 적은
    # 경험치로 레벨이 올라도 이 답에는 붙이지 않는다(9.2)
    gain = XpGain()
    apply = _noting(apply, gain)
    mark_answered = _marking(mark_answered, gain)
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
            _answer_run(query, deliveries, mark_answered)
            step = _review_step(query, deliveries, review)
            # 회고 묶음의 컨디션 누름: 토스트 대신 새 메시지로 답하고 첫 단계를 붙인다(11.1-1, 빈 곳 12)
            if (
                step is not None and review is not None
                and await review.send(replace(step, text=f"{reply}\n\n{step.text}"))
            ):
                reply = None
            return "recorded"
        if (hb := _parse_habit(query.data)) is not None:
            result_h, reply = await _habit(query, *hb, tools, apply, transcripts, clock, deliveries, mark_answered, runs)
            return result_h
        if (lad := _parse_ladder(query.data)) is not None:
            result_l, reply = await _ladder(*lad, tools, apply, review, transcripts, clock)
            return result_l
        if (conf := _parse_confirm(query.data)) is not None:
            result_k, reply = _confirm(conf[0], conf[1], apply, confirms, transcripts, clock)
            if result_k in ("confirmed", "declined"):
                _answer_run(query, deliveries, mark_answered)
            return result_k
        if (cv := _parse_curve(query.data)) is not None:
            result_c, reply, lines = _curve(tools, apply, router, *cv)
            if result_c in ("confirmed", "dropped"):
                _answer_run(query, deliveries, mark_answered)
            if lines:
                _transcript(transcripts, clock, "\n".join(lines))
            return result_c
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
        if "error" not in out:
            _answer_run(query, deliveries, mark_answered)
        if lines:
            _transcript(transcripts, clock, "\n".join(lines))
        return result
    finally:
        if reply is not None:
            # 레벨이 오르면 답 끝에 한 줄(SP3-4 9.2). 즉시 갈래의 확인 문구가 이미 붙였으면 다시 붙이지 않는다
            line = level_line(gain.level_up)
            if line and line not in reply:
                reply = f"{reply}\n{line}"
        await _answer(query, reply)


def _curve(
    tools: Tools, apply: Apply | None, router: ConversationRouter | None, what: str, op: str, n: int
) -> tuple[CallbackResult, str | None, list[str]]:
    """사건(`m`)·챕터(`h`) 초안 버튼(10장): 즉시 갈래로 `confirm_milestones`·`drop_milestone`·`confirm_chapters`·
    `drop_chapter`. 이미 정리된(확정, 빼기, 만료로 지운) 초안이면 바꾸지 않고 "이미 정리된 사건이에요."(챕터는
    "이미 정리된 챕터예요."). (결과, 답 문구, 원문 기록 줄). 원문 기록은 `[버튼] 저장: {제목}`, `[버튼] 빼기: {제목}`."""
    curve = tools.curve
    gone = MILESTONE_GONE if what == "m" else CHAPTER_GONE
    if curve is None:
        log.info("callback_unknown")
        return "unknown", None, []
    if what == "m":
        if op == "all":
            ids = curve.draft_milestone_ids(n)
            conversation_id: int | None = n
        else:
            m = curve.get_milestone(n)
            ids = [n] if m is not None and m.status == "draft" else []
            conversation_id = m.conversation_id if m is not None else None
        if router is not None:
            router.touch_plan(conversation_id)
        titles = {i: m.title for i in ids if (m := curve.get_milestone(i)) is not None}
    else:
        c = curve.get_chapter(n)
        ids = [n] if c is not None and c.status == "draft" else []
        titles = {n: c.title} if c is not None else {}
    if not ids:
        log.info("callback_curve_stale", extra={"kind": what})
        return "stale", gone, []
    if op == "x":
        action, args = ("drop_milestone" if what == "m" else "drop_chapter"), {"id": n}
    else:
        action, args = ("confirm_milestones" if what == "m" else "confirm_chapters"), {"ids": ids}
    out, confirmation = _run(tools, apply, action, args)
    log.info("callback_curve", extra={"kind": what, "op": op, "count": len(ids)})
    if "error" in out:
        return "stale", out["error"] or gone, []
    if op == "x":
        return "dropped", confirmation, [f"[버튼] 빼기: {titles[n]}"]
    done = [c["id"] for c in out.get("confirmed", [])]
    if not done:
        return "stale", gone, []
    return "confirmed", confirmation, [f"[버튼] 저장: {titles[i]}" for i in done if i in titles]


async def _habit(
    query: CallbackQuery, habit_id: int, day: date, tools: Tools, apply: Apply | None, transcripts: TranscriptStore,
    clock: Clock, deliveries: DeliveriesRepo | None, mark_answered: MarkAnswered | None, runs: RunsRepo | None,
) -> tuple[CallbackResult, str | None]:
    """습관 버튼(SP7 5.7): 누르기 전 DB 상태로 `uncheck_habit`(체크돼 있으면) 또는 `check_habit`을 즉시 갈래로.
    (결과, 알림 문구 = 확인 문구 한 줄). 쉬는·그만둔·지운 습관, 7일 밖의 날은 바꾸지 않고 도구의 거절 문구.

    회차 메시지의 버튼이면 그 회차의 답이다(`_answer_run`, X3). 그다음 누른 메시지의 `hb:` 버튼 글자를 DB 상태로
    다시 그린다. 회차 메시지이고 그 회차를 앱에서 먼저 답해 버튼을 거뒀으면(`answered_via = app`) 다시 그리지
    않는다. 로그에는 습관 id와 결과만 남긴다(제목 없이, 8장).
    """
    habits = tools.habits
    if habits is None:
        log.info("callback_unknown")
        return "unknown", None
    uncheck = habit_id in habits.checked_on(day)
    action = "uncheck_habit" if uncheck else "check_habit"
    out, confirmation = _run(tools, apply, action, {"id": habit_id, "date": day.isoformat()})
    log.info("callback_habit", extra={"habit_id": habit_id, "op": action, "ok": "error" not in out})
    if "error" in out:
        return "stale", out["error"] or None
    _transcript(transcripts, clock, f"[버튼] 습관 체크 {'취소 ' if uncheck else ''}{out['habit']['title']}")
    _answer_run(query, deliveries, mark_answered)
    await _redraw_habits(query, habits.checked_on(day), deliveries, runs)
    return "recorded", confirmation


def redraw_habit_buttons(markup: InlineKeyboardMarkup, checked: set[int]) -> InlineKeyboardMarkup:
    """`markup`을 복사하고 그 안의 모든 `hb:` 버튼 글자(`☐`/`✓`)를 `checked`로 다시 정한다. 다른 버튼은 그대로."""
    from my_planner.bot.telegram_io import HABIT_OFF, HABIT_ON

    def redraw(b: InlineKeyboardButton) -> InlineKeyboardButton:
        parsed = _parse_habit(b.callback_data if isinstance(b.callback_data, str) else None)
        if parsed is None:
            return b
        _, rest = b.text.split(" ", 1) if " " in b.text else ("", b.text)
        mark = HABIT_ON if parsed[0] in checked else HABIT_OFF
        return InlineKeyboardButton(f"{mark} {rest}", callback_data=b.callback_data)

    return InlineKeyboardMarkup([[redraw(b) for b in row] for row in markup.inline_keyboard])


async def _redraw_habits(
    query: CallbackQuery, checked: set[int], deliveries: DeliveriesRepo | None, runs: RunsRepo | None
) -> None:
    """누른 메시지의 버튼만 다시 그린다(`editMessageReplyMarkup`). 본문은 그대로다."""
    msg = query.message
    markup = getattr(msg, "reply_markup", None)
    if msg is None or not isinstance(markup, InlineKeyboardMarkup):
        return
    try:
        run_id = deliveries.run_for_message(msg.message_id) if deliveries is not None else None
        run = runs.get(run_id) if runs is not None and run_id is not None else None
        primary = (runs.merged_into(run.id) or run) if runs is not None and run is not None else None
        if primary is not None and primary.answered_via == "app":
            log.info("habit_redraw_skipped", extra={"run_id": primary.id})
            return  # 앱에서 먼저 답해 거둔 버튼(SP3-4 6.4.5)
        await query.edit_message_reply_markup(reply_markup=redraw_habit_buttons(markup, checked))
    except BadRequest as e:
        if "not modified" not in str(e).lower():  # 같은 모양이면 텔레그램이 거절한다: 잡고 넘어간다
            log.warning("habit_redraw_failed", extra={"error_type": type(e).__name__})
    except Exception as e:  # noqa: BLE001 - 체크는 이미 커밋됐다. 버튼 글자만 못 바꿨다
        log.warning("habit_redraw_failed", extra={"error_type": type(e).__name__})


def _review_step(
    query: CallbackQuery, deliveries: DeliveriesRepo | None, review: ReviewFlow | None
) -> NextStep | None:
    """누른 컨디션 버튼이 월말 회고 묶음 메시지에 붙어 있고 아직 첫 단계를 묻지 않았으면 그 단계(표시는 `send`가 한다)."""
    msg = query.message
    if review is None or deliveries is None or msg is None:
        return None
    try:
        run_id = deliveries.run_for_message(msg.message_id)
        return review.after_condition(run_id) if run_id is not None else None
    except Exception as e:  # noqa: BLE001 - 컨디션은 이미 기록됐다. 단계만 못 붙였다(토스트로 답한다)
        log.warning("review_step_error", extra={"error_type": type(e).__name__})
        return None


async def _ladder(
    period: str, field: Literal["n", "f"], value: int | None, tools: Tools, apply: Apply | None,
    review: ReviewFlow | None, transcripts: TranscriptStore, clock: Clock,
) -> tuple[CallbackResult, str | None]:
    """사다리 버튼(11.1-2, 3): 즉시 갈래로 `record_ladder_score(period=버튼의 달)`. (결과, 토스트 문구).

    그 달 월말 회고가 답장 창 안이면 다음 단계(2단계, 또는 "기록했어요: …"와 분기 영역 점수 묻기)를 새 메시지로
    보낸다(토스트 없음). 창 뒤면 기록만 하고 "기록했어요: …"를 토스트로. 점수는 로그에 남기지 않는다.
    """
    from my_planner.harness.review_steps import ladder_recorded

    if value is None:  # 5년 뒤 건너뛰기: 쓰지 않는다
        line, result = "[버튼] 사다리 5년 뒤 건너뛰기", "skipped"
        saved: dict[str, Any] = {}
    else:
        args = {"period": period, "now": value} if field == "n" else {"period": period, "future": value}
        saved, _ = _run(tools, apply, "record_ladder_score", args)
        if "error" in saved:
            log.info("callback_ladder_error", extra={"field": field})
            return "stale", saved["error"] or None
        line, result = f"[버튼] 사다리 {'지금' if field == 'n' else '5년 뒤'} {value}", "recorded"
    _transcript(transcripts, clock, line)
    log.info("callback_ladder", extra={"field": field, "skipped": value is None})
    if review is None:
        return result, ladder_recorded(saved.get("now"), saved.get("future"))  # type: ignore[return-value]
    try:
        step = review.after_now(period) if field == "n" else review.after_future(period)
    except Exception as e:  # noqa: BLE001 - 기록은 이미 됐다. 다음 단계만 못 보낸다
        log.warning("review_step_error", extra={"error_type": type(e).__name__})
        step = None
    if step is not None and await review.send(step):
        return result, None  # type: ignore[return-value]
    return result, review.recorded_copy(period)  # type: ignore[return-value]


def _confirm(
    op: str, token: str, apply: Apply | None, confirms: ConfirmsRepo | None, transcripts: TranscriptStore,
    clock: Clock,
) -> tuple[CallbackResult, str | None]:
    """확인 버튼 하나(10.1 A6): `k:a`는 토큰의 `action`·`args`로 `apply_action(confirm_token=…)`, `k:x`는
    `decline_confirm`. (결과, 답 문구). 토큰과 인자는 로그에 남기지 않는다."""
    if apply is None or confirms is None:
        log.info("callback_unknown")
        return "unknown", None
    p = confirms.get(token)
    if p is None:
        log.info("callback_confirm_stale")
        return "stale", STALE_TOKEN
    if op == "a":
        res = apply(ActionRequest(p.action, p.args, actor="user", channel="telegram", confirm_token=token))
        line, result = f"[버튼] 확인: {p.summary}", "confirmed"
    else:
        res = apply(ActionRequest("decline_confirm", {"confirm_token": token}, actor="user", channel="telegram"))
        line, result = f"[버튼] 그대로 두기: {p.summary}", "declined"
    log.info("callback_confirm", extra={"op": op, "action": p.action, "status": res.status})
    if res.status == "applied":
        _transcript(transcripts, clock, line)
        return result, res.body.get("confirmation")  # type: ignore[return-value]
    if res.status == "rejected":  # 도구가 거절했다(토큰은 열린 채다): 도구의 오류 문구
        return "stale", res.body.get("error", {}).get("message") or STALE_TOKEN
    return "stale", STALE_TOKEN


def _noting(apply: Apply | None, gain: XpGain) -> Apply | None:
    """즉시 갈래 응답의 `xp.level_up`(그 요청의 트랜잭션이 넘긴 레벨)을 `gain`에 모은다."""
    if apply is None:
        return None
    inner = apply

    def noted(req: ActionRequest) -> ActionResult:
        res = inner(req)
        xp = res.body.get("xp") if isinstance(res.body, dict) else None
        if isinstance(xp, dict):
            gain.note(xp.get("level_up"))
        return res

    return noted


def _marking(mark: MarkAnswered | None, gain: XpGain) -> MarkAnswered | None:
    """회차 답 기록이 적은 경험치(X3/X5/X8)를 `gain`에 모은다."""
    if mark is None:
        return None
    inner = mark
    return lambda run_id, channel: inner(run_id, channel, gain=gain)


def _answer_run(query: CallbackQuery, deliveries: DeliveriesRepo | None, mark: MarkAnswered | None) -> None:
    """누른 버튼이 붙은 메시지가 회차 메시지면(`run_deliveries.telegram_message_id`) 그 회차의 답으로 적는다."""
    msg = query.message
    if deliveries is None or mark is None or msg is None:
        return
    try:
        run_id = deliveries.run_for_message(msg.message_id)
        if run_id is not None:
            mark(run_id, "telegram")
    except Exception as e:  # noqa: BLE001 - 바꾼 것은 이미 커밋됐다. 답 표시만 못 했다
        log.warning("callback_answer_record_error", extra={"error_type": type(e).__name__})


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
