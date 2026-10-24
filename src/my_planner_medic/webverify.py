"""웹 장애의 해결 확인 (스펙 5.1). `merged` 상태의 `app`·`dashboard`·`vercel` 장애마다 `tick()`이 한 걸음씩.

1. Vercel 커밋 상태(컨텍스트 접두 `Vercel`)가 `success`가 될 때까지 기다린다. 처음 본 때의 `main` 머리 커밋이나
   더 새 머리 커밋 중 하나가 `success`면 된다. 이전 빌드의 에러는 이때까지 세지 않는다.
2. `success` 뒤 `web_verify_minutes` 동안 같은 지문이 다시 안 나면 `resolved`(이슈 닫기 + "고쳤어요").
   `vercel:` 지문은 `success`만으로 `resolved`.
3. `success` 뒤 같은 지문이 다시 나면 `failed-N` +1과 `recurred`.
4. 3시간 안에 `success`가 안 되면 `failed-N` +1. 둘 다 `merged`를 떼고 `open`으로 돌려 `repair.yml`이 다시 집게 한다.

진행은 장애의 `detail["web"]` = `{"sha", "since", "ok_at"}`에 둔다(medic.db). GitHub이 안 되면 그 회차만 멈춘다.
라벨 쓰기는 `merged` 떼기 → 라벨 달기 순서라 중간에 끊겨 다시 해도 같은 N이다.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta
from typing import Any

from .clock import Clock
from .config import MedicConfig
from .github import GitHub, GitHubUnavailable
from .notify import NotifierLike
from .store import Incident, MedicStore, iso_utc

log = logging.getLogger(__name__)

WEB_PARTS = ("app", "dashboard", "vercel")
VERCEL_CONTEXT = "Vercel"
VERCEL_WAIT = timedelta(hours=3)
_FAILED_RE = re.compile(r"^failed-(\d+)$")


def _parse(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        t = datetime.fromisoformat(value)
    except ValueError:
        return None
    return t if t.tzinfo is not None else None


class WebVerifier:
    def __init__(
        self, cfg: MedicConfig, store: MedicStore, gh: GitHub, notifier: NotifierLike, clock: Clock
    ) -> None:
        self._cfg = cfg
        self._store = store
        self._gh = gh
        self._notifier = notifier
        self._clock = clock

    def tick(self) -> None:
        now = self._clock.now()
        for inc in self._store.by_state("merged"):
            if inc.part not in WEB_PARTS or inc.issue_number is None:
                continue
            try:
                self._step(inc, now)
            except GitHubUnavailable as exc:
                if not exc.rejected:
                    log.warning("web_verify_unavailable %s (%d)", exc.kind, exc.status)
                    return  # 연결·인증·한도·5xx: 이번 회차의 GitHub 일을 멈춘다
                log.warning("web_verify_rejected %d", exc.status)  # 이 이슈만의 문제

    # --- 한 걸음 ----------------------------------------------------------

    def _step(self, inc: Incident, now: datetime) -> None:
        web = inc.detail.get("web")
        if not isinstance(web, dict) or not isinstance(web.get("sha"), str) or _parse(web.get("since")) is None:
            sha = self._gh.head_sha("main")
            web = {"sha": sha, "since": iso_utc(now), "ok_at": None}
            self._save(inc, web)
        since = _parse(web["since"]) or now
        ok_at = _parse(web.get("ok_at"))
        if ok_at is None:
            if not self._vercel_ok(web["sha"]):
                if now - since >= VERCEL_WAIT:
                    self._fail(inc, recurred=False)
                return
            ok_at = now
            web["ok_at"] = iso_utc(now)
            self._save(inc, web)
            if inc.part == "vercel":
                self._resolve(inc, now)
            return
        last = _parse(inc.last_seen)
        if last is not None and last > ok_at:
            self._fail(inc, recurred=True)
        elif now - ok_at >= timedelta(minutes=self._cfg.web_verify_minutes):
            self._resolve(inc, now)

    def _vercel_ok(self, sha: str) -> bool:
        if self._gh.commit_state(sha, VERCEL_CONTEXT) == "success":
            return True
        head = self._gh.head_sha("main")
        return head != sha and self._gh.commit_state(head, VERCEL_CONTEXT) == "success"

    def _save(self, inc: Incident, web: dict[str, Any]) -> None:
        self._store.set_state(inc.fingerprint, "merged", detail={**inc.detail, "web": web})

    # --- 끝 ---------------------------------------------------------------

    def _resolve(self, inc: Incident, now: datetime) -> None:
        n = inc.issue_number
        assert n is not None
        self._gh.close(n)  # 실패하면 resolved가 아니라 다음 회차에 다시 한다
        self._store.set_state(inc.fingerprint, "resolved", resolved_at=iso_utc(now))
        try:
            pr = self._gh.pr_for_issue(n)
        except GitHubUnavailable:
            pr = None
        title, url = pr or (inc.fingerprint, self._gh.issue_url(n))
        try:
            self._notifier.fixed(title, url)
        except Exception as exc:  # noqa: BLE001 - 알림 때문에 상태가 어긋나면 안 된다
            log.warning("notify_failed %s", type(exc).__name__)

    def _fail(self, inc: Incident, *, recurred: bool) -> None:
        n = inc.issue_number
        assert n is not None
        labels = self._gh.issue_labels(n)
        failed = max((int(m[1]) for x in labels if (m := _FAILED_RE.match(x))), default=0) + 1
        self._gh.remove_label(n, "merged")
        add = [f"failed-{failed}"]
        if recurred:
            self._gh.remove_label(n, "recurred")  # 이미 달려 있으면 `labeled`가 다시 안 온다
            add.insert(0, "recurred")
        self._gh.add_labels(n, add)  # 한 번에: repair 게이트가 N을 본다
        detail = {k: v for k, v in inc.detail.items() if k != "web"}
        self._store.set_state(inc.fingerprint, "open", failures=failed, detail=detail)
        log.warning("web_verify_failed recurred=%s failed=%d", recurred, failed)
