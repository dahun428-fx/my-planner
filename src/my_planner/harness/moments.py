"""하루 끝 작업: 이룬 순간 (SP8 스펙 6.2~6.3, 6.8, ADR 0013).

정리할 날 고르기(`days_to_queue`), 두뇌 입력(`build_moments_input`), 지시문(`moments_system_prompt`), 호출 뒤 판정
(`settle`), 세션 파일 지우기(`remove_session_file`). 디스패처의 `_MomentsJob`이 이것들을 부른다.

순간의 글, 할 일 제목, 메시지는 로그에 남기지 않는다. `status_moment_days`와 `app_state.moments_since` 쓰기는
이 모듈에서만 한다(쓰기 경로 감시, `tests/test_write_paths.py`).
"""

from __future__ import annotations

import logging
import re
import shutil
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, tzinfo
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from my_planner.clock import logical_date
from my_planner.harness import prompts
from my_planner.status.xp import AREA_LABELS
from my_planner.store.db import transaction

if TYPE_CHECKING:
    from my_planner.harness.brain import BrainResult
    from my_planner.store.repos.conditions import ConditionsRepo
    from my_planner.store.repos.habits import HabitsRepo
    from my_planner.store.repos.moments import MomentsRepo
    from my_planner.store.repos.state import StateRepo
    from my_planner.store.repos.tasks import TasksRepo
    from my_planner.store.repos.workout import WorkoutRepo
    from my_planner.store.transcripts import TranscriptStore

log = logging.getLogger(__name__)

MOMENTS_LOOKBACK_DAYS = 7  # 어제부터 거꾸로 7일(6.2-2)
MOMENTS_MAX_TURNS = 3
MOMENTS_RESERVE_CALLS = 10  # 하루 두뇌 호출 상한 가운데 사용자 몫(6.2-5)
MOMENTS_MAX_ATTEMPTS = 2  # 두 번 해도 안 되면 `failed`(6.2-6)
MOMENTS_TASKS_MAX = 20
MOMENTS_CHAT_MAX_CHARS = 6000
MOMENT_DAYS_KEEP = 60  # `status_moment_days` 보관(6.4)
MOMENTS_SINCE_KEY = "moments_since"  # 처음 작업이 돈 날의 전날(이보다 앞날은 고르지 않는다)
MOMENTS_PAUSED_KEY = "moments_paused"  # "1"이면 고르지 않는다(16장 끄기)

_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_WEEKDAY = "월화수목금토일"
_BANNED_START = "<!-- banned-words:start -->"
_BANNED_END = "<!-- banned-words:end -->"


# --- 고르기 (6.2-2) ---


def days_to_queue(repo: MomentsRepo, state: StateRepo, today: date) -> list[date]:
    """정리할 날(오래된 날부터): 어제부터 7일, `moments_since` 이후, 행이 없거나 `pending`인 날.

    `moments_since`가 없으면 어제로 적는다. 행이 없던 날은 `pending` 행을 만든다(7일 밖의 날은 만들지 않는다).
    """
    if state.get(MOMENTS_PAUSED_KEY) == "1":
        return []
    yesterday = today - timedelta(days=1)
    with transaction(repo.conn):
        raw = state.get(MOMENTS_SINCE_KEY)
        if raw is None:
            since = yesterday
            state.set(MOMENTS_SINCE_KEY, since.isoformat())
        else:
            since = date.fromisoformat(raw)
        first = max(today - timedelta(days=MOMENTS_LOOKBACK_DAYS), since)
        rows = repo.days_since(first)
        picked: list[date] = []
        d = first
        while d <= yesterday:
            row = rows.get(d)
            if row is None:
                repo.mark(d, "pending", repo.clock.now())
            if row is None or row.state == "pending":
                picked.append(d)
            d += timedelta(days=1)
    return picked


def mark_empty(repo: MomentsRepo, day: date, now: datetime) -> None:
    """데이터가 없는 날(6.2-3). 두뇌를 부르지 않는다."""
    repo.mark(day, "empty", now)


# --- 입력 (6.3) ---


@dataclass(frozen=True)
class MomentsInput:
    text: str
    refs: frozenset[str]  # `sources`에 쓸 수 있는 값(M2)
    has_data: bool  # 끝낸 할 일·습관 체크·운동 기록·사용자 메시지 가운데 하나라도 있다(컨디션만이면 거짓)


def _area_names(areas: list[str]) -> str:
    return ", ".join(AREA_LABELS.get(a, a) for a in areas)


def _one_line(text: str) -> str:
    return " ".join(text.split())


def build_moments_input(
    day: date,
    *,
    tasks: TasksRepo,
    habits: HabitsRepo | None,
    conditions: ConditionsRepo | None,
    transcripts: TranscriptStore,
    tz: str | tzinfo,
    boundary: time,
    workout: WorkoutRepo | None = None,
) -> MomentsInput:
    """그날의 두뇌 입력. 끝낸 할 일 최대 20개(논리적 날짜, 초안·소프트 삭제 뺌), 그날 습관 체크 전부, 컨디션 점수,
    그날 운동 기록(제목만, SP12 5.6), 그날 원문 기록의 **사용자 줄만**(합쳐 6,000자, 넘으면 오래된 줄부터 뺀다). 메모·할 일 메모·컨디션 메모는 읽지 않는다."""
    refs: set[str] = set()
    done = [
        t for t in tasks.list(status="done", from_=day, to=day, limit=MOMENTS_TASKS_MAX)
        if t.completed_at is not None and logical_date(t.completed_at, tz, boundary) == day
    ]
    done.sort(key=lambda t: (t.completed_at, t.id))
    task_lines = []
    for t in done:
        refs.add(f"task:{t.id}")
        task_lines.append(f"- [task:{t.id}] {_one_line(t.title)} · {_area_names([a.value for a in t.areas])}")

    habit_lines = []
    if habits is not None:
        for hid in sorted(habits.checked_on(day)):
            h = habits.get(hid)
            if h is None:
                continue
            refs.add(f"habit:{h.id}")
            habit_lines.append(f"- [habit:{h.id}] {_one_line(h.title)} · {_area_names([h.area.value])}")

    workout_lines = []
    if workout is not None:
        for g in sorted(workout.logs(day, day), key=lambda g: g.id):
            refs.add(f"workout:{g.id}")
            workout_lines.append(f"- [workout:{g.id}] {_one_line(g.title)}")

    cond = conditions.get(day) if conditions is not None else None
    if cond is not None:
        refs.add("condition")

    all_chat = [f"- {hhmm} {_one_line(body)}" for hhmm, body in transcripts.user_lines(day) if body.strip()]
    chat = list(all_chat)
    while chat and sum(len(line) + 1 for line in chat) > MOMENTS_CHAT_MAX_CHARS:
        if len(chat) == 1:
            chat[0] = chat[0][: MOMENTS_CHAT_MAX_CHARS - 1]
            break
        chat.pop(0)  # 오래된 줄부터 뺀다
    if chat:
        refs.add("chat")

    none = "- 없음"
    text = "\n".join([
        "## 날짜",
        f"{day.isoformat()} ({_WEEKDAY[day.weekday()]})",
        "",
        "## 끝낸 할 일",
        *(task_lines or [none]),
        "",
        "## 체크한 습관",
        *(habit_lines or [none]),
        "",
        *(["## 운동 기록", *workout_lines, ""] if workout_lines else []),  # 기록이 없으면 섹션을 빼 입력이 그대로다
        "## 컨디션",
        f"{cond.score}/5" if cond is not None else "없음",
        "",
        "## 사용자 메시지 (두 통로, 오래된 것부터)",
        *(chat or [none]),
    ])
    return MomentsInput(
        text=text, refs=frozenset(refs),
        has_data=bool(done or habit_lines or workout_lines or all_chat),
    )


# --- 지시문 (6.3) ---


def banned_words_block() -> str:
    """`system.md`의 금지어 블록(과 그 앞 한 줄). 대화 요약 호출(SP9 7.2)도 쓴다."""
    lines = prompts.load("system.md").splitlines()
    start = next(i for i, line in enumerate(lines) if line.strip() == _BANNED_START)
    end = next(i for i, line in enumerate(lines) if line.strip() == _BANNED_END)
    return "\n".join(lines[max(start - 1, 0): end + 1])


def moments_system_prompt() -> str:
    """`moments.md` + 빈 줄 + `system.md`의 금지어 블록(과 그 앞 한 줄). 대화 원칙은 싣지 않는다."""
    return f"{prompts.load('moments.md')}\n\n{banned_words_block()}"


# --- 판정 (6.2-6) ---


def settle(
    repo: MomentsRepo, day: date, result: BrainResult, called: bool, now: datetime
) -> Literal["done", "pending", "failed"]:
    """호출이 끝난 뒤 그날의 상태로 판정한다(두뇌 상태가 아니라).

    `done`이면 성공. 도구를 안 부르고 `ok`면 `done`, `saved = 0`. `rate_limited`·`auth_error`로 끝나고 아직
    `pending`이면 `attempts` 그대로. 그 밖에 아직 `pending`이면 `attempts + 1`(2회면 `failed`, `pending` 행만).
    """
    row = repo.day(day)
    if row is not None and row.state != "pending":  # 도구가 저장했다(또는 그 사이 다른 작업이 정리했다)
        return "failed" if row.state == "failed" else "done"
    if result.status == "ok" and not called:
        repo.mark(day, "done", now, saved=0)  # "쓸 거리가 없었다"
        return "done"
    if result.status in ("rate_limited", "auth_error"):
        return "pending"
    got = repo.bump_attempt(day, now, MOMENTS_MAX_ATTEMPTS)
    return "failed" if got == "failed" else "pending"


# --- 세션 파일 (6.3, 계획 결정 18) ---


def claude_config_dir(environ: dict[str, str] | None = None) -> Path:
    """CLI가 세션 jsonl을 두는 곳: `CLAUDE_CONFIG_DIR`, 없으면 `~/.claude`."""
    import os

    env = os.environ if environ is None else environ
    return Path(env.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")


def remove_session_file(session_id: str | None, *, config_dir: Path, event: str = "moments_session_cleanup") -> bool:
    """순간 호출의 세션 파일(`<config>/projects/*/<id>.jsonl`)과 같은 id의 하위 폴더를 지운다. UUID 모양만.

    `no-session-persistence` 플래그와 겹으로 둔다(플래그가 먹으면 지울 것이 없다). 오류는 삼킨다. 로그에는
    지웠는지만 남긴다(경로·id 없음).
    """
    if not isinstance(session_id, str) or not _UUID.fullmatch(session_id):
        log.info(event, extra={"removed": False})
        return False
    removed = False
    try:
        projects = Path(config_dir) / "projects"
        for path in projects.glob(f"*/{session_id}.jsonl"):
            if path.is_file() or path.is_symlink():
                path.unlink(missing_ok=True)
                removed = True
        for path in projects.glob(f"*/{session_id}"):
            if path.is_symlink() or path.is_file():
                path.unlink(missing_ok=True)
                removed = True
            elif path.is_dir():
                shutil.rmtree(path)
                removed = True
    except OSError as e:
        log.warning(f"{event}_error", extra={"error_type": type(e).__name__})
    log.info(event, extra={"removed": removed})
    return removed
