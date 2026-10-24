"""결과 알림 (스펙 6장). 장애 하나에 결과 알림 한 번, 하루 `max_notices_per_day`개까지.

길: `POST {api_base}/internal/notify`(BE가 앱 푸시나 텔레그램으로). BE가 안 되거나 `direct`면 텔레그램 API로 바로.
오늘(논리적 날짜) 보낸 수가 상한이면 `notices`에 쌓았다가, 다음 아침 회차 시각 이후 첫 `flush_spill`이
한 줄 묶음으로 따로 보낸다(계획의 결정 1: BE 브리핑은 바꾸지 않는다). 묶음은 상한에 세지 않는다.

`Notifier`는 네트워크가 안 돼도 예외를 올리지 않는다. 로그에는 채널과 상태 코드만 남긴다(텔레그램 URL에
봇 토큰이 들어 있으니 URL·본문·예외 메시지는 남기지 않는다).

kv 키: `daily:<key>`(마지막으로 보낸 논리적 날짜), `spill_after`(쌓인 알림을 내보낼 가장 이른 시각, ISO).
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Protocol

from .clock import Clock
from .config import MedicConfig
from .http import Http
from .schedule import next_slot
from .store import MedicStore, iso_utc
from .tz import logical_date

log = logging.getLogger(__name__)

FIXED_TEXT = "🔧 자동으로 고쳤어요: {title}. {url}"
GAVE_UP_TEXT = "⚠️ 자동으로 못 고쳤어요: {fp}. 지금은 {state}. {url}"
ROLLED_BACK = "이전 버전으로 돌려 둠"
AS_IS = "그대로"
BUNDLE_TEXT = "자동 복구 알림 {n}개: {items}"
BE_TIMEOUT_S = 20  # BE가 안에서 텔레그램으로 물러서는 시간까지 기다려, 같은 알림이 두 번 가는 일을 줄인다
BUNDLE_MAX = 480  # BE `RecoveryNoticeBody.text`는 500자까지
TELEGRAM = "https://api.telegram.org/bot{token}/sendMessage"


class NotifierLike(Protocol):
    def fixed(self, pr_title: str, pr_url: str) -> None:
        """"🔧 자동으로 고쳤어요: <PR 제목>. <PR 링크>"."""
        ...

    def gave_up(self, fingerprint: str, rolled_back: bool, issue_url: str, *, direct: bool = False) -> None:
        """"⚠️ 자동으로 못 고쳤어요: …". `direct`면 BE를 거치지 않고 텔레그램으로 바로."""
        ...

    def daily(self, text: str, key: str) -> None:
        """같은 `key`는 하루(논리적 날짜) 한 번만 보낸다(상한도 지킨다)."""
        ...

    def flush_spill(self) -> None:
        """상한에 막혀 쌓인 알림을, 다음 아침 회차 시각이 지났으면 한 줄 묶음으로 보낸다."""
        ...


class Notifier:
    def __init__(self, cfg: MedicConfig, store: MedicStore, http: Http, clock: Clock) -> None:
        self._cfg = cfg
        self._store = store
        self._http = http
        self._clock = clock

    # --- 공개 -------------------------------------------------------------

    def fixed(self, pr_title: str, pr_url: str) -> None:
        self._notice(FIXED_TEXT.format(title=pr_title, url=pr_url))

    def gave_up(self, fingerprint: str, rolled_back: bool, issue_url: str, *, direct: bool = False) -> None:
        state = ROLLED_BACK if rolled_back else AS_IS
        self._notice(GAVE_UP_TEXT.format(fp=fingerprint, state=state, url=issue_url), direct=direct)

    def daily(self, text: str, key: str) -> None:
        now = self._clock.now()
        today = self._today(now)
        mark = f"daily:{key}"
        if self._store.kv_get(mark) == today:
            return
        if self._notice(text, spill_failed=False):
            self._store.kv_set(mark, today)  # 못 보냈으면 표시하지 않아 다음 회차에 다시 한다

    def flush_spill(self) -> None:
        try:
            self._flush(self._clock.now())
        except Exception as exc:  # noqa: BLE001 - 알림 때문에 호출한 쪽이 멈추면 안 된다
            log.warning("notify_flush_failed %s", type(exc).__name__)

    # --- 속 ---------------------------------------------------------------

    def _today(self, now: datetime) -> str:
        return logical_date(now, self._cfg.timezone, self._cfg.day_boundary).isoformat()

    def _notice(self, text: str, *, direct: bool = False, spill_failed: bool = True) -> bool:
        """상한 안이면 보낸다. 상한이면 쌓는다(True). 보내지 못했으면 `spill_failed`일 때 쌓는다(False)."""
        try:
            now = self._clock.now()
            today = self._today(now)
            if self._store.sent_notices(today) >= self._cfg.max_notices_per_day:
                self._store.add_notice(today, text, None)
                self._arm_spill(now)
                log.info("notice_spilled cap=%d", self._cfg.max_notices_per_day)
                return True
            if self._deliver(text, direct=direct):
                self._store.add_notice(today, text, iso_utc(now))
                return True
            if spill_failed:  # 둘 다 안 됐다: 잃지 않게 쌓아 두었다가 묶음에 실린다
                self._store.add_notice(today, text, None)
                self._arm_spill(now)
            return False
        except Exception as exc:  # noqa: BLE001 - 알림은 호출한 쪽을 멈추지 않는다
            log.warning("notify_failed %s", type(exc).__name__)
            return False

    def _arm_spill(self, now: datetime) -> None:
        if self._store.kv_get("spill_after") is None:
            self._store.kv_set("spill_after", iso_utc(self._next_morning(now)))

    def _next_morning(self, now: datetime) -> datetime:
        at = now
        for _ in range(16):  # 아침 회차는 매일 있으므로 두세 번 안에 나온다
            at, loop = next_slot(self._cfg, at)
            if loop == "morning_brief":
                break
        return at

    def _flush(self, now: datetime) -> None:
        pending = self._store.spilled_notices()
        if not pending:
            self._store.kv_delete("spill_after")
            return
        raw = self._store.kv_get("spill_after")
        if raw is None:
            self._arm_spill(now)  # 표시가 없으면 지금부터 다음 아침까지 기다린다
            return
        if now < datetime.fromisoformat(raw):
            return
        text = BUNDLE_TEXT.format(n=len(pending), items=" / ".join(t for _, t in pending))
        if len(text) > BUNDLE_MAX:
            text = text[: BUNDLE_MAX - 1] + "…"
        if self._deliver(text, direct=False):
            self._store.mark_notices_sent([i for i, _ in pending], iso_utc(now))
            self._store.kv_delete("spill_after")

    def _deliver(self, text: str, *, direct: bool) -> bool:
        cfg = self._cfg
        if not direct and cfg.api_enabled and cfg.api_token:
            status, _, _ = self._http.request(
                "POST",
                f"{cfg.api_base}/internal/notify",
                headers={"Authorization": f"Bearer {cfg.api_token}"},
                json={"text": text, "kind": "recovery"},
                timeout=BE_TIMEOUT_S,
            )
            if 200 <= status < 300:
                return True
            log.warning("notify_be_failed status=%d", status)
        if cfg.telegram_token and cfg.owner_telegram_id:
            status, _, _ = self._http.request(
                "POST",
                TELEGRAM.format(token=cfg.telegram_token),
                json={"chat_id": cfg.owner_telegram_id, "text": text},
                timeout=10,
            )
            if 200 <= status < 300:
                return True
            log.warning("notify_telegram_failed status=%d", status)
        return False
