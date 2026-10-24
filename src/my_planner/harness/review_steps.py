"""회고 단계: 월말 사다리, 분기 영역 점수, 연말 돌아보기 (SP3-4 스펙 11.1~11.2, 부록 A).

새 회차 종류를 만들지 않는다. `review(week)` 회차 `scheduled_for`의 논리적 날짜(R1로 넘겨 받은 회고도 원래 날짜)가
그 달의 마지막 일요일이면 사다리, 분기 마지막 달이면 + 영역 점수, 12월이면 + 올해 돌아보기를 차례로 묻는다.

하네스가 묻는 첫 단계(`first_step`: 사다리 1단계, 사다리를 묻지 않으면 영역 점수)는 회차마다 한 번이다
(`app_state.ladder_prompted_run_id`, 계획 빈 곳 12). 붙는 자리는 세 곳 가운데 처음 오는 곳이다.
(a) 회고 묶음의 컨디션 누름(토스트 대신 새 메시지), (b) 컨디션 버튼 없이 회고 대화에 들어온 첫 사용자 글의 답,
(c) 그 날짜 컨디션이 이미 있어 컨디션 줄이 없는 회고 메시지. 그 달 사다리 `now`가 이미 있으면 사다리를 묻지 않는다
(계획 빈 곳 14). 답장 창이 끝나면 남은 단계는 묻지 않는다(누름은 기록만).

이 모듈의 메시지는 사용자 행동에 대한 답이라 하루 3회 상한에 세지 않는다. 로그에는 본문과 점수를 남기지 않는다.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Literal

from my_planner.clock import Clock, logical_date, period_of
from my_planner.domain import Area, Cadence, LoopKey, RunStatus
from my_planner.status.xp import AREA_LABELS

if TYPE_CHECKING:
    from my_planner.config import Settings
    from my_planner.store.repos.curve import CurveRepo
    from my_planner.store.repos.runs import Run, RunsRepo
    from my_planner.store.repos.state import StateRepo
    from my_planner.store.transcripts import TranscriptStore

log = logging.getLogger(__name__)

LadderField = Literal["n", "f"]

LADDER_PROMPTED_KEY = "ladder_prompted_run_id"  # 첫 단계를 이미 물은 회차(primary). 회차마다 한 번

# 부록 A (Dahun 확인 필요)
LADDER_STEP1 = "이번 달, 가능한 최고의 삶을 10, 최악을 0이라고 하면 지금은 몇 칸인가요?"
LADDER_STEP2 = "5년 뒤에는 몇 칸일 것 같아요?"
AREA_EXAMPLE = "예: 커리어 7 경제 5 건강 6 관계 8 배움 7 삶의 질 6"

STEP_PROMPTS = ("review_month.md", "review_quarter.md", "review_year.md")

@dataclass(frozen=True)
class ReviewSteps:
    """그 회고에 더하는 단계. 분기는 월말을, 연말은 분기를 품는다."""

    month: bool = False
    quarter: bool = False
    year: bool = False

    def __bool__(self) -> bool:
        return self.month

    def prompt_files(self) -> list[str]:
        """`review_week.md` 뒤에 차례로 붙일 지시문."""
        return [f for f, on in zip(STEP_PROMPTS, (self.month, self.quarter, self.year), strict=True) if on]

    def included_line(self, d: date) -> str | None:
        """회고 파일 머리글 아래 한 줄(11.1 "회고 파일"): `포함: 월간(2026-12), 분기(2026-Q4), 연간(2026)`."""
        if not self.month:
            return None
        parts = [f"월간({period_of(Cadence.month, d)})"]
        if self.quarter:
            parts.append(f"분기({period_of(Cadence.quarter, d)})")
        if self.year:
            parts.append(f"연간({period_of(Cadence.year, d)})")
        return "포함: " + ", ".join(parts)


def review_steps(d: date) -> ReviewSteps:
    """회고 날짜(논리적 날짜) `d`의 단계. 그 달의 마지막 일요일만 월말이다(11/29는 월말, 11/22는 아니다)."""
    last_sunday = d.weekday() == 6 and (d + timedelta(days=7)).month != d.month
    if not last_sunday:
        return ReviewSteps()
    return ReviewSteps(month=True, quarter=d.month in (3, 6, 9, 12), year=d.month == 12)


def ladder_recorded(now: int | None, future: int | None) -> str:
    """부록 A "사다리 기록": `기록했어요: 지금 6, 5년 뒤 8`. 건너뛰면 `기록했어요: 지금 6`."""
    bits = [f"지금 {now}" if now is not None else None, f"5년 뒤 {future}" if future is not None else None]
    shown = ", ".join(b for b in bits if b is not None)
    return f"기록했어요: {shown}" if shown else "기록했어요."


def area_scores_ask(previous: dict[str, int]) -> str:
    """부록 A "영역 점수 묻기". 지난 분기 점수가 없으면 `지난 분기: …` 문장을 뺀다. 영역은 SP1 순서."""
    head = "이번 분기 영역 점수도 여쭤볼게요. 1~10으로 답해 주세요."
    line = " · ".join(f"{AREA_LABELS[a.value]} {previous[a.value]}" for a in Area if a.value in previous)
    return f"{head} 지난 분기: {line}. {AREA_EXAMPLE}" if line else f"{head} {AREA_EXAMPLE}"


def prev_quarter(period: str) -> str:
    year, q = int(period[:4]), int(period[-1])
    return f"{year - 1}-Q4" if q == 1 else f"{year}-Q{q - 1}"


@dataclass(frozen=True)
class NextStep:
    """하네스가 보내는 단계 하나: 글과(있으면) 사다리 키보드 `(period, field)`."""

    text: str
    ladder: tuple[str, LadderField] | None = None
    conversation_id: int | None = None  # 원문 기록에 남길 회고 대화(보낼 때)


@dataclass(frozen=True)
class ReviewOf:
    """회차 묶음 안의 주간 회고와 그 단계."""

    review: Run
    day: date
    steps: ReviewSteps

    @property
    def month(self) -> str:
        return period_of(Cadence.month, self.day)

    @property
    def quarter(self) -> str:
        return period_of(Cadence.quarter, self.day)


def review_in(group: list[Run], settings: Settings) -> ReviewOf | None:
    """묶음(primary + 합친 회차)의 주간 회고. 판정은 그 회고 `scheduled_for`의 논리적 날짜(넘겨 받은 회고도 원래 날짜)."""
    review = next((r for r in group if r.loop is LoopKey.review), None)
    if review is None:
        return None
    d = logical_date(review.scheduled_for, settings.timezone, settings.day_boundary)
    return ReviewOf(review, d, review_steps(d))


def first_step(of: ReviewOf | None, curve: CurveRepo | None) -> NextStep | None:
    """하네스가 처음 묻는 단계: 그 달 사다리 `now`가 없으면 사다리 1단계, 아니면(분기 회고) 그 분기 영역 점수가
    없을 때 영역 점수 묻기. 둘 다 이미 있으면 None(묻지 않는다)."""
    if of is None or not of.steps or curve is None:
        return None
    ladder = curve.ladder(of.month)
    if ladder is None or ladder.now is None:
        return NextStep(LADDER_STEP1, (of.month, "n"))
    return area_step(of, curve)


def area_step(of: ReviewOf, curve: CurveRepo) -> NextStep | None:
    """분기 회고이고 그 분기 영역 점수가 아직 없으면 영역 점수 묻기(지난 분기 점수 함께)."""
    if not of.steps.quarter or curve.area_scores(of.quarter):
        return None
    return NextStep(area_scores_ask(previous_scores(of.quarter, curve)))


def previous_scores(period: str, curve: CurveRepo) -> dict[str, int]:
    return {s.area: s.score for s in curve.area_scores(prev_quarter(period))}


def step_note(step: NextStep | None, *, where: str) -> str:
    """두뇌에게 알리는 한 절: 하네스가 이 글 끝에 질문을 붙이니 따로 묻지 않는다."""
    if step is None:
        return ""
    return (
        "## 하네스가 붙이는 질문\n"
        f"이 {where} 끝에 하네스가 다음 질문을 붙입니다: {step.text}\n"
        f"이 {where}에는 따로 질문을 넣지 않습니다."
    )


class ReviewFlow:
    """회고 단계의 판정, 회차마다 한 번 표시(`app_state`, 디스패처 운영 상태), 단계 메시지 보내기.

    디스패처가 만들어 갖고, 텔레그램 버튼 처리기(`bot/callbacks.py`)가 같은 것을 쓴다. 점수 쓰기는 하지 않는다
    (즉시 갈래 `apply_action`의 `record_ladder_score`가 한다).
    """

    def __init__(
        self, *, runs: RunsRepo, state: StateRepo, curve: CurveRepo, settings: Settings, clock: Clock,
        send: Callable[[NextStep], Awaitable[object]], transcripts: TranscriptStore | None = None,
    ) -> None:
        self.runs = runs
        self.state = state
        self.curve = curve
        self.settings = settings
        self.clock = clock
        self._send = send
        self.transcripts = transcripts

    # --- 판정 ---

    def of_run(self, run: Run) -> ReviewOf | None:
        """회차(합쳐진 회차면 primary 기준) 묶음의 회고."""
        primary = self.runs.merged_into(run.id) or self.runs.get(run.id) or run  # 합친 기록은 DB의 지금 값
        group = [primary, *(r for i in primary.merged_run_ids if (r := self.runs.get(i)) is not None)]
        return review_in(group, self.settings)

    def claimed(self, run_id: int) -> bool:
        return self.state.get(LADDER_PROMPTED_KEY) == str(run_id)

    def claim(self, run_id: int) -> None:
        self.state.set(LADDER_PROMPTED_KEY, str(run_id))

    def pending_step(self, primary: Run) -> NextStep | None:
        """아직 묻지 않은 첫 단계(표시는 하지 않는다)."""
        if self.claimed(primary.id):
            return None
        return first_step(self.of_run(primary), self.curve)

    def _open(self, primary: Run, at: datetime) -> bool:
        from my_planner.harness.checkins import reply_until

        return (
            primary.status is RunStatus.done
            and at <= reply_until(primary, runs=self.runs, settings=self.settings)
        )

    def after_condition(self, run_id: int) -> NextStep | None:
        """(a) 회고 묶음 메시지의 컨디션 누름: 답장 창 안이고 아직 묻지 않았으면 첫 단계를 표시하고 돌려준다."""
        run = self.runs.get(run_id)
        if run is None:
            return None
        primary = self.runs.merged_into(run.id) or run
        if not self._open(primary, self.clock.now()):
            return None
        step = self.pending_step(primary)
        if step is None:
            return None
        self.claim(primary.id)
        log.info("review_step_prompted", extra={"run_id": primary.id, "where": "condition"})
        return replace(step, conversation_id=primary.conversation_id)

    def open_month_review(self, period: str) -> tuple[Run, ReviewOf] | None:
        """그 달(`YYYY-MM`)의 월말 회고 회차(primary)가 지금 답장 창 안이면 (primary, 회고)."""
        from my_planner.harness.checkins import open_checkins

        for primary in open_checkins(self.runs, self.clock.now(), self.settings):
            of = self.of_run(primary)
            if of is not None and of.steps and of.month == period:
                return primary, of
        return None

    def after_now(self, period: str) -> NextStep | None:
        """`지금`을 눌렀다: 그 달 월말 회고가 열려 있으면 2단계(`5년 뒤`) + `f` 키보드."""
        found = self.open_month_review(period)
        if found is None:
            return None
        return NextStep(LADDER_STEP2, (period, "f"), found[0].conversation_id)

    def after_future(self, period: str) -> NextStep | None:
        """`5년 뒤`를 누르거나 건너뛰었다: 열린 월말 회고면 "기록했어요: …"(분기 회고면 이어서 영역 점수 묻기)."""
        found = self.open_month_review(period)
        if found is None:
            return None
        primary, of = found
        text = self.recorded_copy(period)
        area = area_step(of, self.curve)
        return NextStep(f"{text}\n\n{area.text}" if area is not None else text, None, primary.conversation_id)

    def recorded_copy(self, period: str) -> str:
        """부록 A "사다리 기록"(그 달 지금 값으로)."""
        ladder = self.curve.ladder(period)
        return ladder_recorded(ladder.now if ladder else None, ladder.future if ladder else None)

    # --- 보내기 ---

    async def send(self, step: NextStep) -> bool:
        """단계 메시지를 텔레그램에 보낸다(하루 3회에 세지 않는다). 보냈으면 원문 기록에 비서 줄을 남긴다."""
        try:
            await self._send(step)
        except Exception as e:  # noqa: BLE001 - 본문 없이 종류만 남긴다
            log.warning("review_step_send_error", extra={"error_type": type(e).__name__})
            return False
        if self.transcripts is not None:
            try:
                self.transcripts.append(self.clock.now(), "비서", step.conversation_id, None, step.text)
            except Exception as e:  # noqa: BLE001
                log.warning("review_step_transcript_error", extra={"error_type": type(e).__name__})
        return True
