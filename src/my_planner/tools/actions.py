"""즉시 갈래: 두뇌 없이 도구 함수 하나를 부른다 (SP3-4 스펙 4.3, 6.4.2).

`apply_action(deps, req)`는 동기 함수이고 안에서 `await`하지 않는다. 그래서 두뇌 갈래의 도구 실행 사이에 끼어들
수는 있어도 트랜잭션 도중에 끼어들지는 않는다. 적용 결과(데이터, `tool_events_log`, `activity`), 확인 토큰의
상태, `api_idempotency`는 `transaction(conn)` 하나에 쓴다.

순서(6.4.2):
1. 이름 확인: 모르는 동작, 밖(`app`·`telegram`)에서 부른 내부 동작은 `400 invalid_request`.
2. `client_msg_id`가 있으면 저장한 처음 응답을 그대로 돌려준다(`api_idempotency`).
3. `args` 모양 확인: 객체가 아니거나 도구가 받지 않는 항목이면 `400 invalid_request`(저장하지 않는다).
4. 한 트랜잭션 안에서:
   - `decline_confirm`: 열린 토큰을 `declined`로 닫는다(아무것도 바꾸지 않는다).
   - `confirm_token`이 있으면: 없거나 쓰였거나 만료된 토큰, 요청과 맞지 않는 토큰은 `409 conflict`. 대상에 토큰 뒤
     활동이 있으면 `stale`로 닫고 `409`. 맞으면 `risk = confirm`으로 적용하고 `applied`로 닫는다.
   - 앱 요청이고 확인이 필요하면(`needs_confirm`) 토큰(10분)만 만들고 `needs_confirm`.
   - 그 밖에는 도구를 부른다. 도구가 거절하면 `422 rejected`(도구의 오류 문구).
   - 응답을 `api_idempotency`에 쓴다(`client_msg_id`가 있을 때).

푸시와 알림 설정(6.4.8, 6.4.9)은 `api/push.py`만 부르는 내부 동작이다(`endpoint="push"`, 되돌릴 수 없음):
`push_subscribe`, `push_unsubscribe`, `notify_set`, `push_test_result`. 구독 `endpoint`(주소)와 키는 활동
`summary`, 결과, 로그에 넣지 않는다(14장). `api_idempotency`에는 쓰지 않는다(이 경로들은 `client_msg_id`가 없다).

되돌리기 `undo`(6.4.3)는 `POST /activity/{id}/undo`만 부르는 내부 동작이다(`endpoint="undo"`). 없는 활동은 `404`,
이미 되돌린 활동은 아무것도 바꾸지 않고 `200 already_undone`(U4: 같은 `client_msg_id`로 다시 와도 같은 답),
U1~U3에 걸리면 `422 not_undoable`·`409 undo_expired`·`409 superseded`. 되돌리면 대상 복원, 새 활동(`kind="undo"`,
`undo_json = NULL`), 원래 행의 `undone_at`·`undone_by`를 한 트랜잭션에 쓴다(U5). 경험치 원장은 건드리지 않는다(U6).

로그에는 동작 이름과 결과만 남긴다(제목, 인자, 토큰 없이).
"""

from __future__ import annotations

import inspect
import logging
import sqlite3
from collections.abc import Callable
from dataclasses import KW_ONLY, dataclass, field
from datetime import date, timedelta
from typing import TYPE_CHECKING, Any, Literal

from my_planner.clock import Clock, period_of
from my_planner.domain import (
    ActivityChannel,
    Actor,
    Cadence,
    Channel,
    RunContext,
    TaskStatus,
)
from my_planner.store.db import transaction
from my_planner.timefmt import (  # API 경계의 시각 변환(6.1). 도구 결과는 현지 시각이다
    api_time,
    to_api_times,
)
from my_planner.tools.activity import (
    SUPERSEDED,
    UNDO_HANDLERS,
    UNDO_KIND,
    live_targets,
    priorities_target,
    record_activity,
    task_target,
    undo_block,
    watched_targets,
)
from my_planner.tools.confirmations import (
    confirm_declined_summary,
    period_label,
    render_confirmations,
    undo_summary,
)

if TYPE_CHECKING:
    from my_planner.config import Settings
    from my_planner.harness.conversations import ConversationRouter
    from my_planner.store.repos.activity import (
        ActivityRepo,
        ConfirmsRepo,
        IdempotencyRepo,
    )
    from my_planner.store.repos.push import PushRepo
    from my_planner.store.repos.runs import RunsRepo
    from my_planner.store.repos.state import StateRepo
    from my_planner.tools.core import Tools

log = logging.getLogger(__name__)

CONFIRM_TTL = timedelta(minutes=10)  # `/actions`가 만든 확인 토큰(6.4.2)
IDEMPOTENCY_KEEP = timedelta(days=2)  # `api_idempotency` 보관(5.2)
CONFIRMS_KEEP = timedelta(days=7)  # `pending_confirms` 보관(5.2)
NO_XP: dict[str, Any] = {"gained": 0, "level_up": None}  # 경험치는 티켓 15가 채운다

STALE_TOKEN = "이미 정리된 제안이에요."  # 10.1 A6
TOKEN_MISMATCH = "확인한 제안과 요청이 달라요."
UNKNOWN_ACTION = "알 수 없는 동작이에요."
BAD_ARGS = "args 형식이 맞지 않아요."
REUSED_ID = "이미 다른 요청에 쓴 client_msg_id예요."
NO_ACTIVITY = "없는 활동이에요."
UNDO_ERRORS: dict[str, tuple[int, str]] = {  # 6.1 오류 코드 → (HTTP, 문구)
    "not_undoable": (422, "되돌릴 수 없는 변경이에요."),
    "undo_expired": (409, "되돌릴 수 있는 24시간이 지났어요."),
    "superseded": (409, "그 뒤에 바뀐 내용이 있어서 되돌릴 수 없어요."),
}

RequestEndpoint = Literal["chat", "actions", "undo", "push"]  # `push`: `api/push.py`(중복 방지 기록 없음)

ActionStatus = Literal[
    "applied", "needs_confirm", "rejected", "invalid", "conflict",
    "undone", "already_undone", "not_found", "not_undoable", "undo_expired", "superseded",
]


@dataclass
class ActionRequest:
    action: str
    args: Any
    _: KW_ONLY
    actor: Actor
    channel: ActivityChannel
    client_msg_id: str | None = None
    confirm_token: str | None = None
    endpoint: RequestEndpoint = "actions"


@dataclass
class ActionResult:
    status: ActionStatus
    http_status: int
    body: dict[str, Any]


@dataclass
class ActionDeps:
    tools: Tools
    clock: Clock
    activity: ActivityRepo | None = None
    idempotency: IdempotencyRepo | None = None
    confirms: ConfirmsRepo | None = None
    state: StateRepo | None = None  # 명령 동작(`cmd_pause`, `cmd_unpause`)
    router: ConversationRouter | None = None  # 명령 동작 `cmd_done`
    # 답한 회차(6.4.5): 적용한 동작이 회차의 버튼과 같은 일이면 `mark_answered(run_id, channel)`(디스패처)
    runs: RunsRepo | None = None
    settings: Settings | None = None
    mark_answered: Callable[[int, Channel], object] | None = None
    pushes: PushRepo | None = None  # 푸시 구독(`push_*` 동작)

    @property
    def conn(self) -> sqlite3.Connection:
        return self.tools.tasks.conn


Handler = Callable[[ActionDeps, RunContext, dict[str, Any]], dict[str, Any]]
NeedsConfirm = Callable[["Tools", dict[str, Any], date], str | None]


@dataclass(frozen=True)
class ActionSpec:
    """`tool`: `Tools` 메서드 이름 또는 처리 함수. `needs_confirm`: 확인이 필요하면 확인 문구 한 줄.

    `target`: 확인 토큰의 `stale` 판정에 쓰는 활동 대상(5.2). `public=False`는 하루 한 번 작업 같은 내부 동작이다.
    `endpoint`가 있으면 그 경로(`ActionRequest.endpoint`)에서만 부른다(`undo`).
    """

    tool: str | Handler
    needs_confirm: NeedsConfirm | None = None
    public: bool = True
    target: Callable[[Tools, dict[str, Any]], list[str]] | None = None
    accepts: frozenset[str] = field(default_factory=frozenset)  # 처리 함수가 받는 `args` 항목(메서드는 서명으로 본다)
    endpoint: RequestEndpoint | None = None
    reply: bool = False  # 명령 동작: 결과가 답 글(`reply_text`)이고 응답은 `/chat` 재생 모양(6.4.1)


# --- 확인이 필요한가 (6.4.2 위험 칸) ---


def _int(v: Any) -> int | None:
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def drop_needs_confirm(tools: Tools, args: dict[str, Any], today: date) -> str | None:
    """지금 기간 우선순위이거나 열린 첫 걸음이 있는 할 일을 내려놓을 때."""
    i = _int(args.get("id"))
    t = tools.tasks.get(i) if i is not None else None
    if t is None or t.status not in (TaskStatus.open, TaskStatus.draft):
        return None  # 도구가 거절한다
    if tools.tasks.current_priority(t.id, today) is not None:
        return f"우선순위 할 일을 내려놓아요: {t.title}"
    if tools.tasks.first_steps(t.id)[0] > 0:
        return f"첫 걸음이 남은 할 일을 내려놓아요: {t.title}"
    return None


def priorities_need_confirm(tools: Tools, args: dict[str, Any], today: date) -> str | None:
    """`quarter`·`year`이면서 이미 비어 있지 않은 목록을 다른 목록으로 바꿀 때."""
    cadence, period, ids = args.get("cadence"), args.get("period"), args.get("task_ids")
    if cadence not in (Cadence.quarter.value, Cadence.year.value) or not isinstance(period, str):
        return None
    current = [t.id for _, t in tools.tasks.priority_ranks(cadence, period)]
    if not current or current == ids:
        return None
    label = period_label(cadence, period, period_of(Cadence(cadence), today))
    return f"{label} 우선순위 {len(current)}개를 바꿔요"


def _task_target(tools: Tools, args: dict[str, Any]) -> list[str]:
    i = _int(args.get("id"))
    return [task_target(i)] if i is not None else []


def _priorities_target(tools: Tools, args: dict[str, Any]) -> list[str]:
    """그 기간 목록과, 지금 목록·새 목록의 할 일 전부. 그 가운데 하나라도 토큰 뒤에 바뀌면 확인 문구가 맞지 않는다.

    토큰 뒤에 목록에서 빠진 할 일(내려놓기)은 그 활동이 목록 대상(`priorities:…`)도 적으므로 함께 잡힌다.
    """
    c, p, ids = args.get("cadence"), args.get("period"), args.get("task_ids")
    if not isinstance(c, str) or not isinstance(p, str) or c not in {x.value for x in Cadence}:
        return []
    current = [t.id for _, t in tools.tasks.priority_ranks(c, p)]
    new = [i for i in ids if _int(i) is not None] if isinstance(ids, list) else []
    return [priorities_target(c, p), *(task_target(i) for i in dict.fromkeys([*current, *new]))]


# --- 내부 처리 함수 ---


def _decline_confirm(deps: ActionDeps, ctx: RunContext, args: dict[str, Any]) -> dict[str, Any]:
    """처리는 `apply_action`이 한다(토큰 확인이 응답 모양을 정한다). 여기 오지 않는다."""
    raise AssertionError("decline_confirm은 apply_action이 처리한다")


def _undo_stub(deps: ActionDeps, ctx: RunContext, args: dict[str, Any]) -> dict[str, Any]:
    """처리는 `_undo`가 한다(응답 모양이 다르다). 여기 오지 않는다."""
    raise AssertionError("undo는 apply_action이 처리한다")


def _expire_drafts(deps: ActionDeps, ctx: RunContext, args: dict[str, Any]) -> dict[str, Any]:
    return deps.tools.expire_drafts(ctx, args["older_than"])


def _prune_api_state(deps: ActionDeps, ctx: RunContext, args: dict[str, Any]) -> dict[str, Any]:
    """하루 한 번 작업: 만료된 토큰 닫기, 7일 지난 토큰과 2일 지난 `api_idempotency` 지우기. 활동은 없다."""
    now = deps.clock.now()
    out = {"tokens_expired": 0, "tokens_pruned": 0, "idempotency_pruned": 0}
    if deps.confirms is not None:
        out["tokens_expired"] = deps.confirms.expire(now)
        out["tokens_pruned"] = deps.confirms.prune(now - CONFIRMS_KEEP)
    if deps.idempotency is not None:
        out["idempotency_pruned"] = deps.idempotency.prune(now - IDEMPOTENCY_KEEP)
    return out


def _cmd_pause(deps: ActionDeps, ctx: RunContext, args: dict[str, Any]) -> dict[str, Any]:
    from my_planner.bot.commands import cmd_pause

    assert deps.state is not None
    return {"reply_text": cmd_pause(deps.state, deps.clock.now(), str(args.get("text", "")), deps.tools.tz)}


def _cmd_unpause(deps: ActionDeps, ctx: RunContext, args: dict[str, Any]) -> dict[str, Any]:
    from my_planner.bot.commands import cmd_unpause

    assert deps.state is not None
    return {"reply_text": cmd_unpause(deps.state, deps.clock.now())}


def _cmd_done(deps: ActionDeps, ctx: RunContext, args: dict[str, Any]) -> dict[str, Any]:
    from my_planner.bot.commands import cmd_done

    assert deps.router is not None
    return {"reply_text": cmd_done(deps.router, ctx.channel)}


PUSH_SUBSCRIBED = "푸시 알림을 켰어요"
PUSH_UNSUBSCRIBED = "푸시 알림을 껐어요"
NO_SUBSCRIPTION = "없는 구독이에요."
BAD_PRIMARY = "주 통로는 telegram 또는 app이에요."
CHANNEL_LABELS = {"telegram": "텔레그램", "app": "앱"}
PUSH_RESULTS = ("ok", "gone", "failed")


def _push_summary(base: str, label: Any) -> str:
    """활동 한 줄. 기기 이름(사용자가 붙인 것)만 붙인다. 구독 주소와 키는 넣지 않는다."""
    return f"{base}: {label.strip()}" if isinstance(label, str) and label.strip() else base


def _push_subscribe(deps: ActionDeps, ctx: RunContext, args: dict[str, Any]) -> dict[str, Any]:
    endpoint, p256dh, auth = args.get("endpoint"), args.get("p256dh"), args.get("auth")
    label = args.get("label")
    if not all(isinstance(v, str) and v for v in (endpoint, p256dh, auth)) or not (
        label is None or isinstance(label, str)
    ):
        return {"error": BAD_ARGS}
    assert deps.pushes is not None
    sid = deps.pushes.upsert(endpoint, p256dh, auth, label or None, at=deps.clock.now())
    record_activity(
        deps.activity, ctx, kind="push_subscribed", target=f"push:{sid}", summary=_push_summary(PUSH_SUBSCRIBED, label),
        risk="low", undo=None,
    )
    return {"id": sid}


def _push_unsubscribe(deps: ActionDeps, ctx: RunContext, args: dict[str, Any]) -> dict[str, Any]:
    sid = _int(args.get("id"))
    assert deps.pushes is not None
    sub = deps.pushes.get(sid) if sid is not None else None
    if sub is None or not deps.pushes.delete(sub.id):
        return {"error": NO_SUBSCRIPTION}
    record_activity(
        deps.activity, ctx, kind="push_unsubscribed", target=f"push:{sub.id}",
        summary=_push_summary(PUSH_UNSUBSCRIBED, sub.label), risk="low", undo=None,
    )
    return {"id": sub.id}


def _notify_set(deps: ActionDeps, ctx: RunContext, args: dict[str, Any]) -> dict[str, Any]:
    from my_planner.store.repos.state import NOTIFY_PRIMARY_KEY

    primary = args.get("primary")
    if primary not in CHANNEL_LABELS:
        return {"error": BAD_PRIMARY}
    assert deps.state is not None
    deps.state.set(NOTIFY_PRIMARY_KEY, primary)
    record_activity(
        deps.activity, ctx, kind="notify_changed", target="notify", summary=f"주 통로: {CHANNEL_LABELS[primary]}",
        risk="low", undo=None,
    )
    return {"primary": primary}


def _push_test_result(deps: ActionDeps, ctx: RunContext, args: dict[str, Any]) -> dict[str, Any]:
    """`POST /push/test`의 결과 기록(구독마다 받음·못 받음). 활동은 남기지 않는다(바뀐 데이터가 없다)."""
    results = args.get("results")
    if not isinstance(results, list) or not all(
        isinstance(r, dict) and _int(r.get("id")) is not None and r.get("result") in PUSH_RESULTS for r in results
    ):
        return {"error": BAD_ARGS}
    assert deps.pushes is not None
    now = deps.clock.now()
    disabled = 0
    for r in results:
        if r["result"] == "ok":
            deps.pushes.record_ok(r["id"], now)
        elif deps.pushes.record_failure(r["id"], gone=r["result"] == "gone", at=now):
            disabled += 1
    ok = sum(1 for r in results if r["result"] == "ok")
    return {"ok": ok, "failed": len(results) - ok, "disabled": disabled}


ACTIONS: dict[str, ActionSpec] = {
    "add_task": ActionSpec("add_task"),
    "update_task": ActionSpec("update_task", target=_task_target),
    "move_task": ActionSpec("move_task", target=_task_target),
    "complete_task": ActionSpec("complete_task", target=_task_target),
    "reopen_task": ActionSpec("reopen_task", target=_task_target),
    "drop_task": ActionSpec("drop_task", needs_confirm=drop_needs_confirm, target=_task_target),
    "confirm_tasks": ActionSpec("confirm_tasks"),
    "set_priorities": ActionSpec("set_priorities", needs_confirm=priorities_need_confirm, target=_priorities_target),
    "record_condition": ActionSpec("record_condition"),
    "decline_confirm": ActionSpec(_decline_confirm, accepts=frozenset({"confirm_token"})),
    # 내부(하루 한 번 작업, `secretary`/`scheduler`)
    "expire_drafts": ActionSpec(_expire_drafts, public=False, accepts=frozenset({"older_than"})),
    "prune_api_state": ActionSpec(_prune_api_state, public=False),
    # 내부(`POST /activity/{id}/undo`)
    "undo": ActionSpec(_undo_stub, public=False, accepts=frozenset({"activity_id"}), endpoint="undo"),
    # 내부(상태를 바꾸는 명령 `/pause`, `/unpause`, `/done`: `bot.commands.run_command`, 6.4.1). 중복 방지는
    # `endpoint='chat'`의 `api_idempotency`(`response_json.reply_text`에 명령의 답)
    "cmd_pause": ActionSpec(_cmd_pause, public=False, accepts=frozenset({"text"}), endpoint="chat", reply=True),
    "cmd_unpause": ActionSpec(_cmd_unpause, public=False, endpoint="chat", reply=True),
    "cmd_done": ActionSpec(_cmd_done, public=False, endpoint="chat", reply=True),
    # 내부(`api/push.py`: 6.4.8, 6.4.9). 되돌릴 수 없다
    "push_subscribe": ActionSpec(
        _push_subscribe, public=False, accepts=frozenset({"endpoint", "p256dh", "auth", "label"}), endpoint="push"
    ),
    "push_unsubscribe": ActionSpec(_push_unsubscribe, public=False, accepts=frozenset({"id"}), endpoint="push"),
    "notify_set": ActionSpec(_notify_set, public=False, accepts=frozenset({"primary"}), endpoint="push"),
    "push_test_result": ActionSpec(_push_test_result, public=False, accepts=frozenset({"results"}), endpoint="push"),
}


# --- 응답 모양 ---


def _error(status: ActionStatus, http: int, code: str, message: str) -> ActionResult:
    return ActionResult(status, http, {"error": {"code": code, "message": message}})


def _rejected(message: str) -> ActionResult:
    return ActionResult(
        "rejected", 422, {"status": "rejected", "activity_id": None, "error": {"code": "rejected", "message": message}}
    )


def _applied(deps: ActionDeps, ctx: RunContext, result: dict[str, Any]) -> ActionResult:
    aid = ctx.activity_ids[0] if ctx.activity_ids else None
    confirmation = render_confirmations(ctx.events, deps.tools.today()) or None
    if confirmation is None and aid is not None and deps.activity is not None:
        a = deps.activity.get(aid)  # 확인 문구가 없는 종류(컨디션 등)는 활동 한 줄
        confirmation = a.summary if a is not None else None
    body: dict[str, Any] = {"status": "applied", "activity_id": aid}
    if aid is not None and aid in ctx.undo_ids:
        body["undo_id"] = aid  # 되돌릴 수 있을 때만, 값은 activity_id와 같다
    body.update({"result": to_api_times(result), "confirmation": confirmation, "xp": dict(NO_XP)})
    return ActionResult("applied", 200, body)


# --- 즉시 갈래 ---


def _accepts(deps: ActionDeps, spec: ActionSpec, args: dict[str, Any]) -> bool:
    if isinstance(spec.tool, str):
        method = getattr(deps.tools, spec.tool)
        try:
            inspect.signature(method).bind(None, **args)  # 첫 자리는 ctx
        except TypeError:
            return False
        return True
    return set(args) <= spec.accepts


def _context(req: ActionRequest) -> RunContext:
    return RunContext(
        conversation_id=None,
        run_id=None,
        actor=req.actor,
        channel="app" if req.channel == "app" else "telegram",
        activity_channel=req.channel,
    )


def _call(deps: ActionDeps, spec: ActionSpec, ctx: RunContext, args: dict[str, Any]) -> ActionResult:
    if isinstance(spec.tool, str):
        out = getattr(deps.tools, spec.tool)(ctx, **args)
    else:
        out = spec.tool(deps, ctx, args)
    if "error" in out:
        return _rejected(str(out["error"]))
    if spec.reply:
        return ActionResult("applied", 200, {
            "status": "applied", "conversation_id": None, "reply_text": out["reply_text"], "confirmation": None,
            "inbound_id": None,
        })
    return _applied(deps, ctx, out)


def _decline(deps: ActionDeps, req: ActionRequest, args: dict[str, Any]) -> ActionResult:
    token = args.get("confirm_token")
    p = deps.confirms.get(token) if deps.confirms is not None and isinstance(token, str) else None
    now = deps.clock.now()
    if p is None or not p.open_at(now):
        if p is not None and p.resolved_at is None:
            deps.confirms.resolve(p.token, "expired")  # type: ignore[union-attr]
        return _error("conflict", 409, "conflict", STALE_TOKEN)
    assert deps.confirms is not None
    deps.confirms.resolve(p.token, "declined")
    ctx = _context(req)
    record_activity(
        deps.activity, ctx, kind="confirm_declined", target=None, summary=confirm_declined_summary(p.summary),
        risk="low", undo=None,
    )
    return _applied(deps, ctx, {})


def _with_token(deps: ActionDeps, spec: ActionSpec, req: ActionRequest, args: dict[str, Any]) -> ActionResult:
    p = deps.confirms.get(req.confirm_token) if deps.confirms is not None and req.confirm_token else None
    now = deps.clock.now()
    if p is None or p.resolved_at is not None:
        return _error("conflict", 409, "conflict", STALE_TOKEN)
    assert deps.confirms is not None
    if not p.open_at(now):
        deps.confirms.resolve(p.token, "expired")
        return _error("conflict", 409, "conflict", STALE_TOKEN)
    if p.action != req.action or p.args != args:
        return _error("conflict", 409, "conflict", TOKEN_MISMATCH)
    targets = spec.target(deps.tools, args) if spec.target is not None else []
    if deps.activity is not None and any(deps.activity.changed_after(t, p.created_at) for t in targets):
        deps.confirms.resolve(p.token, "stale")  # 확인 사이에 대상이 바뀌었다: 적용하지 않는다(5.2)
        return _error("conflict", 409, "conflict", STALE_TOKEN)
    ctx = _context(req)
    ctx.risk = "confirm"
    res = _call(deps, spec, ctx, args)
    if res.status == "applied":
        deps.confirms.resolve(p.token, "applied")
    return res


class _Superseded(Exception):
    """되돌리기 처리 함수가 `"superseded"`를 돌려줬다: 그 안의 쓰기를 되돌린다(안쪽 SAVEPOINT)."""


def _already_undone(undo_activity_id: int | None) -> ActionResult:
    return ActionResult("already_undone", 200, {"status": "already_undone", "activity_id": undo_activity_id})


def _undo(deps: ActionDeps, req: ActionRequest, args: dict[str, Any]) -> ActionResult:
    """되돌리기 한 번(6.4.3). 바깥 트랜잭션 안에서 부른다."""
    aid = _int(args.get("activity_id"))
    a = deps.activity.get(aid) if deps.activity is not None and aid is not None else None
    if a is None:
        return _error("not_found", 404, "not_found", NO_ACTIVITY)
    assert deps.activity is not None
    if a.undone_at is not None:
        return _already_undone(a.undone_by)  # U4
    block = undo_block(a, deps.activity, deps.clock.now())
    if block is not None:
        http, message = UNDO_ERRORS[block]
        return _error(block, http, block, message)
    assert a.undo is not None
    ctx = _context(req)
    payload = {**a.undo, "targets": live_targets(a, deps.activity)[1]}  # 처리 함수가 되돌린 대상만 남긴다
    try:
        with transaction(deps.conn):
            if UNDO_HANDLERS[a.kind](deps.tools, payload, ctx) == SUPERSEDED:
                raise _Superseded
    except _Superseded:
        http, message = UNDO_ERRORS[SUPERSEDED]
        return _error("superseded", http, "superseded", message)
    summary = undo_summary(payload.get("summary", a.summary))  # 일부만 되돌렸으면 처리 함수가 좁힌 문구
    new_id = record_activity(
        deps.activity, ctx, kind=UNDO_KIND, target=a.target, summary=summary, risk="low", undo=None,
        # 되돌리기도 그 대상을 바꾼 활동이다(U3): 실제로 되돌린 대상과, 원래 행의 지켜보는 대상(확인 토큰 stale용)
        targets=[*payload["targets"], *watched_targets(a, deps.activity)],
    )
    assert new_id is not None
    deps.activity.mark_undone(a.id, new_id)  # U5
    deps.tools._export()
    return ActionResult(
        "undone", 200, {"status": "undone", "activity_id": new_id, "undone": a.id, "confirmation": summary}
    )


def _decide(deps: ActionDeps, spec: ActionSpec, req: ActionRequest, args: dict[str, Any]) -> ActionResult:
    if req.action == UNDO_KIND:
        return _undo(deps, req, args)
    if req.action == "decline_confirm":
        return _decline(deps, req, args)
    if req.confirm_token is not None:
        return _with_token(deps, spec, req, args)
    if req.channel == "app" and spec.needs_confirm is not None:
        summary = spec.needs_confirm(deps.tools, args, deps.tools.today())
        if summary is not None:
            if deps.confirms is None:  # 확인을 받을 곳이 없으면 바로 적용하지 않는다
                raise RuntimeError("needs_confirm without a confirms repo")
            p = deps.confirms.create(
                action=req.action, args=args, summary=summary, origin="actions",
                expires_at=deps.clock.now() + CONFIRM_TTL,
            )
            return ActionResult(
                "needs_confirm", 200,
                {"status": "needs_confirm", "confirm_token": p.token, "summary": summary,
                 "expires_at": api_time(p.expires_at)},
            )
    return _call(deps, spec, _context(req), args)


def _mark_answered(deps: ActionDeps, req: ActionRequest) -> None:
    """적용한 동작이 답한 회차가 있으면 처음 한 번 적는다(`harness.checkins.run_answered_by`, 동작이 커밋된 뒤)."""
    if deps.mark_answered is None or deps.runs is None or deps.settings is None:
        return
    from my_planner.harness.checkins import run_answered_by

    run_id = run_answered_by(
        req, runs=deps.runs, tasks=deps.tools.tasks, settings=deps.settings, now=deps.clock.now(),
        activity=deps.activity,
    )
    if run_id is not None:
        deps.mark_answered(run_id, "app" if req.channel == "app" else "telegram")


_REQUEST_KEY = "_request"  # 저장한 undo 응답 옆에 둔 요청(활동 id). 다시 돌려줄 때 뺀다


def _request_key(req: ActionRequest) -> Any:
    return req.args.get("activity_id") if isinstance(req.args, dict) else None


def _callable_from(spec: ActionSpec, req: ActionRequest) -> bool:
    """`endpoint`가 정해진 동작은 그 경로에서만, 그 밖의 내부 동작은 하루 한 번 작업(`scheduler`)에서만."""
    if spec.endpoint is not None:
        return req.endpoint == spec.endpoint
    return spec.public or req.channel == "scheduler"


def apply_action(deps: ActionDeps, req: ActionRequest) -> ActionResult:
    """즉시 갈래 하나(동기). 모듈 설명의 순서대로."""
    spec = ACTIONS.get(req.action)
    if spec is None or not _callable_from(spec, req):
        return _error("invalid", 400, "invalid_request", UNKNOWN_ACTION)
    # `push` 경로는 중복 방지 기록이 없다(`api_idempotency.endpoint`에 없는 값)
    if req.client_msg_id is not None and deps.idempotency is not None and req.endpoint != "push":
        stored = deps.idempotency.get(req.client_msg_id)
        if stored is not None:
            if stored.endpoint != req.endpoint:
                return _error("conflict", 409, "conflict", REUSED_ID)
            body = dict(stored.body or {})
            asked = body.pop(_REQUEST_KEY, None)
            if asked is not None and asked != _request_key(req):
                return _error("conflict", 409, "conflict", REUSED_ID)  # 같은 id를 다른 대상에 다시 썼다
            if req.endpoint == "undo" and body.get("status") == "undone":
                return _already_undone(body.get("activity_id"))  # U4: 같은 client_msg_id여도 두 번째는 already_undone
            return ActionResult(body.get("status", "conflict"), stored.status_code, body)
    args = req.args if req.args is not None else {}
    if not isinstance(args, dict) or not _accepts(deps, spec, args):
        return _error("invalid", 400, "invalid_request", BAD_ARGS)
    try:
        with transaction(deps.conn):
            res = _decide(deps, spec, req, args)
            if req.client_msg_id is not None and deps.idempotency is not None and req.endpoint != "push":
                stored_body = res.body if req.endpoint != "undo" else {**res.body, _REQUEST_KEY: _request_key(req)}
                deps.idempotency.put(
                    req.client_msg_id, req.endpoint, res.http_status, stored_body  # type: ignore[arg-type]
                )
    except Exception:
        # 적용과 응답 기록이 함께 되돌려졌다. `tasks.md`는 트랜잭션 밖 파일이라 지금 값으로 다시 만든다
        deps.tools._export()
        log.warning("action_failed", extra={"action": req.action, "channel": req.channel})
        raise
    if res.status == "applied":
        try:
            _mark_answered(deps, req)  # 동작은 이미 커밋됐다. 답 표시가 안 돼도 응답은 그대로다
        except Exception as e:  # noqa: BLE001 - 본문 없이 종류만 남긴다
            log.warning("action_answer_record_error", extra={"action": req.action, "error_type": type(e).__name__})
    log.info(
        "action_handled",
        extra={"action": req.action, "status": res.status, "actor": req.actor, "channel": req.channel},
    )
    return res
