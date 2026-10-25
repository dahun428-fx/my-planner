"""일정 알림 판정 (SP9 스펙 5.3, ADR 0015): 1분 tick이 두뇌 없이 부른다.

- `remind_events`(동기)가 `remind_at`이 공백 안에 든 그날 일정을 R1~R5로 판정하고 `event_reminders` 행을 **먼저** 적는다
  (보내는 도중에 죽어도 같은 날 두 번 보내지 않는다). 보낼 것(`sent`·`late_sent`)만 `PendingReminder`로 돌려준다.
- `send_reminders`(비동기)가 주 통로로 보내고, 못 보냈으면 그 행을 `failed`로 고친다.
- 멈춤 중에도 보내고 `daily_proactive_messages`에 세지 않는다(그 상한은 비서가 먼저 거는 말의 것). 대신 하루 상한은
  `limits.daily_event_reminders`. 로그에는 일정 번호와 개수만 남긴다(제목은 남기지 않는다).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta, tzinfo
from typing import TYPE_CHECKING, Literal

from my_planner.clock import local

if TYPE_CHECKING:
    from my_planner.config import LimitsConfig
    from my_planner.harness.delivery import Delivery
    from my_planner.store.repos.events import EventsRepo, Occurrence

log = logging.getLogger(__name__)

RESUME_GAP = timedelta(minutes=3)  # 직전 tick과 이보다 멀면 절전에서 깨어난 것(공백 == 3분은 아님). 러너가 같이 쓴다
LOOKBACK = timedelta(days=7)  # 거슬러 보는 범위: 이보다 앞의 `remind_at`은 판정도 기록도 하지 않는다
LATE_MAX = 3  # 한 번에 보내는 늦은 알림
DEFAULT_TZ = "Asia/Seoul"

Outcome = Literal["sent", "late_sent", "missed", "failed", "skipped"]


@dataclass(frozen=True)
class ReminderOutcome:
    event_id: int
    date: date
    outcome: Outcome


@dataclass(frozen=True)
class PendingReminder:
    """보낼 알림 하나. `outcome.outcome`은 `sent` 또는 `late_sent`, 푸시 데이터 `url`은 `/schedule/?date=YYYY-MM-DD`."""

    outcome: ReminderOutcome
    title: str
    body: str
    url: str


def reminder_text(occ: Occurrence, now: datetime, late: bool, *, tz: str | tzinfo = DEFAULT_TZ) -> tuple[str, str]:
    """(제목, 본문) (5.3). 본문 `{HH:MM} ({남은 말})`: 정시 "지금이에요", 10/30/60분 "{n}분 뒤", 하루 전 "내일",
    늦게 보냄 "{n}분 남았어요"(60분 이상이면 "{h}시간 남았어요", 내림). 하루 종일은 `하루 종일 (오늘|내일)`."""
    if occ.all_day:
        return occ.title, f"하루 종일 ({'내일' if occ.remind_min == 1440 else '오늘'})"
    assert occ.start is not None
    when = f"{local(occ.start, tz):%H:%M}"
    if late:
        left = max(1, int((occ.start - now).total_seconds() // 60))
        word = f"{left // 60}시간 남았어요" if left >= 60 else f"{left}분 남았어요"
    elif occ.remind_min == 0:
        word = "지금이에요"
    elif occ.remind_min == 1440:
        word = "내일"
    else:
        word = f"{occ.remind_min}분 뒤"
    return occ.title, f"{when} ({word})"


def _over(occ: Occurrence, now: datetime, tz: tzinfo) -> bool:
    """그날 일정의 시작이 지났나(하루 종일은 그날이 지났나)."""
    if occ.all_day:
        return local(now, tz).date() > occ.date
    assert occ.start is not None
    return occ.start <= now


def remind_events(
    *, last_seen_at: datetime, now: datetime, events: EventsRepo, limits: LimitsConfig
) -> list[PendingReminder]:
    """`remind_at ∈ (last_seen_at, now]`인 그날 일정을 판정해 행을 적고, 보낼 것을 돌려준다(동기).

    R1 공백 ≤ 3분: `sent`. R2 깨어남이고 아직 시작 전: `late_sent`(가장 가까운 시작 순 최대 3개). R3 깨어남이고
    시작이 지남: `missed`. R5 늦은 알림이 3개를 넘거나 하루 상한을 넘음: `skipped`. 보내기 실패(R4)는
    `send_reminders`가 `failed`로 고친다. 대상은 `remind_at > events.updated_at`인 것만(만들거나 바꾸기 전 시각은 안 보냄).
    """
    if last_seen_at >= now:  # 시계가 뒤로 갔거나 같은 시각: 판정할 공백이 없다
        return []
    wake = now - last_seen_at > RESUME_GAP
    lo = max(last_seen_at, now - LOOKBACK)
    tz = events.tz
    # 하루 전 알림(1440)의 그날은 내일이다: 범위 끝을 하루 늘린다
    first, last = local(lo, tz).date() - timedelta(days=1), local(now, tz).date() + timedelta(days=1)
    decided = events.decided_reminders(first, last)
    updated: dict[int, datetime] = {}
    due: list[Occurrence] = []
    for o in events.occurrences(first, last):
        if o.remind_at is None or not (lo < o.remind_at <= now) or (o.event_id, o.date) in decided:
            continue
        if o.event_id not in updated:
            e = events.get(o.event_id)
            updated[o.event_id] = e.updated_at if e is not None else now
        if o.remind_at > updated[o.event_id]:
            due.append(o)
    if not due:
        return []
    day_start = datetime.combine(local(now, tz).date(), time(0, 0), tz).astimezone(UTC)
    room = max(0, limits.daily_event_reminders - events.reminders_attempted_since(day_start))
    pending: list[PendingReminder] = []

    def decide(o: Occurrence, outcome: Outcome, late: bool = False) -> None:
        assert o.remind_at is not None
        events.record_reminder(o.event_id, o.date, o.remind_at, outcome, now)
        if outcome in ("sent", "late_sent"):
            title, body = reminder_text(o, now, late, tz=tz)
            pending.append(
                PendingReminder(ReminderOutcome(o.event_id, o.date, outcome), title, body, f"/schedule/?date={o.date.isoformat()}")
            )

    late: list[Occurrence] = []
    for o in sorted(due, key=lambda x: (x.remind_at or now, x.event_id)):
        if not wake:
            if room > 0:
                room -= 1
                decide(o, "sent")
            else:
                decide(o, "skipped")
        elif _over(o, now, tz):
            decide(o, "missed")
        else:
            late.append(o)
    # 가장 가까운 시작 순. 하루 종일은 그날 0시 시작으로 본다
    late.sort(key=lambda x: (x.start or datetime.combine(x.date, time(0, 0), tz).astimezone(UTC), x.event_id))
    for i, o in enumerate(late):
        if i < LATE_MAX and room > 0:
            room -= 1
            decide(o, "late_sent", late=True)
        else:
            decide(o, "skipped")
    log.info("reminders_judged", extra={"sent": len(pending), "due": len(due), "wake": wake})
    return pending


async def send_reminders(pending: list[PendingReminder], delivery: Delivery, events: EventsRepo) -> None:
    """주 통로로 보낸다(텔레그램 대체 포함). 어디에도 못 보냈으면 그 행을 `failed`로 고친다(R4)."""
    for p in pending:
        try:
            channel = await delivery.deliver_reminder(p.title, p.body, p.url)
        except Exception as e:  # noqa: BLE001 - 한 알림이 안 가도 나머지는 보낸다
            log.warning("reminder_send_error", extra={"event_id": p.outcome.event_id, "error_type": type(e).__name__})
            channel = None
        if channel is None:
            events.mark_reminder_failed(p.outcome.event_id, p.outcome.date)
            log.warning("reminder_failed", extra={"event_id": p.outcome.event_id})
