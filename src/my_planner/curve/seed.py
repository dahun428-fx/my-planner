"""`python -m my_planner seed-life <파일> [--dry-run]` (SP3-4 스펙 12장, 티켓 12).

검토한 시드 파일에서 챕터, 사건, 영역 기본 퀘스트, 질문을 **한 트랜잭션**으로 가져온다. 두뇌를 거치지 않는다.

- 단일 작성자: BE와 같은 잠금(`state/my-planner.lock`)을 잡는다. 못 잡으면 코드 3.
- 한 번만: 끝나면 `app_state.life_seed_imported_at`을 적고, 이 값이 있으면 다시 가져오지 않는다(코드 4).
- 개인 정보: 출력은 개수뿐이다. 제목, 메모, 퀘스트, 질문, 파일 내용은 출력하지도 로그에 남기지도 않는다.
- 영역 점수(`areas[].score`)와 최상위 `ladder`는 읽지 않는다(회고에서 사용자가 답할 때 생긴다). 챕터의 기억한 사다리
  `chapters[].ladder?`(정수 0~10)와 사건의 대표 영역 `events[].area?`는 가져온다(SP8 8.1, 틀리면 그 항목 `invalid`).

`seed-life --update-history <파일> [--dry-run]`(SP8 8.1)은 이미 가져온 DB의 빈 칸(사건 `area`, 챕터
`ladder_remembered`)만 같은 파일에서 채운다. 같은 잠금, 같은 확인 규칙, 같은 출력 규칙(개수만)이고 한 번만 돈다
(`app_state.life_seed_history_updated_at`, 다시 돌리면 코드 4). 시드를 아직 가져오지 않았으면 코드 7.
- 칭호: 가져온 높은 때·전환점마다 하나. 경험치는 주지 않고 활동 기록·칭호 이벤트도 남기지 않는다.
"""

from __future__ import annotations

import json
import re
import sqlite3
import sys
from collections import Counter
from collections.abc import Callable
from contextlib import AbstractContextManager, ExitStack
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, TextIO

from my_planner.clock import Clock, SystemClock, to_iso
from my_planner.config import PathsConfig
from my_planner.domain import Area
from my_planner.platform.windows import AlreadyRunning, SingleInstanceLock
from my_planner.store.db import migrate, open_db, open_ro, transaction
from my_planner.store.exports import export_curve
from my_planner.store.repos.curve import CurveRepo, date_precision
from my_planner.store.repos.state import StateRepo
from my_planner.store.repos.status import StatusRepo

EXIT_OK = 0
EXIT_RUNNING = 3
EXIT_ALREADY = 4
EXIT_NOT_REVIEWED = 5
EXIT_BAD_FILE = 6
EXIT_NOT_IMPORTED = 7  # `--update-history`인데 시드를 아직 가져오지 않았다(SP8 계획 결정 15)

LOCK_FILE = "my-planner.lock"  # app.LOCK_FILE와 같다(app은 텔레그램·SDK를 불러와서 여기서 가져오지 않는다)
DB_FILE = "planner.db"  # app.DB_FILE와 같다
IMPORTED_AT_KEY = "life_seed_imported_at"
HISTORY_UPDATED_AT_KEY = "life_seed_history_updated_at"

RUNNING_MESSAGE = "my-planner가 실행 중이에요. 작업 스케줄러에서 멈춘 뒤 다시 실행해 주세요."  # 부록 A
ALREADY_MESSAGE = "이미 시드를 가져왔어요. 다시 가져오지 않아요."
NOT_REVIEWED_MESSAGE = "시드 파일을 검토한 뒤 meta.reviewed를 true로 넣어 주세요. 아무것도 가져오지 않았어요."
BAD_FILE_MESSAGE = "시드 파일을 읽을 수 없어요(없는 파일이거나 JSON 객체가 아니에요). 아무것도 가져오지 않았어요."
DB_REJECTED_MESSAGE = "시드 항목 가운데 DB에 넣을 수 없는 것이 있어요. 아무것도 가져오지 않았어요."
DONE_MESSAGE = "가져왔어요."
DRY_RUN_MESSAGE = "--dry-run: 아무것도 쓰지 않았어요."
HISTORY_ALREADY_MESSAGE = "이미 채웠어요."  # SP8 부록 A
NOT_IMPORTED_MESSAGE = "아직 가져온 시드가 없어요. 먼저 seed-life로 가져와 주세요."  # SP8 계획 문구 표

SkipReason = Literal["sensitive_unconfirmed", "storage_unconfirmed", "invalid", "ambiguous"]
# 가져오기의 이유. `ambiguous`(같은 `date + title` 항목이 둘 이상)는 `--update-history`만 쓴다
SKIP_REASONS: tuple[SkipReason, ...] = ("sensitive_unconfirmed", "storage_unconfirmed", "invalid")
HISTORY_SKIP_REASONS: tuple[SkipReason, ...] = (*SKIP_REASONS, "ambiguous")

_CERTAINTY = {"사실": "fact", "추정": "estimate", "fact": "fact", "estimate": "estimate"}
_KIND = {"high": "high", "low": "low", "turning": "turning_point"}
_AREAS = frozenset(a.value for a in Area)
MAX_TITLE = 100  # curve_chapters.title, curve_milestones.title CHECK
# 12장 표의 필수 키(`?`가 붙지 않은 것). 빠지면 그 항목은 `invalid`다. 값을 읽지 않는 키(`score`, `evidence`)도 있어야 한다
REQUIRED_KEYS = {
    "chapters": ("id", "title", "start", "end", "source", "certainty", "note"),
    "events": ("date", "title", "kind", "chapter_id", "source", "certainty", "kind_certainty", "sensitive"),
    "curve_sketch": ("chapter_id", "direction", "certainty"),
    "areas": ("key", "label", "score", "evidence", "source", "quest", "sensitive"),
}
# ASCII 숫자만(전각 숫자는 `str.isdigit()`을 통과하지만 DB의 GLOB CHECK에 걸린다)
_MONTH_RE = re.compile(r"\d{4}-\d{2}", re.ASCII)
_EVENT_DATE_RE = re.compile(r"\d{4}(-\d{2})?", re.ASCII)  # 12장: 'YYYY' | 'YYYY-MM'
MAX_QUEST = 80  # curve_area_defaults.recovery_quest CHECK
LADDER_MIN, LADDER_MAX = 0, 10  # curve_chapters.ladder_remembered CHECK (015)


class SeedFileError(Exception):
    """파일이 없거나, 읽을 수 없거나, JSON 객체가 아니다. 메시지에 파일 내용을 넣지 않는다."""


@dataclass(frozen=True)
class SeedChapter:
    seed_key: str
    title: str
    start_month: str
    end_month: str | None
    theme: str | None
    certainty: str
    source_ref: str | None
    ladder: int | None = None  # 그 시기를 돌아보며 기억하는 사다리 칸(SP8 8.1)


@dataclass(frozen=True)
class SeedEvent:
    date_text: str
    kind: str
    title: str
    note: str | None
    chapter_key: str | None  # 가져오는 챕터의 seed_key. 건너뛰었거나 없는 챕터면 None
    sensitive: bool
    certainty: str
    kind_certainty: str
    source_ref: str | None
    area: str | None = None  # 대표 영역 하나(SP8 8.1)


@dataclass
class SeedPlan:
    chapters: list[SeedChapter] = field(default_factory=list)
    events: list[SeedEvent] = field(default_factory=list)
    quests: dict[str, str] = field(default_factory=dict)  # 영역 → 기본 회복 퀘스트
    sketches: dict[str, str] = field(default_factory=dict)  # 챕터 seed_key → sketch
    questions: list[str] = field(default_factory=list)
    skipped: Counter[SkipReason] = field(default_factory=Counter)


def load_seed(path: Path | str) -> dict[str, Any]:
    """`utf-8-sig`로 읽는다(메모장 BOM). 최상위가 객체가 아니면 `SeedFileError`."""
    try:
        text = Path(path).read_text(encoding="utf-8-sig")
        data = json.loads(text)
    except (OSError, UnicodeDecodeError, ValueError) as e:
        raise SeedFileError("unreadable") from e
    if not isinstance(data, dict):
        raise SeedFileError("not an object")
    return data


def is_reviewed(seed: dict[str, Any]) -> bool:
    meta = seed.get("meta")
    return isinstance(meta, dict) and meta.get("reviewed") is True


class _Invalid(Exception):
    pass


def _gate(section: str, item: dict[str, Any]) -> SkipReason | None:
    """필수 키 → 확인 규칙(`sensitive: true`이거나 `storage` 키가 있으면 `confirmed: true`일 때만)."""
    if any(k not in item for k in REQUIRED_KEYS[section]):
        return "invalid"
    sensitive = item.get("sensitive", False)  # 챕터는 `sensitive`가 선택 키다
    if not isinstance(sensitive, bool):
        return "invalid"
    if item.get("confirmed") is True:
        return None
    if sensitive:
        return "sensitive_unconfirmed"
    if "storage" in item:
        return "storage_unconfirmed"
    return None


def _text(item: dict[str, Any], key: str, *, max_len: int | None = None) -> str:
    v = item.get(key)
    if not isinstance(v, str) or not v.strip():
        raise _Invalid(key)
    if max_len is not None and len(v) > max_len:
        raise _Invalid(key)
    return v


def _opt_text(item: dict[str, Any], key: str) -> str | None:
    v = item.get(key)
    if v is None:
        return None
    if not isinstance(v, str):
        raise _Invalid(key)
    return v or None


def _certainty(item: dict[str, Any], key: str) -> str:
    v = item.get(key)  # 필수 키다: 기본값으로 채우지 않는다(추정을 사실로 저장하지 않게)
    if not isinstance(v, str) or v not in _CERTAINTY:
        raise _Invalid(key)
    return _CERTAINTY[v]


def _month(v: Any) -> str:
    if not isinstance(v, str) or not _MONTH_RE.fullmatch(v):
        raise _Invalid("month")
    try:
        precision, _ = date_precision(v)
    except ValueError as e:
        raise _Invalid("month") from e
    if precision != "month":
        raise _Invalid("month")
    return v


def _chapter(item: dict[str, Any]) -> SeedChapter:
    key = _text(item, "id")
    start = _month(item.get("start"))
    end = None if item.get("end") is None else _month(item.get("end"))
    if end is not None and end < start:
        raise _Invalid("end")
    return SeedChapter(
        seed_key=key, title=_text(item, "title", max_len=MAX_TITLE), start_month=start, end_month=end,
        theme=_opt_text(item, "note"), certainty=_certainty(item, "certainty"), source_ref=_opt_text(item, "source"),
        ladder=_ladder(item),
    )


def _ladder(item: dict[str, Any]) -> int | None:
    """`chapters[].ladder?`: 정수 0~10. `true`, `6.0`, 문자열은 틀린 값이다."""
    v = item.get("ladder")
    if v is None:
        return None
    if not isinstance(v, int) or isinstance(v, bool) or not LADDER_MIN <= v <= LADDER_MAX:
        raise _Invalid("ladder")
    return v


def _area(item: dict[str, Any]) -> str | None:
    """`events[].area?`: 6개 영역 코드 가운데 하나."""
    v = item.get("area")
    if v is None:
        return None
    if not isinstance(v, str) or v not in _AREAS:
        raise _Invalid("area")
    return v


def _event(item: dict[str, Any], chapter_keys: set[str]) -> SeedEvent:
    date_text = _text(item, "date")
    if not _EVENT_DATE_RE.fullmatch(date_text):
        raise _Invalid("date")
    try:
        date_precision(date_text)
    except ValueError as e:
        raise _Invalid("date") from e
    kind = item.get("kind")
    if not isinstance(kind, str) or kind not in _KIND:
        raise _Invalid("kind")
    chapter = item.get("chapter_id")
    if chapter is not None and not isinstance(chapter, str):
        raise _Invalid("chapter_id")
    return SeedEvent(
        date_text=date_text, kind=_KIND[kind], title=_text(item, "title", max_len=MAX_TITLE),
        note=_opt_text(item, "note"), chapter_key=chapter if chapter in chapter_keys else None,
        sensitive=item["sensitive"] is True, certainty=_certainty(item, "certainty"),
        kind_certainty=_certainty(item, "kind_certainty"), source_ref=_opt_text(item, "source"), area=_area(item),
    )


def _items(seed: dict[str, Any], key: str, skipped: Counter[SkipReason]) -> list[Any]:
    """없으면 빈 목록. 목록이 아니면 그 묶음 전체를 `invalid` 하나로 센다."""
    v = seed.get(key)
    if v is None:
        return []
    if not isinstance(v, list):
        skipped["invalid"] += 1
        return []
    return v


def plan_import(seed: dict[str, Any]) -> SeedPlan:
    """순수 함수: 무엇을 가져오고 무엇을 왜 건너뛰는지. `seed`를 바꾸지 않는다. 점수와 `ladder`는 읽지 않는다."""
    plan = SeedPlan()
    skipped = plan.skipped

    section = "chapters"
    for item in _items(seed, section, skipped):
        if not isinstance(item, dict):
            skipped["invalid"] += 1
            continue
        if reason := _gate(section, item):
            skipped[reason] += 1
            continue
        try:
            chapter = _chapter(item)
        except _Invalid:
            skipped["invalid"] += 1
            continue
        if any(c.seed_key == chapter.seed_key for c in plan.chapters):
            skipped["invalid"] += 1  # seed_key는 UNIQUE
            continue
        plan.chapters.append(chapter)
    chapter_keys = {c.seed_key for c in plan.chapters}

    section = "events"
    for item in _items(seed, section, skipped):
        if not isinstance(item, dict):
            skipped["invalid"] += 1
            continue
        if reason := _gate(section, item):
            skipped[reason] += 1
            continue
        try:
            plan.events.append(_event(item, chapter_keys))
        except _Invalid:
            skipped["invalid"] += 1

    for item in _items(seed, "curve_sketch", skipped):
        if not isinstance(item, dict):
            skipped["invalid"] += 1
            continue
        if _gate("curve_sketch", item) == "invalid":
            skipped["invalid"] += 1
            continue
        try:
            key = _text(item, "chapter_id")
            direction = _text(item, "direction")
            _certainty(item, "certainty")  # 확인만 한다. 챕터의 certainty는 챕터 것을 쓴다
        except _Invalid:
            skipped["invalid"] += 1
            continue
        if key in chapter_keys:  # 건너뛴 챕터의 그림은 그 챕터와 함께 빠진다(따로 세지 않는다)
            plan.sketches[key] = direction

    section = "areas"
    for item in _items(seed, section, skipped):
        if not isinstance(item, dict):
            skipped["invalid"] += 1
            continue
        if reason := _gate(section, item):
            skipped[reason] += 1
            continue
        key = item.get("key")
        if not isinstance(key, str) or key not in _AREAS or key in plan.quests:
            skipped["invalid"] += 1
            continue
        if item.get("quest") is None:
            continue  # 퀘스트가 없는 영역은 가져올 것이 없다(틀린 것이 아니다)
        try:
            plan.quests[key] = _text(item, "quest", max_len=MAX_QUEST)
        except _Invalid:
            skipped["invalid"] += 1

    for q in _items(seed, "questions", skipped):
        if isinstance(q, str) and q.strip():
            plan.questions.append(q)
        else:
            skipped["invalid"] += 1
    return plan


def apply_seed(conn: sqlite3.Connection, plan: SeedPlan, clock: Clock) -> dict[str, int]:
    """한 트랜잭션. 모두 `confirmed`/`seed`. 높은 때·전환점마다 칭호(경험치 없음). 끝에 `life_seed_imported_at`."""
    curve = CurveRepo(conn, clock)
    status = StatusRepo(conn, clock)
    now = clock.now()
    titles = 0
    with transaction(conn):
        ids: dict[str, int] = {}
        for c in plan.chapters:
            row = curve.add_chapter(
                title=c.title, start_month=c.start_month, end_month=c.end_month, status="confirmed", origin="seed",
                theme=c.theme, sketch=plan.sketches.get(c.seed_key), certainty=c.certainty, seed_key=c.seed_key,
                source_ref=c.source_ref, ladder_remembered=c.ladder,
            )
            ids[c.seed_key] = row.id
        for e in plan.events:
            m = curve.add_milestone(
                date_text=e.date_text, kind=e.kind, title=e.title, note=e.note, status="confirmed", origin="seed",
                chapter_id=ids.get(e.chapter_key) if e.chapter_key else None, sensitive=e.sensitive,
                certainty=e.certainty, kind_certainty=e.kind_certainty, source_ref=e.source_ref, area=e.area,
            )
            if m.kind in ("high", "turning_point") and status.add_title(m.id, now):
                titles += 1
        for area, quest in plan.quests.items():
            curve.set_area_default(area, quest)
        for q in plan.questions:
            curve.add_question(q)
        StateRepo(conn, clock).set(IMPORTED_AT_KEY, to_iso(now))
    return {
        "chapters": len(plan.chapters), "events": len(plan.events), "quests": len(plan.quests),
        "questions": len(plan.questions), "titles": titles,
    }


def _imported(conn: sqlite3.Connection) -> bool:
    row = conn.execute("SELECT value FROM app_state WHERE key = ?", (IMPORTED_AT_KEY,)).fetchone()
    return row is not None and row[0] is not None


def summary_lines(plan: SeedPlan) -> list[str]:
    """개수만(12장). 항목 내용은 넣지 않는다."""
    s = plan.skipped
    return [
        (f"가져올 것: 챕터 {len(plan.chapters)}, 사건 {len(plan.events)}, 영역 퀘스트 {len(plan.quests)}, "
         f"질문 {len(plan.questions)}"),
        (f"건너뛸 것: {sum(s[r] for r in SKIP_REASONS)} (sensitive_unconfirmed {s['sensitive_unconfirmed']}, "
         f"storage_unconfirmed {s['storage_unconfirmed']}, invalid {s['invalid']})"),
    ]


def run_seed_life(
    root: Path | str,
    file: Path | str,
    *,
    dry_run: bool,
    out: TextIO | None = None,
    lock_factory: Callable[[Path], AbstractContextManager[Any]] = SingleInstanceLock,
    clock: Clock | None = None,
) -> int:
    """잠금 → 파일 → 검토 표시 → 이미 가져옴 → 계획 → (`--dry-run`이 아니면) 쓰기와 `chapters.md` 내보내기."""
    out = out if out is not None else sys.stdout
    clock = clock or SystemClock()
    paths = PathsConfig.for_root(Path(root))

    def say(line: str) -> None:
        print(line, file=out)

    with ExitStack() as stack:
        try:
            stack.enter_context(lock_factory(paths.state_dir / LOCK_FILE))
        except AlreadyRunning:
            say(RUNNING_MESSAGE)
            return EXIT_RUNNING
        try:
            seed = load_seed(file)
        except SeedFileError:
            say(BAD_FILE_MESSAGE)
            return EXIT_BAD_FILE
        if not is_reviewed(seed):
            say(NOT_REVIEWED_MESSAGE)
            return EXIT_NOT_REVIEWED
        db_path = paths.state_dir / DB_FILE
        if dry_run:  # --dry-run은 DB도 만들지 않는다: 있으면 읽기 전용으로 "이미 가져옴"만 본다
            if db_path.exists():
                ro = open_ro(db_path)
                try:
                    already = _imported(ro)
                finally:
                    ro.close()
                if already:
                    say(ALREADY_MESSAGE)
                    return EXIT_ALREADY
            plan = plan_import(seed)
            for line in summary_lines(plan):
                say(line)
            say(DRY_RUN_MESSAGE)
            return EXIT_OK
        conn = open_db(db_path)
        try:
            migrate(conn)
            if _imported(conn):
                say(ALREADY_MESSAGE)
                return EXIT_ALREADY
            plan = plan_import(seed)
            for line in summary_lines(plan):
                say(line)
            try:
                apply_seed(conn, plan, clock)
            except sqlite3.Error:
                # 계획을 지나 DB 제약에 걸렸다: 한 트랜잭션이라 모두 되돌려졌다. 예외 글은 내지 않는다
                say(DB_REJECTED_MESSAGE)
                return EXIT_BAD_FILE
            try:
                export_curve(CurveRepo(conn, clock), paths.data_dir / "curve" / "chapters.md")
            except OSError:
                pass  # 내보내기는 다음 변경 때 다시 만든다(5.4). DB는 이미 커밋됐다
            say(DONE_MESSAGE)
            return EXIT_OK
        finally:
            conn.close()
    return EXIT_BAD_FILE  # pragma: no cover (ExitStack가 예외를 삼키지 않는다)


# --- `--update-history` (SP8 8.1) ---


@dataclass
class HistoryPlan:
    milestone_areas: dict[int, str] = field(default_factory=dict)  # 사건 id → 영역(지금 `area IS NULL`인 것만)
    chapter_ladders: dict[int, int] = field(default_factory=dict)  # 챕터 id → 기억한 사다리(지금 NULL인 것만)
    skipped: Counter[SkipReason] = field(default_factory=Counter)


def _valid_items(
    seed: dict[str, Any], section: str, skipped: Counter[SkipReason], parse: Callable[[dict[str, Any]], Any],
) -> list[Any]:
    """`plan_import`와 같은 확인 규칙(필수 키 → 민감·`storage`는 `confirmed: true`) → 값 검사. 건너뛴 것은 센다."""
    out = []
    for item in _items(seed, section, skipped):
        if not isinstance(item, dict):
            skipped["invalid"] += 1
            continue
        if reason := _gate(section, item):
            skipped[reason] += 1
            continue
        try:
            out.append(parse(item))
        except _Invalid:
            skipped["invalid"] += 1
    return out


def plan_history_update(seed: dict[str, Any], curve: CurveRepo) -> HistoryPlan:
    """무엇을 채우고 무엇을 왜 건너뛰는지(쓰지 않는다). 챕터와 사건 묶음만 본다.

    - 챕터 `ladder`: `seed_key`로 찾고 DB 칸이 NULL일 때만.
    - 사건 `area`: `origin = 'seed'`이고 `area IS NULL`인 사건을 `date_text`와 `title`이 같은 시드 항목으로 찾는다.
      같은 `date + title`이 시드에 둘 이상이거나 DB에 둘 이상이면 그 항목은 `ambiguous`.
    - DB에서 짝을 찾지 못하거나 이미 값이 있는 칸은 채울 것이 없을 뿐 건너뜀으로 세지 않는다.
    """
    plan = HistoryPlan()
    skipped = plan.skipped

    chapters: list[SeedChapter] = _valid_items(seed, "chapters", skipped, _chapter)
    keys = Counter(c.seed_key for c in chapters)
    for c in chapters:
        if keys[c.seed_key] > 1:
            skipped["invalid"] += 1  # seed_key는 UNIQUE(가져오기와 같다)
            continue
        if c.ladder is None:
            continue
        row = curve.chapter_by_seed_key(c.seed_key)
        if row is not None and row.ladder_remembered is None:
            plan.chapter_ladders[row.id] = c.ladder

    events: list[SeedEvent] = _valid_items(seed, "events", skipped, lambda item: _event(item, set()))
    in_seed = Counter((e.date_text, e.title) for e in events)
    in_db: dict[tuple[str, str], list[Any]] = {}
    for m in curve.seed_milestones():
        in_db.setdefault((m.date_text, m.title), []).append(m)
    for e in events:
        if e.area is None:
            continue
        key = (e.date_text, e.title)
        found = in_db.get(key, [])
        if in_seed[key] > 1 or len(found) > 1:
            skipped["ambiguous"] += 1
            continue
        if found and found[0].area is None:
            plan.milestone_areas[found[0].id] = e.area
    return plan


def history_lines(plan: HistoryPlan) -> list[str]:
    """개수만(SP8 부록 A 시드 명령). 항목 내용은 넣지 않는다."""
    s = plan.skipped
    return [
        f"채울 것: 사건 영역 {len(plan.milestone_areas)}, 챕터 사다리 {len(plan.chapter_ladders)}",
        (f"건너뛸 것: {sum(s[r] for r in HISTORY_SKIP_REASONS)} (sensitive_unconfirmed {s['sensitive_unconfirmed']}, "
         f"storage_unconfirmed {s['storage_unconfirmed']}, invalid {s['invalid']}, ambiguous {s['ambiguous']})"),
    ]


def run_update_history(
    root: Path | str,
    file: Path | str,
    *,
    dry_run: bool,
    out: TextIO | None = None,
    lock_factory: Callable[[Path], AbstractContextManager[Any]] = SingleInstanceLock,
    clock: Clock | None = None,
) -> int:
    """잠금(3) → 파일(6) → 검토 표시(5) → 시드를 가져오지 않음(7) → 이미 채움(4) → 계획 출력 → 쓰기와 표시."""
    out = out if out is not None else sys.stdout
    clock = clock or SystemClock()
    paths = PathsConfig.for_root(Path(root))

    def say(line: str) -> None:
        print(line, file=out)

    with ExitStack() as stack:
        try:
            stack.enter_context(lock_factory(paths.state_dir / LOCK_FILE))
        except AlreadyRunning:
            say(RUNNING_MESSAGE)
            return EXIT_RUNNING
        try:
            seed = load_seed(file)
        except SeedFileError:
            say(BAD_FILE_MESSAGE)
            return EXIT_BAD_FILE
        if not is_reviewed(seed):
            say(NOT_REVIEWED_MESSAGE)
            return EXIT_NOT_REVIEWED
        db_path = paths.state_dir / DB_FILE
        if not db_path.exists():  # DB가 없으면 가져온 시드도 없다. DB를 새로 만들지 않는다
            say(NOT_IMPORTED_MESSAGE)
            return EXIT_NOT_IMPORTED
        conn = open_ro(db_path) if dry_run else open_db(db_path)
        try:
            if not dry_run:
                migrate(conn)
            if not _imported(conn):
                say(NOT_IMPORTED_MESSAGE)
                return EXIT_NOT_IMPORTED
            row = conn.execute("SELECT value FROM app_state WHERE key = ?", (HISTORY_UPDATED_AT_KEY,)).fetchone()
            if row is not None and row[0] is not None:
                say(HISTORY_ALREADY_MESSAGE)
                return EXIT_ALREADY
            curve = CurveRepo(conn, clock)
            plan = plan_history_update(seed, curve)
            for line in history_lines(plan):
                say(line)
            if dry_run:
                say(DRY_RUN_MESSAGE)
                return EXIT_OK
            try:
                with transaction(conn):
                    curve.fill_history(plan.milestone_areas, plan.chapter_ladders)
                    StateRepo(conn, clock).set(HISTORY_UPDATED_AT_KEY, to_iso(clock.now()))
            except sqlite3.Error:
                say(DB_REJECTED_MESSAGE)  # 한 트랜잭션이라 모두 되돌려졌다. 예외 글은 내지 않는다
                return EXIT_BAD_FILE
            return EXIT_OK
        finally:
            conn.close()
    return EXIT_BAD_FILE  # pragma: no cover (ExitStack가 예외를 삼키지 않는다)
