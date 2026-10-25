"""웹 장애의 해결 확인 (스펙 5.1). `merged` 상태의 `app`·`dashboard`·`vercel` 장애마다 `tick()`이 한 걸음씩.

1. Vercel 배포가 `success`가 될 때까지 기다린다. 이전 빌드의 에러는 이때까지 세지 않는다.
2. `success` 뒤 `web_verify_minutes` 동안 같은 지문이 다시 안 나면 `resolved`(이슈 닫기 + "고쳤어요").
   `vercel:` 지문은 `success`만으로 `resolved`.
3. `success` 뒤 같은 지문이 다시 나면 `failed-N` +1과 `recurred`.
4. 3시간 안에 `success`가 안 되면 `failed-N` +1. 둘 다 `merged`를 떼고 `open`으로 돌려 `repair.yml`이 다시 집게 한다.
   이슈가 닫혀 있으면(수리 PR의 닫기 낱말이나 손) 라벨 전에 다시 연다: 닫힌 이슈는 게이트·sweep이 건너뛴다(최종 리뷰 I-1).

어느 상태를 보나(최종 리뷰 I-3):
- 컨텍스트는 정확히 하나: `app` → `vercel_context_app`, `dashboard` → `vercel_context_dashboard`(설정, 기본값은
  config.medic.toml과 같다), `vercel:<컨텍스트>` → 그 컨텍스트. 만든 계정이 `vercel[bot]`인 상태만, 그중 가장 새 것.
- 커밋 R은 업데이터가 `merged`로 둘 때 적은 `Repairs #N` 커밋(`detail["repair_sha"]`). 없으면(업그레이드 전) 처음
  본 `main` 머리.
- 그 컨텍스트의 폴더(`web/app`·`web/dashboard`)를 알면, R과 그 뒤 `main` 커밋 중 그 폴더를 바꾼 가장 새 커밋 W를
  찾고, W부터 `main`을 따라 앞으로 걸어 그 컨텍스트 상태가 처음 있는 커밋을 본다. Vercel은 푸시마다 **머리 커밋만**
  빌드하고(승격은 develop 커밋 여럿을 한 푸시로 ff한다), `ignoreCommand`로 그 폴더를 안 바꾼 푸시는 건너뛴다.
  그래서 W 자신에는 상태가 없을 수 있고, W의 변경을 담은 빌드는 W 뒤 첫 상태다(재리뷰 I-4).
  R 뒤로 그 폴더를 바꾼 커밋이 없으면(수리가 웹 폴더를 안 바꿨다, 예: BE 응답을 고친 앱 오류) 다시 빌드할 것이
  없다: Vercel 기다림을 건너뛰고 바로 조용한 시간으로 간다. 단 `vercel:` 빌드 실패는 다시 빌드되어야 고쳐지므로
  R부터 걸어 기다린다.
- 폴더를 모르는 `vercel:` 컨텍스트는 R부터 차례로 그 컨텍스트 상태가 처음 있는 커밋을 본다.
- 걷기는 `WALK_MAX`(50) 커밋까지만(한 회차의 API 호출 상한). 넘으면 이번 회차는 기다린다(3시간 뒤 실패).

진행은 장애의 `detail["web"]` = `{"sha", "since", "ok_at"}`에 둔다(medic.db). GitHub이 안 되면 그 회차만 멈춘다.
실패 처리는 N을 먼저 `detail["web"]["fail"]`에 저장하고 라벨을 쓴다(응답이 끊겨 다시 해도 같은 N, `recurred`는
한 번만 단다). `resolved`로 바꾼 뒤 알림 전에 죽으면 알림은 잃는다(두 번 보내느니 한 번 놓친다. 업데이터와 같다).
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
VERCEL_WAIT = timedelta(hours=3)
WALK_MAX = 50  # 상태를 찾아 앞으로 걷는 커밋 수 상한
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
            repair = inc.detail.get("repair_sha")
            sha = repair if isinstance(repair, str) and repair else self._gh.head_sha("main")
            web = {"sha": sha, "since": iso_utc(now), "ok_at": None}
            self._save(inc, web)
        if isinstance(web.get("fail"), dict):  # 쓰다 끊긴 실패 처리를 먼저 마친다
            self._fail(inc, web, recurred=bool(web["fail"].get("recurred")))
            return
        since = _parse(web["since"]) or now
        ok_at = _parse(web.get("ok_at"))
        if ok_at is None:
            if not self._vercel_ok(inc, web["sha"]):
                if now - since >= VERCEL_WAIT:
                    self._fail(inc, web, recurred=False)
                return
            ok_at = now
            web["ok_at"] = iso_utc(now)
            self._save(inc, web)
            if inc.part == "vercel":
                self._resolve(inc, now)
            return
        last = _parse(inc.last_seen)
        if last is not None and last > ok_at:
            self._fail(inc, web, recurred=True)
        elif now - ok_at >= timedelta(minutes=self._cfg.web_verify_minutes):
            self._resolve(inc, now)

    def _context(self, inc: Incident) -> str:
        if inc.part == "vercel":
            return inc.fingerprint.partition(":")[2]
        return self._cfg.vercel_context_app if inc.part == "app" else self._cfg.vercel_context_dashboard

    def _vercel_ok(self, inc: Incident, repair: str) -> bool:
        """머리 docstring의 "어느 상태를 보나". 그 커밋의 상태가 `success`여야 한다(없거나 `pending`이면 기다린다)."""
        ctx = self._context(inc)
        head = self._gh.head_sha("main")
        span = [repair, *([] if head == repair else self._gh.commits_after(repair, head))]
        folder = {self._cfg.vercel_context_app: "web/app", self._cfg.vercel_context_dashboard: "web/dashboard"}.get(ctx)
        start = 0
        if folder is not None:
            touched = set(self._gh.path_commits(folder, "main"))
            last = next((k for k in range(len(span) - 1, -1, -1) if span[k] in touched), None)
            if last is None and inc.part != "vercel":
                return True  # R 뒤로 그 폴더를 바꾼 커밋이 없다: 다시 빌드할 것이 없다(조용한 시간이 확인한다)
            # `vercel:` 빌드 실패는 다시 빌드되어야만 고쳐진다: 폴더를 안 바꾼 수리면 R부터 걸어 기다린다
            start = last or 0
        for sha in span[start:start + WALK_MAX]:  # W(또는 R)부터 앞으로: 처음 상태가 있는 커밋이 그 변경의 빌드
            state = self._gh.vercel_state(sha, ctx)
            if state is not None:
                return state == "success"
        return False

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

    def _fail(self, inc: Incident, web: dict[str, Any], *, recurred: bool) -> None:
        n = inc.issue_number
        assert n is not None
        fail = web.get("fail")
        if not isinstance(fail, dict):  # N은 한 번만 정해 먼저 저장한다(업데이터의 rolled_back 연산과 같다)
            labels = self._gh.issue_labels(n)
            failed = max((int(m[1]) for x in labels if (m := _FAILED_RE.match(x))), default=0) + 1
            fail = {"n": failed, "recurred": recurred}
            self._save(inc, {**web, "fail": fail})
        failed = int(fail["n"])
        if f"failed-{failed}" not in self._gh.issue_labels(n):  # 이미 달렸으면(응답만 끊긴 경우) 다시 쓰지 않는다
            # 수리 PR의 닫기 낱말(또는 손)로 닫혔을 수 있다: 닫힌 채면 게이트·sweep이 건너뛴다(최종 리뷰 I-1)
            self._gh.reopen(n, [])
            self._gh.remove_label(n, "merged")
            add = [f"failed-{failed}"]
            if recurred:
                self._gh.remove_label(n, "recurred")  # 이미 달려 있으면 `labeled`가 다시 안 온다
                add.insert(0, "recurred")
            self._gh.add_labels(n, add)  # 한 번에: repair 게이트가 N을 본다
        detail = {k: v for k, v in inc.detail.items() if k not in ("web", "repair_sha")}  # 다음 수리가 새로 적는다
        self._store.set_state(inc.fingerprint, "open", failures=failed, detail=detail)
        log.warning("web_verify_failed recurred=%s failed=%d", recurred, failed)
