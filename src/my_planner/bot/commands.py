"""명령 /today /week /status /habits /help /pause /unpause /plan /done (스펙 5.6, SP3-4 11.4, SP7 5.7). /plan 말고는
두뇌를 거치지 않고 하네스가 바로 답한다.

/today /week /status /habits는 읽기 전용이다. /habits는 텔레그램에서만 습관 버튼을 붙인다(`telegram_io._answer_command`). 초안(`draft`)과 내려놓은 것, 끝낸 것은 보여 주지 않는다.

텔레그램과 앱(`POST /chat`, SP3-4 6.4.1)이 같은 함수 `run_command`를 쓴다. 상태를 바꾸는 `/pause`, `/unpause`,
`/done`은 즉시 갈래(`apply_action`의 내부 동작 `cmd_*`)로 처리하고, 앱 요청이면 그 자리에서 `api_idempotency`에
답을 적는다(같은 `client_msg_id`가 다시 와도 다시 실행하지 않는다).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, time, timedelta, tzinfo
from datetime import datetime as _datetime
from typing import TYPE_CHECKING, Any, Protocol

from my_planner.clock import Clock, from_iso, local, logical_date, to_iso
from my_planner.probe import command_probe_on
from my_planner.store.repos.state import PAUSE_UNTIL_KEY, StateRepo
from my_planner.store.repos.tasks import Task, TasksRepo
from my_planner.store.views import WEEKDAY, today_view, week_view

if TYPE_CHECKING:
    from my_planner.domain import Channel
    from my_planner.harness.conversations import ConversationRouter
    from my_planner.store.repos.conditions import ConditionsRepo
    from my_planner.store.repos.curve import CurveRepo
    from my_planner.store.repos.habits import HabitsRepo
    from my_planner.store.repos.status import StatusRepo
    from my_planner.tools.actions import ActionRequest, ActionResult

HELP_TEXT = (
    "쓸 수 있는 명령이에요.\n"
    "/today  오늘 우선순위, 일정, 열린 할 일\n"
    "/week  이번 주 우선순위와 할 일\n"
    "/status  레벨, 스탯, 퀘스트\n"
    "/habits — 오늘 습관 체크\n"
    "/pause 3  사흘 동안 먼저 연락하지 않기(1~14일)\n"
    "/unpause  멈춤 풀기\n"
    "/plan 주제  함께 계획 세우기(주제는 없어도 돼요)\n"
    "/done  계획 대화 마치기\n"
    "/help  이 안내\n"
    "\n"
    "그 밖에는 그냥 말씀해 주세요. 할 일 추가, 옮기기, 완료, 우선순위 정하기를 도와 드려요."
)

COMMANDS = ("/today", "/week", "/status", "/habits", "/help", "/pause", "/unpause", "/plan", "/done", "/medic_probe")

PROBE_OFF_REPLY = "개발용 명령이에요. 지금은 꺼져 있어요."

PAUSE_MIN_DAYS, PAUSE_MAX_DAYS = 1, 14
PAUSE_USAGE = "쉴 날 수를 1~14 사이로 함께 적어 주세요. 예: /pause 3"
UNPAUSE_REPLY = "멈춤을 풀었어요. 다시 정해진 시각에 연락할게요."
NOT_PAUSED_REPLY = "지금은 멈춤 중이 아니에요."

# 계획 모드 (스펙 5.7). /plan은 주제(없으면 PLAN_START_TEXT)를 계획 대화로 디스패처에 넘긴다
PLAN_START_TEXT = "계획 모드 시작"
PLAN_DONE_REPLY = "계획 대화를 마칠게요. 다시 함께 정리하고 싶으면 /plan을 보내 주세요."
NO_PLAN_REPLY = "지금 열린 계획 대화가 없어요."


def command_of(text: str) -> str | None:
    """`/today`, `/today@봇이름 인자`처럼 오는 글에서 우리가 직접 답하는 명령 이름. 아니면 None."""
    words = text.strip().split(None, 1)
    if not words or not words[0].startswith("/"):
        return None
    name = words[0].split("@", 1)[0].lower()
    return name if name in COMMANDS else None


def plan_topic(text: str) -> str:
    """`/plan [주제]`의 주제. 없으면 "계획 모드 시작"."""
    words = text.strip().split(None, 1)
    topic = words[1].strip() if len(words) == 2 else ""
    return topic or PLAN_START_TEXT


def pause_days(text: str) -> int | None:
    """`/pause <일수>`의 일수. 정수가 아니거나 1~14 밖이면 None."""
    words = text.strip().split()
    if len(words) != 2 or not (words[1].isascii() and words[1].isdecimal()):
        return None
    n = int(words[1])
    return n if PAUSE_MIN_DAYS <= n <= PAUSE_MAX_DAYS else None


def pause_reply(until: _datetime, tz: str | tzinfo) -> str:
    lt = local(until, tz)
    return (
        f"{lt.month}월 {lt.day}일 {lt:%H:%M}까지 먼저 연락하지 않을게요. 그동안에도 말씀하시면 답해요. "
        "다시 시작하려면 /unpause를 보내 주세요."
    )


def _md(d: date) -> str:
    return f"{d.month}/{d.day}"


def _numbered(items: list[Task]) -> str:
    return "\n".join(f"{i}. {t.title}" for i, t in enumerate(items, start=1))


def today_text(tasks: TasksRepo, now: _datetime, tz: str | tzinfo, boundary: time) -> str:
    """`store.views.today_view`를 글로 바꾸기만 한다(`GET /today`와 같은 뷰)."""
    view = today_view(tasks, None, now, tz, boundary)
    out = [f"오늘 ({_md(view.date)} {view.weekday})"]
    for g in view.groups:
        if g.name == "priority":
            out.append("우선순위\n" + _numbered(g.tasks))
        elif g.name == "scheduled":
            out.append("일정\n" + "\n".join(f"- {local(t.scheduled_at, tz):%H:%M} {t.title}" for t in g.tasks))  # type: ignore[arg-type]
        else:
            lines = [
                f"- {t.title}" + (f" ({_md(t.planned_for)})" if t.planned_for < view.date else "")  # type: ignore[operator,arg-type]
                for t in g.tasks
            ]
            out.append("열린 할 일\n" + "\n".join(lines))
    if len(out) == 1:
        out.append("아직 비어 있어요. 하고 싶은 일을 말씀해 주세요.")
    return "\n\n".join(out)


def week_text(tasks: TasksRepo, now: _datetime, tz: str | tzinfo, boundary: time) -> str:
    """`store.views.week_view`를 글로 바꾸기만 한다(`GET /week`와 같은 뷰). 할 일이 없는 날은 글에서만 뺀다."""
    view = week_view(tasks, now, tz, boundary)
    out = [f"이번 주 ({_md(view.start)}~{_md(view.end)})"]
    if view.priorities:
        out.append("우선순위\n" + _numbered(view.priorities))
    for day in view.days:
        if not day.tasks:
            continue
        lines = []
        for t in day.tasks:
            at = f"{local(t.scheduled_at, tz):%H:%M} " if t.scheduled_at else ""
            lines.append(f"- {at}{t.title}")
        mark = " (오늘)" if day.is_today else ""
        out.append(f"{_md(day.date)} {day.weekday}{mark}\n" + "\n".join(lines))
    if len(out) == 1:
        out.append("아직 비어 있어요. 하고 싶은 일을 말씀해 주세요.")
    return "\n\n".join(out)


# --- 상태창 (SP3-4 11.4) ---

EMPTY_STATS = "영역 점수는 분기 마지막 주 회고에서 함께 정해요."  # 부록 A "/status 빈 스탯"
STATUS_UNAVAILABLE = "상태창을 읽을 수 없어요."


def status_text(snap: dict[str, Any]) -> str:
    """`status_snapshot()`(`GET /status`와 같은 값)을 글로 바꾸기만 한다(11.4). 빈 묶음은 뺀다."""
    hp = snap["hp"]["score"]
    blocks = [
        "상태창\n"
        f"레벨 {snap['level']} · 경험치 {snap['xp_into_level']}/{snap['xp_for_next']}\n"
        + (f"HP {hp}/5 (오늘 컨디션)" if hp is not None else "HP 기록 없음 (오늘 컨디션)")
    ]
    scored = [s for s in snap["stats"] if s["score"] is not None]
    if not scored:
        blocks.append(EMPTY_STATS)
    else:
        latest = max(s["period"] for s in scored)

        def stat(s: dict[str, Any]) -> str:
            if s["score"] is None:
                return f"{s['label']} -"
            older = f" ({s['period']})" if s["period"] != latest else ""
            return f"{s['label']} {s['score']}{older}" + (" ↓" if s["debuff"] else "")

        lines = [f"스탯 ({latest})", " · ".join(stat(s) for s in snap["stats"])]
        lines += [
            f"↓ {s['label']} {s['prev_score']} → {s['score']}: 회복 퀘스트 \"{s['recovery_quest']}\""
            for s in snap["stats"] if s["debuff"]
        ]
        blocks.append("\n".join(lines))
    if snap["main_quests"]:
        blocks.append("메인 퀘스트\n" + "\n".join(
            f"{q['rank']}. {q['title']} (첫 걸음 {q['first_steps']['done']}/"
            f"{q['first_steps']['done'] + q['first_steps']['open']})"
            for q in snap["main_quests"]
        ))
    if snap["daily_quests"]:
        blocks.append("오늘의 퀘스트\n" + "\n".join(f"- {q['title']}" for q in snap["daily_quests"]))
    titles = snap["titles"]
    if titles:
        more = f" 외 {len(titles) - 1}개" if len(titles) > 1 else ""
        blocks.append(f"칭호: {titles[0]['title']}{more}")
    return "\n\n".join(blocks)


def _status_reply(deps: CommandDeps, now: _datetime) -> str:
    from my_planner.status.snapshot import status_snapshot

    if deps.status is None or deps.curve is None or deps.conditions is None:
        return STATUS_UNAVAILABLE
    snap = status_snapshot(
        now=now, tz=_tz(deps), boundary=_boundary(deps), status=deps.status, curve=deps.curve, tasks=deps.tasks,
        conditions=deps.conditions,
    )
    return status_text(snap)


# --- 습관 (SP7 5.7, 부록 A) ---

HABITS_EMPTY = "아직 습관이 없어요. '매일 물 마시기 습관 추가해 줘'처럼 말하면 만들어 드려요."
HABITS_UNAVAILABLE = "습관을 다룰 수 없어요."


def habits_text(habits: HabitsRepo, today: date) -> str:
    """`/habits`의 글: `오늘 습관 (10/24 토)` 다음 활성 습관마다 한 줄. 주 N회 습관은 이번 주(ISO 주) 체크 수와 목표,
    매일 습관은 제목만. 활성 습관이 없으면 빈 목록 문구. 텔레그램과 앱이 같은 글이다."""
    active = habits.list()
    if not active:
        return HABITS_EMPTY
    counts = habits.week_counts(today - timedelta(days=today.weekday()))
    lines = [f"오늘 습관 ({_md(today)} {WEEKDAY[today.weekday()]})"]
    for h in active:
        if h.kind == "weekly":
            lines.append(f"- {h.title} · 이번 주 {counts.get(h.id, 0)}번 / 목표 {h.target_per_week}번")
        else:
            lines.append(f"- {h.title}")
    return "\n".join(lines)


# --- 상태를 바꾸는 명령 (즉시 갈래의 내부 동작 `cmd_*`이 부른다) ---


def cmd_pause(state: StateRepo, now: _datetime, text: str, tz: str | tzinfo) -> str:
    days = pause_days(text)
    if days is None:
        return PAUSE_USAGE
    until = now + timedelta(days=days)  # 지금부터 N×24시간(스펙 5.6)
    state.set(PAUSE_UNTIL_KEY, to_iso(until))
    return pause_reply(until, tz)


def cmd_unpause(state: StateRepo, now: _datetime) -> str:
    v = state.get(PAUSE_UNTIL_KEY)
    state.set(PAUSE_UNTIL_KEY, None)
    return UNPAUSE_REPLY if v and from_iso(v) > now else NOT_PAUSED_REPLY


def cmd_done(router: ConversationRouter, channel: Channel) -> str:
    return PLAN_DONE_REPLY if router.end_plan(channel) else NO_PLAN_REPLY


# 상태를 바꾸는 명령 → 즉시 갈래의 내부 동작. 이 명령들은 즉시 갈래가 `api_idempotency`에 답을 적는다(6.4.1)
STATEFUL_COMMANDS: dict[str, str] = {"/pause": "cmd_pause", "/unpause": "cmd_unpause", "/done": "cmd_done"}


class TimeSettings(Protocol):
    """명령이 쓰는 시간 설정(`config.Settings`가 이 모양이다)."""

    @property
    def timezone(self) -> str | tzinfo: ...

    @property
    def day_boundary(self) -> time: ...


@dataclass(frozen=True)
class LocalTime:
    """`TimeSettings`의 단순한 구현(텔레그램 쪽은 `Tools`의 값으로 만든다)."""

    timezone: str | tzinfo
    day_boundary: time


@dataclass
class CommandDeps:
    """명령 하나에 필요한 것. `apply`는 즉시 갈래(`Dispatcher.apply_action`). 없으면 같은 함수를 바로 부른다(SP1 시험)."""

    tasks: TasksRepo
    conditions: ConditionsRepo | None
    state: StateRepo
    router: ConversationRouter | None
    clock: Clock
    settings: TimeSettings
    apply: Callable[[ActionRequest], ActionResult] | None = None
    status: StatusRepo | None = None  # `/status`(11.4). 없으면 "상태창을 읽을 수 없어요."
    curve: CurveRepo | None = None
    habits: HabitsRepo | None = None  # `/habits`(SP7 5.7). 없으면 "습관을 다룰 수 없어요."


def _tz(deps: CommandDeps) -> str | tzinfo:
    return deps.settings.timezone


def _boundary(deps: CommandDeps) -> time:
    return deps.settings.day_boundary


def run_command(
    cmd: str, text: str, deps: CommandDeps, *, channel: Channel, client_msg_id: str | None = None
) -> str:
    """명령의 답 글. `/plan`은 두뇌 갈래로 가므로 여기 오지 않는다.

    상태를 바꾸는 명령은 `deps.apply`(즉시 갈래)로: 앱 요청이면 `client_msg_id`로 답을 저장하고, 같은 값이 다시 오면
    저장한 답을 돌려준다.
    """
    now = deps.clock.now()
    if cmd == "/help":
        return HELP_TEXT
    if cmd == "/medic_probe":  # 개발용 결함 주입(SP6 스펙 12장, `my_planner.probe`). 도움말에는 없다
        if command_probe_on():
            raise KeyError("probe")
        return PROBE_OFF_REPLY
    if cmd in ("/today", "/week"):
        render = today_text if cmd == "/today" else week_text
        return render(deps.tasks, now, _tz(deps), _boundary(deps))
    if cmd == "/status":
        return _status_reply(deps, now)
    if cmd == "/habits":
        if deps.habits is None:
            return HABITS_UNAVAILABLE
        return habits_text(deps.habits, logical_date(now, _tz(deps), _boundary(deps)))
    action = STATEFUL_COMMANDS.get(cmd)
    if action is None:
        raise ValueError(f"unknown command: {cmd}")
    if deps.apply is None:
        if cmd == "/pause":
            return cmd_pause(deps.state, now, text, _tz(deps))
        if cmd == "/unpause":
            return cmd_unpause(deps.state, now)
        assert deps.router is not None
        return cmd_done(deps.router, channel)
    from my_planner.tools.actions import ActionRequest

    args = {"text": text} if cmd == "/pause" else {}
    res = deps.apply(
        ActionRequest(action, args, actor="user", channel=channel, client_msg_id=client_msg_id, endpoint="chat")
    )
    reply = res.body.get("reply_text")
    if not isinstance(reply, str):
        raise RuntimeError(f"command action failed: {res.status}")  # noqa: TRY004 - 동작 결과 오류다
    return reply
