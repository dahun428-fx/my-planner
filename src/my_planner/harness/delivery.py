"""회차 전달: 주 통로, 웹 푸시, 텔레그램 대체 (SP3-4 스펙 7.3 D1~D8, 6.4.8).

- 실제 통로(D1a): 주 통로가 `app`이고, 푸시가 켜져 있고(VAPID), 켜진 구독이 하나라도 있으면 `app`. 아니면 `telegram`.
- `telegram`(D2): 텔레그램에 전체 메시지를 SP1처럼 보낸다. 푸시는 보내지 않는다.
- `app`(D3): 켜진 구독 모두에 6.4.8 페이로드를 보낸다. 하나라도 받으면 끝이고 텔레그램에는 보내지 않는다.
- 대체(D4): 어느 구독도 받지 못하면 텔레그램에 전체 메시지(`mode = fallback`). 구독마다 바로 3회(1초·2초 간격)
  보내 본다. 404/410은 다시 보내지 않고 끈다. 회차 하나의 시도가 끝내 안 되면 연속 실패 1이고, 연속 5번이면 끈다.
- 고정 안내(D8)도 실제 통로로 간다(`type: notice`). 안전 모드 안내는 이 모듈을 거치지 않는다(텔레그램만, `app.py`).

`pywebpush`는 동기 함수라 보내기는 `to_thread`(기본 `asyncio.to_thread`)로 하고, 구독 기록(`PushRepo`)은
돌아온 뒤 이벤트 루프 스레드에서 한다(쓰기 연결을 다른 스레드에서 만지지 않는다, 4.3).
구독 `endpoint`와 키는 로그에 넣지 않는다: 남기는 것은 구독 id, 상태 코드, 예외 종류뿐이다.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any, Literal, Protocol

from my_planner.domain import Channel, LoopKey
from my_planner.harness.dispatcher import (
    SEND_ATTEMPTS,
    SEND_RETRY_DELAYS_S,
    Outbound,
    Sender,
    send_run_telegram,
)
from my_planner.store.repos.state import NOTIFY_PRIMARY_KEY

if TYPE_CHECKING:
    from my_planner.clock import Clock
    from my_planner.config import Settings, VapidConfig
    from my_planner.store.repos.channels import DeliveriesRepo
    from my_planner.store.repos.push import PushRepo, PushSubscription
    from my_planner.store.repos.runs import Run
    from my_planner.store.repos.state import StateRepo

log = logging.getLogger(__name__)

# 푸시 제목(부록 A)
PUSH_TITLES: dict[LoopKey, str] = {
    LoopKey.morning_brief: "아침 브리핑",
    LoopKey.evening_checkin: "저녁 체크인",
    LoopKey.review: "주간 회고",
    LoopKey.return_: "다시 이어서",
}
NOTICE_TITLE = "알림"
PUSH_TEST_TEXT = "알림이 잘 오는지 시험으로 보냈어요."
BODY_MAX_CHARS = 120  # 본문 첫 줄을 이 길이로 자른다(6.4.8)
NOTICE_TTL_S = 24 * 60 * 60
NOTICE_URL = "/"
REMINDER_TTL_S = 60 * 60  # 일정 알림은 한 시간이 지나면 낡았다(SP9 5.3)
GONE_STATUSES = frozenset({404, 410})  # 구독이 만료됐다: 다시 보내지 않고 끈다

PushResult = Literal["ok", "gone", "failed"]


class PushSender(Protocol):
    """동기 전송 하나. HTTP 상태 코드를 돌려준다(201이면 받음). 네트워크 오류는 예외로 올린다."""

    def send(self, sub: PushSubscription, payload: dict[str, Any], *, ttl: int, topic: str | None) -> int: ...


class WebPushSender:
    """`pywebpush`(RFC 8291 암호화, VAPID 서명). 실패 응답은 예외 대신 상태 코드로 돌려준다.

    `WebPushException`의 메시지에는 구독 주소가 들어 있을 수 있어 감싸거나 남기지 않는다.
    """

    def __init__(self, vapid: VapidConfig, *, timeout_s: float = 10) -> None:
        self._vapid = vapid
        self._timeout_s = timeout_s

    def send(self, sub: PushSubscription, payload: dict[str, Any], *, ttl: int, topic: str | None) -> int:
        from pywebpush import WebPushException, webpush

        headers = {"Topic": topic} if topic else {}
        try:
            resp = webpush(
                subscription_info={"endpoint": sub.endpoint, "keys": {"p256dh": sub.p256dh, "auth": sub.auth}},
                data=json.dumps(payload, ensure_ascii=False),
                vapid_private_key=self._vapid.private_key.get_secret_value(),
                vapid_claims={"sub": self._vapid.subject},
                ttl=ttl,
                headers=headers,
                timeout=self._timeout_s,
            )
        except WebPushException as e:
            status = getattr(e.response, "status_code", None)
            if isinstance(status, int):
                return status
            raise PushSendError("push_failed") from None  # 메시지(주소가 들어 있다)를 잇지 않는다
        return int(getattr(resp, "status_code", 201))


class PushSendError(Exception):
    """응답 없이 실패한 푸시. 메시지는 고정 문자열이다."""


def effective_channel(primary: str, active_subscriptions: int, push_enabled: bool) -> Channel:
    """실제 통로(7.3 D1a)."""
    return "app" if primary == "app" and push_enabled and active_subscriptions > 0 else "telegram"


def _first_line(text: str) -> str:
    line = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")
    return line if len(line) <= BODY_MAX_CHARS else line[: BODY_MAX_CHARS - 1] + "…"


def push_payload(run: Run, text: str, *, reply_until: datetime, now: datetime) -> tuple[dict[str, Any], int, str]:
    """회차 푸시(6.4.8): (페이로드, TTL 초 = `now`(주입한 시계)부터 답장 창 끝까지, Topic `run-<id>`)."""
    payload = {
        "type": "checkin",
        "checkin_id": run.id,
        "title": PUSH_TITLES[run.loop],
        "body": _first_line(text),
        "url": f"/checkins/{run.id}",
    }
    ttl = max(0, int((reply_until - now).total_seconds()))
    return payload, ttl, f"run-{run.id}"


def notice_payload(text: str) -> dict[str, Any]:
    """고정 안내·시험 푸시(`type: notice`)."""
    return {"type": "notice", "checkin_id": None, "title": NOTICE_TITLE, "body": _first_line(text), "url": NOTICE_URL}


def reminder_payload(title: str, body: str, url: str) -> dict[str, Any]:
    """일정 알림(`type: reminder`, SP9 5.3): 제목은 일정 제목, 누르면 `url`(앱 `/schedule/?date=…`)."""
    return {"type": "reminder", "checkin_id": None, "title": title, "body": _first_line(body), "url": url}


@dataclass
class DeliveryOutcome:
    """회차 전달 하나의 결과. `channel`은 전체 본문을 받은(받으려던) 통로(D5)."""

    channel: Channel
    mode: Literal["full", "fallback"]
    sent: bool
    telegram_message_id: int | None = None
    push_ok: int = 0
    push_failed: int = 0

    @property
    def tried_push(self) -> bool:
        return self.push_ok + self.push_failed > 0


def record_deliveries(deliveries: DeliveriesRepo, run_id: int, outcome: DeliveryOutcome) -> None:
    """`run_deliveries`(4.3: 이 모듈이 쓴다): 푸시를 해 봤으면 앱 줄(받았으면 sent), 텔레그램으로 보냈으면(대체 포함)
    텔레그램 줄. 디스패처가 회차 작업(두뇌 갈래) 안에서, 회차 상태와 같은 트랜잭션으로 부른다."""
    status = "sent" if outcome.sent else "not_sent"
    if outcome.tried_push:
        app_status = "sent" if outcome.push_ok > 0 else "not_sent"
        deliveries.record(run_id, "app", "full", app_status, push_ok=outcome.push_ok, push_failed=outcome.push_failed)
    if outcome.channel == "telegram":
        deliveries.record(run_id, "telegram", outcome.mode, status, telegram_message_id=outcome.telegram_message_id)


ToThread = Callable[..., Awaitable[Any]]


class Delivery:
    def __init__(
        self,
        *,
        telegram: Sender,
        push: PushSender | None,
        pushes: PushRepo,
        state: StateRepo,
        clock: Clock,
        settings: Settings,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        to_thread: ToThread = asyncio.to_thread,
    ) -> None:
        self.telegram = telegram
        self.push = push if settings.vapid is not None else None  # VAPID가 없으면 푸시는 늘 꺼져 있다
        self.pushes = pushes
        self.state = state
        self.clock = clock
        self.settings = settings
        self._sleep = sleep
        self.to_thread = to_thread

    @property
    def push_enabled(self) -> bool:
        return self.push is not None

    def primary(self) -> Channel:
        v = self.state.get(NOTIFY_PRIMARY_KEY)
        return v if v in ("telegram", "app") else self.settings.notify.default_primary  # type: ignore[return-value]

    def effective(self) -> Channel:
        return effective_channel(self.primary(), self.pushes.count_active(), self.push_enabled)

    # --- 회차 (D2~D4) ---

    async def deliver_run(
        self, run: Run, out: Outbound, *, reply_until: datetime, attempts: int = SEND_ATTEMPTS
    ) -> DeliveryOutcome:
        if self.effective() == "app":
            payload, ttl, topic = push_payload(run, out.text, reply_until=reply_until, now=self.clock.now())
            ok, failed = await self._push_all(payload, ttl=ttl, topic=topic, attempts=attempts, run_id=run.id)
            if ok:
                return DeliveryOutcome("app", "full", True, push_ok=ok, push_failed=failed)
            log.warning("push_fallback_telegram", extra={"run_id": run.id, "push_failed": failed})
            sent, mid = await self._telegram(out, attempts=attempts, run_id=run.id)
            return DeliveryOutcome("telegram", "fallback", sent, mid, push_ok=0, push_failed=failed)
        sent, mid = await self._telegram(out, attempts=attempts, run_id=run.id)
        return DeliveryOutcome("telegram", "full", sent, mid)

    async def _telegram(self, out: Outbound, *, attempts: int, run_id: int) -> tuple[bool, int | None]:
        return await send_run_telegram(self.telegram, out, sleep=self._sleep, attempts=attempts, run_id=run_id)

    # --- 고정 안내 (D8) ---

    async def deliver_notice(self, text: str) -> Channel | None:
        """실제 통로가 `app`이면 `type: notice` 푸시(구독마다 한 번), 아무도 받지 못하면 텔레그램.

        받은 통로를 돌려준다. 아무 데도 못 보냈으면 None.
        """
        if self.effective() == "app":
            ok, _ = await self._push_all(notice_payload(text), ttl=NOTICE_TTL_S, topic=None, attempts=1)
            if ok:
                return "app"
            log.warning("notice_push_fallback_telegram")
        try:
            await self.telegram.send(Outbound(text=text))
        except Exception as e:  # noqa: BLE001 - 안내가 안 가도 다음 기회에 다시 보낸다
            log.warning("notice_send_error", extra={"error_type": type(e).__name__})
            return None
        return "telegram"

    # --- 일정 알림 (SP9 5.3) ---

    async def deliver_reminder(self, title: str, body: str, url: str) -> Channel | None:
        """`deliver_notice`와 같은 통로 규칙: 주 통로가 `app`이면 `type: reminder` 푸시, 아무도 못 받으면 텔레그램에
        같은 한 줄. 받은 통로, 어디에도 못 보냈으면 None."""
        if self.effective() == "app":
            ok, _ = await self._push_all(reminder_payload(title, body, url), ttl=REMINDER_TTL_S, topic=None, attempts=1)
            if ok:
                return "app"
            log.warning("reminder_push_fallback_telegram")
        try:
            await self.telegram.send(Outbound(text=f"{title} · {body}"))
        except Exception as e:  # noqa: BLE001 - 못 갔으면 부르는 쪽이 `failed`로 적는다
            log.warning("reminder_send_error", extra={"error_type": type(e).__name__})
            return None
        return "telegram"

    # --- 시험 (6.4.8 `POST /push/test`) ---

    async def push_test(self, record: Callable[[list[dict[str, Any]]], object]) -> tuple[int, int]:
        """켜진 구독 모두에 시험 알림을 한 번씩 보낸다. 하루 3회 상한에 세지 않는다. (받은 수, 못 받은 수).

        결과(`[{"id", "result"}]`)는 `record`(즉시 갈래 `push_test_result`)가 적는다. 시험의 `failed`는 연속 실패에
        세지 않는다(`PushRepo.apply_result(count_failure=False)`).
        """
        if self.push is None:
            return 0, 0
        payload = notice_payload(PUSH_TEST_TEXT)
        results: list[dict[str, Any]] = []
        for sub in self.pushes.active():
            res = await self._try(sub, payload, ttl=NOTICE_TTL_S, topic=None, attempts=1)
            results.append({"id": sub.id, "result": res})
        record(results)
        ok = sum(1 for r in results if r["result"] == "ok")
        return ok, len(results) - ok

    # --- 공통 ---

    async def _push_all(
        self, payload: dict[str, Any], *, ttl: int, topic: str | None, attempts: int, run_id: int | None = None
    ) -> tuple[int, int]:
        if self.push is None:
            return 0, 0
        ok = failed = 0
        for sub in self.pushes.active():
            res = await self._try(sub, payload, ttl=ttl, topic=topic, attempts=attempts, run_id=run_id)
            self._record(sub.id, res, self.clock.now())
            if res == "ok":
                ok += 1
            else:
                failed += 1
        return ok, failed

    async def _try(
        self, sub: PushSubscription, payload: dict[str, Any], *, ttl: int, topic: str | None, attempts: int,
        run_id: int | None = None,
    ) -> PushResult:
        """한 구독에 바로 `attempts`회까지. 404/410이면 그 자리에서 그만둔다."""
        assert self.push is not None
        extra: dict[str, Any] = {"subscription_id": sub.id}
        if run_id is not None:
            extra["run_id"] = run_id
        for i in range(attempts):
            try:
                status = await self.to_thread(self.push.send, sub, payload, ttl=ttl, topic=topic)
            except Exception as e:  # noqa: BLE001 - 종류만 남긴다(메시지에 구독 주소가 들어 있을 수 있다)
                log.warning("push_send_error", extra={**extra, "try": i + 1, "error_type": type(e).__name__})
            else:
                if 200 <= status < 300:
                    return "ok"
                log.warning("push_send_error", extra={**extra, "try": i + 1, "status": status})
                if status in GONE_STATUSES:
                    return "gone"
            if i + 1 < attempts:
                await self._sleep(SEND_RETRY_DELAYS_S[i])
        return "failed"

    def _record(self, sub_id: int, result: str, at: datetime) -> None:
        """회차와 고정 안내: 전달 하나에 결과 하나(`failed`는 연속 실패 +1)."""
        if self.pushes.apply_result(sub_id, result, at):
            log.info("push_subscription_disabled", extra={"subscription_id": sub_id, "reason": result})
