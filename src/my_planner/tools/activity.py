"""활동 기록 (SP3-4 스펙 5.2, 6.4.4). 변경 도구가 데이터 변경과 같은 트랜잭션 안에서 부른다.

대상 문자열(5.2): `task:12`, `condition:2026-10-24`, `priorities:week:2026-W43`, `ladder:2026-10`, `areas:2026-Q4`,
`milestone:7`, `chapter:3`, `card:2`, `cards:order`,
`habit:3`, `habit:3:2026-10-24`(SP7 5.5), `moment:41`, `moments:2026-10-24`(SP8 6.4). `summary`는 확인 문구 한 줄이고 메시지 본문(메모 포함)은 넣지 않는다.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Any, Literal

from my_planner.domain import ActivityChannel, Actor, Risk, RunContext

if TYPE_CHECKING:
    from my_planner.store.repos.activity import Activity, ActivityRepo
    from my_planner.tools.core import Tools


def activity_origin(ctx: RunContext) -> tuple[Actor, ActivityChannel]:
    """(행위자, 활동 통로). 통로는 `activity_channel`이 있으면 그것(회차 첫 호출, 하루 한 번 작업), 없으면 대화 통로."""
    return ctx.actor, ctx.activity_channel if ctx.activity_channel is not None else ctx.channel


def task_target(task_id: int) -> str:
    return f"task:{task_id}"


def condition_target(d: date) -> str:
    return f"condition:{d.isoformat()}"


def priorities_target(cadence: str, period: str) -> str:
    return f"priorities:{cadence}:{period}"


CARDS_ORDER_TARGET = "cards:order"  # 고정 카드 순서(`reorder_cards`)


def card_target(card_id: int) -> str:
    return f"card:{card_id}"


def ladder_target(period: str) -> str:
    return f"ladder:{period}"


def areas_target(period: str) -> str:
    return f"areas:{period}"


def milestone_target(milestone_id: int) -> str:
    return f"milestone:{milestone_id}"


def chapter_target(chapter_id: int) -> str:
    return f"chapter:{chapter_id}"


def habit_target(habit_id: int) -> str:
    """습관 추가·고치기·상태(SP7 5.5)."""
    return f"habit:{habit_id}"


def habit_day_target(habit_id: int, d: date) -> str:
    """습관 체크·취소(SP7 5.5): 대상은 이것 하나다. 같은 날짜끼리만 U3로 서로 막는다. 원장 `source_ref`(X11)도 같다."""
    return f"habit:{habit_id}:{d.isoformat()}"


def moment_target(moment_id: int) -> str:
    """이룬 순간 숨기기·다시 보이기·지우기(SP8 6.4). 같은 순간끼리 U3로 서로 막는다."""
    return f"moment:{moment_id}"


def many_target(every: list[str]) -> tuple[str | None, list[str]]:
    """대상 여럿을 바꾼 활동의 (`target`, `targets`): 하나면 그 값, 여럿이면 NULL과 전부(5.2 `activity_targets`)."""
    return (every[0] if len(every) == 1 else None), every


def tasks_target(ids: list[int]) -> tuple[str | None, list[str]]:
    """할 일 여럿을 바꾼 활동의 (`target`, `targets`): 하나면 `task:12`, 여럿이면 NULL과 `task:` 전부."""
    return many_target([task_target(i) for i in ids])


def record_activity(
    repo: ActivityRepo | None,
    ctx: RunContext,
    *,
    kind: str,
    target: str | None,
    summary: str,
    risk: Risk | None = None,
    undo: dict[str, Any] | None,
    targets: list[str] | None = None,
) -> int | None:
    """활동 한 행을 쓰고 `ctx.activity_ids`(되돌릴 수 있으면 `ctx.undo_ids`도)에 더한다. 저장소가 없으면 None.

    `targets`는 바꾼 대상 전부(`activity_targets`, 없으면 `[target]`). `target`은 하나일 때만 그 값이다.
    `risk`를 주지 않으면 `ctx.risk`. `risk = confirm`으로 적용한 변경은 되돌릴 수 없다(6.4.2).
    """
    if repo is None:
        return None
    actor, channel = activity_origin(ctx)
    risk = risk if risk is not None else ctx.risk
    aid = repo.add(
        actor=actor, channel=channel, kind=kind, target=target, summary=summary, risk=risk, undo=undo,
        conversation_id=ctx.conversation_id, run_id=ctx.run_id, inbound_id=ctx.inbound_id, targets=targets,
    )
    ctx.activity_ids.append(aid)
    if risk == "low" and undo is not None:
        ctx.undo_ids.append(aid)
    return aid


# --- 되돌리기 (6.4.3) ---

UNDO_WINDOW = timedelta(hours=24)  # U2: 활동 뒤 24시간이 되면(딱 24시간 포함) 되돌릴 수 없다
UNDO_KIND = "undo"
SUPERSEDED = "superseded"

# 종류별 되돌리기: (도구, 입력, 맥락) → None(되돌림) 또는 `"superseded"`(되돌릴 수 없게 됐다).
# 입력은 활동의 `undo_json`에 `targets`(U3에서 나중에 바뀌지 않은 대상, `live_targets`)를 더한 것이다. 처리 함수는
# 실제로 되돌린 대상만 남기도록 `targets`를 좁힐 수 있다(되돌리기 활동이 그 대상을 적는다). 일부만 되돌리면
# `summary`(원래 활동 모양의 확인 문구)를 넣어, 되돌림 확인이 되돌린 것만 적게 한다.
# 처리 함수는 바깥 트랜잭션 안에서 불리고, `"superseded"`를 돌려주면 그 쓰기는 모두 되돌려진다.
UndoHandler = Callable[["Tools", dict[str, Any], RunContext], str | None]


class UndoRefused(Exception):
    """되돌리기 처리 함수가 상한 때문에 거절한다(SP9 메모: `too_many_memos`, `too_many_pinned`). 그 안의 쓰기는
    되돌려지고 `422`와 그 코드·문구로 답한다."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(code)
        self.code = code
        self.message = message
UNDO_HANDLERS: dict[str, UndoHandler] = {}

# (종류, 대상 접두): 그 종류 행의 그 대상은 "지켜보는" 대상이다. 확인 토큰 stale 판정(티켓 04)에는 쓰지만
# U3("같은 target을 바꾼")에서는 보지 않는다. 우선순위 목록 변경은 목록만 바꾸고 그 안의 할 일은 바꾸지 않는다.
WATCH_ONLY_TARGETS: tuple[tuple[str, str], ...] = (("priorities_set", "task:"),)
# 대상마다 U3를 판정하는 종류: 나중에 바뀌지 않은 대상만 되돌리고, 하나도 없을 때만 superseded(6.4.3 표)
U3_PER_TARGET = frozenset({"tasks_confirmed"})

UndoBlock = Literal["not_undoable", "undo_expired", "superseded"]


def register_undo(kind: str, handler: UndoHandler) -> None:
    """활동 종류 하나의 되돌리기를 더한다(`tools/core.py`가 할 일·우선순위·컨디션·카드·곡선을)."""
    if kind == UNDO_KIND:
        raise ValueError("되돌리기는 되돌리지 않는다(U5)")
    UNDO_HANDLERS[kind] = handler


def _handlers() -> dict[str, UndoHandler]:
    """등록된 되돌리기. 할 일·우선순위·컨디션 처리 함수는 `tools.core`가 등록하므로, 누가 먼저 무엇을 가져왔든
    여기서 그 모듈을 불러온다(가져오는 순서에 따라 `undo_id`가 조용히 모두 비지 않게)."""
    import my_planner.tools.core  # noqa: F401 - 등록(순환 가져오기를 피해 함수 안에서)

    return UNDO_HANDLERS


def _watch_only(kind: str, target: str) -> bool:
    return any(kind == k and target.startswith(p) for k, p in WATCH_ONLY_TARGETS)


def watched_targets(a: Activity, repo: ActivityRepo) -> list[str]:
    """그 활동의 지켜보는 대상. 되돌리기 행도 적는다: 확인 토큰의 stale 판정이 그 되돌림을 보게(U3은 거른다)."""
    return [t for t in repo.targets(a.id) if _watch_only(a.kind, t)]


def live_targets(a: Activity, repo: ActivityRepo) -> tuple[list[str], list[str]]:
    """(U3이 보는 대상, 그 가운데 나중에 바뀌지 않은 것). 나중 행은 `(at, id)`가 큰 되돌리지 않은 행이고,
    다른 행의 지켜보는 대상(`WATCH_ONLY_TARGETS`)은 바꾼 것으로 세지 않는다."""
    own = [t for t in repo.targets(a.id) if not _watch_only(a.kind, t)]
    live = [
        t for t in own
        if not repo.changed_after(t, a.at, after_id=a.id, skip_undone=True, ignore=WATCH_ONLY_TARGETS)
    ]
    return own, live


def undo_block(a: Activity, repo: ActivityRepo, now: datetime) -> UndoBlock | None:
    """U1~U3을 `now`로 판정한다. 되돌릴 수 있으면 None. 이미 되돌린 행(U4)은 따로 본다."""
    if a.risk != "low" or a.undo is None or a.kind not in _handlers():
        return "not_undoable"  # U1. 되돌리기 활동은 `undo_json`이 없다(U5)
    if now >= a.at + UNDO_WINDOW:
        return "undo_expired"  # U2
    own, live = live_targets(a, repo)
    if a.kind in U3_PER_TARGET:
        if own and not live:
            return "superseded"  # U3. 대상마다: 하나도 남지 않았을 때만
    elif len(live) != len(own):
        return "superseded"  # U3. 여러 대상 활동은 하나라도 나중에 바뀌면
    return None


def undoable_now(a: Activity, repo: ActivityRepo, now: datetime) -> bool:
    """지금 되돌릴 수 있다(U1~U3, 아직 되돌리지 않았다). `GET /activity`의 `undo_id`(6.4.4)."""
    return a.undone_at is None and undo_block(a, repo, now) is None
