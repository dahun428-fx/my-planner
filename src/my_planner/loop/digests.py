"""일정 정리 알림 판정 (SP9b 스펙 1~4장, ADR 0015 덧붙임): 1분 tick이 일정 알림 바로 다음에 두뇌 없이 부른다.

- 아침 알림(`morning`)은 오늘 일정, 밤 알림(`night`)은 내일 일정을 하루 한 번 모아 보낸다. 기억 카드를 만드는
  정리 루프(`consolidation`)와 다르다.
- `judge_digests`(동기)가 종류마다 슬롯(어제, 오늘)을 판정하고 `app_state.digest_last`를 **먼저** 적는다(보내는 도중에
  죽어도 두 번 보내지 않는다). 보낼 것만 `PendingDigest`로 돌려준다.
- `send_digests`(비동기)가 주 통로로 보낸다. 적을 행이 없으니 끝내 못 보내면 로그 `digest_failed`만 남긴다.
- 멈춤 중에도 보내고 어떤 하루 상한(`daily_proactive_messages`, `daily_event_reminders`)에도 세지 않는다(종류마다
  하루 한 번). 로그에는 종류, 날짜, 개수만 남긴다(제목은 남기지 않는다).
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta, tzinfo
from typing import TYPE_CHECKING, Any, Literal
from zoneinfo import ZoneInfo

from my_planner.clock import local, logical_date
from my_planner.loop.reminders import RESUME_GAP, RETRY_DELAYS_S, TTL_MAX_S, TTL_MIN_S

if TYPE_CHECKING:
    from my_planner.config import DigestConfig
    from my_planner.harness.delivery import Delivery
    from my_planner.store.repos.events import EventsRepo, Occurrence
    from my_planner.store.repos.state import StateRepo

log = logging.getLogger(__name__)

DigestKind = Literal["morning", "night"]
DIGEST_KINDS: tuple[DigestKind, ...] = ("morning", "night")
# 고를 수 있는 시각(포함). 아침은 논리적 날짜 경계부터, 밤은 자정 전까지: 보내는 날의 달력 날짜가 "오늘"과 같다
RANGES: dict[DigestKind, tuple[time, time]] = {"morning": (time(4, 0), time(11, 50)), "night": (time(18, 0), time(23, 50))}
STEP_MIN = 10  # 체크인 시간 선택기와 같은 10분 단위
DIGEST_LATE_MAX = timedelta(hours=2)  # 깨어났을 때 이만큼 늦은 것까지는 늦게 보낸다(포함). 넘으면 안 보낸다
TITLE_MAX_CHARS = 20  # 줄마다 일정 제목을 이 길이에서 자르고 "…"를 붙인다
SHOW_LINES = 3  # 보이는 일정 줄. 더 있으면 넷째 줄에 "외 {k}개"

Outcome = Literal["sent", "late", "too_late", "empty"]
_HHMM = re.compile(r"^([01][0-9]|2[0-3]):([0-5][0-9])$")


@dataclass(frozen=True)
class DigestSetting:
    on: bool
    time: time


@dataclass(frozen=True)
class PendingDigest:
    """보낼 일정 정리 알림 하나. `date`는 담은 날, `until`(UTC)은 판정한 시각의 논리적 날짜 끝(다음 경계).
    재시도와 푸시 보관 시간이 `until`까지다."""

    kind: DigestKind
    date: date
    title: str
    body: str
    url: str
    until: datetime


def validate_digest_time(kind: DigestKind, v: Any) -> time | None:
    """`HH:MM` 문자열(또는 `time`)이 그 종류의 범위 안 10분 단위면 그 시각, 아니면 None(모르는 종류도 None)."""
    if kind not in RANGES:
        return None
    if isinstance(v, str):
        m = _HHMM.match(v)
        if m is None:
            return None
        t = time(int(m.group(1)), int(m.group(2)))
    elif isinstance(v, time):
        if v.second or v.microsecond or v.tzinfo is not None:
            return None
        t = v
    else:
        return None
    lo, hi = RANGES[kind]
    return t if lo <= t <= hi and t.minute % STEP_MIN == 0 else None


def default_digest_settings(defaults: DigestConfig) -> dict[DigestKind, DigestSetting]:
    return {
        "morning": DigestSetting(defaults.morning_on, defaults.morning),
        "night": DigestSetting(defaults.night_on, defaults.night),
    }


def parse_digest_settings(raw: str | None, defaults: DigestConfig) -> dict[DigestKind, DigestSetting]:
    """`app_state.digest_settings`(JSON) 해석. 없거나 깨진 JSON, 잘못된 칸, 범위 밖 시각은 칸마다 config 값(예외 없음).
    `StateRepo.get_digest_settings`와 `wake_times.load_digest_settings`가 함께 쓴다."""
    out = default_digest_settings(defaults)
    try:
        data = json.loads(raw) if raw else None
    except ValueError:
        return out
    if not isinstance(data, dict):
        return out
    for kind in DIGEST_KINDS:
        slot = data.get(kind)
        if not isinstance(slot, dict):
            continue
        on = slot.get("on")
        t = validate_digest_time(kind, slot.get("time"))
        out[kind] = DigestSetting(on if isinstance(on, bool) else out[kind].on, t or out[kind].time)
    return out


def dump_digest_settings(settings: dict[DigestKind, DigestSetting]) -> str:
    return json.dumps({k: {"on": s.on, "time": f"{s.time:%H:%M}"} for k, s in settings.items()}, ensure_ascii=False)


def _cut(title: str) -> str:
    return title if len(title) <= TITLE_MAX_CHARS else title[:TITLE_MAX_CHARS] + "…"


def _items(day: date, occs: list[Occurrence], *, now: datetime, late: bool) -> list[Occurrence]:
    """담을 그날 일정: `day`의 것(건너뛴 회 빼고), 하루 종일 먼저, 시작 순. 늦게 보내면 시작이 지난 시각 일정은 뺀다."""
    got = [o for o in occs if o.date == day and not o.skipped]
    if late:
        got = [o for o in got if o.all_day or (o.start is not None and o.start > now)]
    return sorted(got, key=lambda o: (not o.all_day, o.start or now, o.event_id))


def _format(kind: DigestKind, items: list[Occurrence], tz: str | tzinfo) -> tuple[str, str]:
    lines = [
        f"하루 종일 {_cut(o.title)}" if o.all_day else f"{local(o.start, tz):%H:%M} {_cut(o.title)}"  # type: ignore[arg-type]
        for o in items[:SHOW_LINES]
    ]
    if len(items) > SHOW_LINES:
        lines.append(f"외 {len(items) - SHOW_LINES}개")
    return f"{'오늘' if kind == 'morning' else '내일'} 일정 {len(items)}개", "\n".join(lines)


def digest_text(
    kind: DigestKind, day: date, occs: list[Occurrence], *, now: datetime, late: bool, tz: str | tzinfo
) -> tuple[str, str] | None:
    """(제목, 본문) (2장). 그날 일정을 `{HH:MM} {제목}`(하루 종일은 `하루 종일 {제목}`) 줄로 세 줄까지, 더 있으면
    `외 {k}개`. 늦게 보내면 시작이 지난 시각 일정은 뺀다(하루 종일은 남긴다). 담을 것이 없으면 None.
    제목의 `{n}`은 담은 개수(뺀 것은 세지 않는다)."""
    items = _items(day, occs, now=now, late=late)
    return _format(kind, items, tz) if items else None


def judge_digests(
    *,
    last_seen_at: datetime,
    now: datetime,
    settings: dict[DigestKind, DigestSetting],
    events: EventsRepo,
    state: StateRepo,
    tz: str,
    day_boundary: time,
) -> list[PendingDigest]:
    """`(last_seen_at, now]`에 든 슬롯을 판정해 `digest_last`를 적고, 보낼 것을 돌려준다(동기, 3장).

    종류 k, 달력 날짜 x의 슬롯은 x + k의 시각(현지). 지금의 현지 날짜 d에 대해 x = d - 1, d를 이 순서로 본다(밤 23:00
    슬롯을 자정 뒤에 깨어나 늦게 보낼 때 d - 1이다). 그 종류의 `digest_last`가 x 이상이면 이미 판정했다.
    공백 ≤ 3분이면 보내고(`sent`), 깨어났고 2시간 이내면 늦게 보내고(`late`), 넘으면 안 보낸다(`too_late`, 놓친 알림
    카드도 없다). 담을 일정이 없으면 `empty`. 결과와 상관없이 `digest_last`는 x로 적는다. 꺼진 종류는 건너뛴다.
    """
    if last_seen_at >= now:  # 시계가 뒤로 갔거나 같은 시각: 판정할 공백이 없다
        return []
    zone = ZoneInfo(tz)
    wake = now - last_seen_at > RESUME_GAP
    d = local(now, zone).date()
    # 보내는 시각(판정한 now)의 논리적 날짜 끝: 재시도와 푸시 보관 시간이 여기까지
    until = datetime.combine(logical_date(now, zone, day_boundary) + timedelta(days=1), day_boundary, zone).astimezone(UTC)
    last = state.get_digest_last()
    pending: list[PendingDigest] = []
    for kind in DIGEST_KINDS:
        s = settings[kind]
        if not s.on:
            continue
        for x in (d - timedelta(days=1), d):
            at = datetime.combine(x, s.time, zone).astimezone(UTC)
            if not (last_seen_at < at <= now):
                continue
            done = last[kind]
            if done is not None and done >= x:
                continue
            state.set_digest_last(kind, x)  # 보내기 전에 적는다
            last[kind] = x
            day = x if kind == "morning" else x + timedelta(days=1)
            outcome: Outcome
            items: list[Occurrence] = []
            if wake and now - at > DIGEST_LATE_MAX:
                outcome = "too_late"
            else:
                items = _items(day, events.occurrences(day, day), now=now, late=wake)
                outcome = ("late" if wake else "sent") if items else "empty"
            if items:
                title, body = _format(kind, items, zone)
                pending.append(PendingDigest(kind, day, title, body, f"/schedule/?date={day.isoformat()}", until))
            log.info("digest_judged", extra={"kind": kind, "date": day.isoformat(), "count": len(items), "outcome": outcome})
    return pending


def _ttl(p: PendingDigest, now: datetime) -> int:
    """푸시 보관 시간: `until`까지 남은 시간(1시간~하루, 일정 알림과 같은 범위)."""
    return max(TTL_MIN_S, min(TTL_MAX_S, int((p.until - now).total_seconds())))


async def _send_one(
    p: PendingDigest, delivery: Delivery, sleep: Callable[[float], Awaitable[None]], delays: tuple[float, ...]
) -> None:
    extra: dict[str, Any] = {"kind": p.kind, "date": p.date.isoformat()}
    # 취소(종료 중)는 그대로 올린다: 적을 행이 없다
    for attempt in range(len(delays) + 1):
        if attempt:
            await sleep(delays[attempt - 1])
            if delivery.clock.now() >= p.until:  # 논리적 날짜가 끝나면 다시 보내지 않는다
                break
        try:
            channel = await delivery.deliver_digest(
                p.kind, p.date, p.title, p.body, p.url, ttl_s=_ttl(p, delivery.clock.now())
            )
        except Exception as e:  # noqa: BLE001 - 한 종류가 안 가도 나머지는 보낸다
            log.warning("digest_send_error", extra={**extra, "error_type": type(e).__name__})
            channel = None
        if channel is not None:
            return
        log.warning("digest_attempt_failed", extra={**extra, "attempt": attempt + 1})
    log.warning("digest_failed", extra=extra)


async def send_digests(
    pending: list[PendingDigest],
    delivery: Delivery,
    *,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    delays: tuple[float, ...] = RETRY_DELAYS_S,
) -> None:
    """주 통로로 보낸다(텔레그램 대체 포함). 못 보내면 20초·60초 뒤에 다시 해 보되 `until`이 지나면 하지 않고, 끝내 안
    되면 로그 `digest_failed`만 남긴다. 종류마다 따로 기다린다."""
    await asyncio.gather(*(_send_one(p, delivery, sleep, delays) for p in pending))
