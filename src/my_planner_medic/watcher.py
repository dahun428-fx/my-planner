"""감시자 (스펙 3.2, 3.5 하트비트 쓰기, 4.1, 4.4). `tick()`을 2분마다 부른다.

kv 키(모두 `medic.db`):
- `log_cursor` `{"file", "offset"}`(file은 `#서명`까지 그대로), `last_tick_at`, `last_heartbeat_at`,
  `health_streak`(int), `deployed_sha`(읽기만, 티켓 09가 채운다. 없으면 "unknown").
- `warn_window` 이벤트 → ISO 시각 목록(최근 1시간), `bind_error_seen` 걸쇠(bool),
  `wake_grace_until`(절전 유예 끝, ISO), `last_import_at`(Actions 이슈 가져오기, ISO),
  `recent_rows`(허용 열만 남긴 최근 로그 줄, 30분 안 최대 20개, INFO가 아닌 줄 우선).

GitHub이 안 되면(`GitHubUnavailable`) 그 회차의 GitHub 일만 멈춘다. 장애는 `medic.db`에 남아 다음
회차에 올라간다. 이슈가 없는 장애는 올리기 전에 늘 `find_incident`로 찾는다(응답이 끊긴 생성 보호).
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, date, datetime, timedelta
from typing import Any

from .clock import Clock
from .config import MedicConfig
from .github import RECORD, GitHub, GitHubUnavailable
from .http import Http
from .logs import LogCursor, read_new_lines
from .notify import NotifierLike
from .redact import allowed_health, allowed_log_row, issue_body, safe_token
from .schedule import next_run
from .signals import (
    HealthProbe,
    Signal,
    has_bind_error,
    health_signals,
    log_signals,
)
from .store import Incident, MedicStore, iso_utc
from .tz import zone
from .webverify import WebVerifier

log = logging.getLogger(__name__)

WAKE_GAP = timedelta(minutes=10)  # 직전 tick과 이만큼 벌어지면 막 깬 것
WAKE_GRACE = timedelta(minutes=10)
BODY_EVERY = timedelta(minutes=10)
RECUR_WINDOW = timedelta(hours=24)
IMPORT_EVERY = timedelta(minutes=30)
ROWS_KEEP = 20
ROWS_WINDOW = timedelta(minutes=30)
ACTIONS_TZ = "Asia/Seoul"  # watch.yml의 "오늘"(스펙 3.5)
ACTIVE_STATES = ("open", "repairing", "merged", "deploying", "gave_up")
CI_MAIN = "ci:main"
FIXED_COMMENT = "고쳤어요: `main`의 CI가 다시 성공했어요 ({sha})."
CI_FIXED_TITLE = "main의 CI가 다시 성공했어요"  # 결과 알림 "고쳤어요"의 제목(수리 PR이 없을 때)
_STALE_RE = re.compile(r"^stale-(\d{4}-\d{2}-\d{2})$")
_TITLE_PREFIX = "[incident] "
_ACTIONS_KIND = "actions"


def _parse(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        t = datetime.fromisoformat(value)
    except ValueError:
        return None
    return t if t.tzinfo is not None else None


def _z(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _trim_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """최대 `ROWS_KEEP`개. INFO가 아닌 줄을 먼저(최근 것부터) 남기고 남는 자리를 최근 INFO 줄로 채운다. 순서는 시간순."""
    if len(rows) <= ROWS_KEEP:
        return rows
    loud = [i for i, r in enumerate(rows) if r.get("level") != "INFO"][-ROWS_KEEP:]
    quiet = [i for i, r in enumerate(rows) if r.get("level") == "INFO"]
    room = ROWS_KEEP - len(loud)
    keep = set(loud) | set(quiet[len(quiet) - room:] if room else [])
    return [r for i, r in enumerate(rows) if i in keep]


def _is_imported(fp: str) -> bool:
    return fp == CI_MAIN or fp.startswith("vercel:")


class Watcher:
    def __init__(
        self, cfg: MedicConfig, store: MedicStore, gh: GitHub, http: Http, clock: Clock,
        notifier: NotifierLike,
    ) -> None:
        self._cfg = cfg
        self._store = store
        self._gh = gh
        self._http = http
        self._clock = clock
        self._notifier = notifier
        self._web = WebVerifier(cfg, store, gh, notifier, clock)
        self.suppressed = False  # 업데이터가 배포·배포 롤백 동안 켠다
        self._log_dir = cfg.root / "state" / "logs"
        if zone(cfg.timezone) is UTC and cfg.timezone not in ("UTC", "Etc/UTC"):
            log.warning("timezone_fallback_utc %s", safe_token(cfg.timezone))

    # --- 한 회차 ----------------------------------------------------------

    def tick(self) -> None:
        now = self._clock.now()
        suppress = self._wake_grace(now) or self.suppressed
        records = self._read_logs()
        rows = self._remember_rows(records, now)
        signals = self._log_signals(records, now)
        if has_bind_error(records):
            self._store.kv_json_set("bind_error_seen", True)
        health: dict[str, Any] | None = None
        if self._cfg.api_enabled:
            more, health = self._health(now, suppress)
            signals += more
        for sig in signals:
            self._record(sig, records, rows, now)
        self._sync(now, health)
        self._notifier.flush_spill()  # 쌓인 알림은 다음 아침 회차 뒤 첫 tick에(스펙 6장)
        self._web.tick()  # 5.1: 웹 장애의 해결 확인

    def heartbeat(self) -> None:
        """`enabled = false`일 때: 감시 없이 하트비트만(죽은 것으로 보이지 않게)."""
        try:
            self._heartbeat(self._clock.now(), self._store.kv_get("deployed_sha") or "unknown")
        except GitHubUnavailable as exc:
            log.warning("github_unavailable %s (%d)", exc.kind, exc.status)

    def _wake_grace(self, now: datetime) -> bool:
        last = _parse(self._store.kv_get("last_tick_at"))
        until = _parse(self._store.kv_get("wake_grace_until"))
        if last is not None and now - last >= WAKE_GAP:
            until = now + WAKE_GRACE
            self._store.kv_set("wake_grace_until", iso_utc(until))
        self._store.kv_set("last_tick_at", iso_utc(now))
        return until is not None and now < until

    # --- 로그 -------------------------------------------------------------

    def _read_logs(self) -> list[dict[str, Any]]:
        raw = self._store.kv_json_get("log_cursor")
        cursor = None
        if isinstance(raw, dict) and isinstance(raw.get("file"), str) and isinstance(raw.get("offset"), int):
            cursor = LogCursor(raw["file"], raw["offset"])
        try:
            records, new, bad = read_new_lines(self._log_dir, cursor)
        except OSError as exc:  # 회전(rename)과 겹친 경우 등: 다음 회차에 다시 읽는다
            log.warning("log_read_failed (%s)", type(exc).__name__)
            return []
        if bad:
            log.info("log_bad_lines %d", bad)
        self._store.kv_json_set("log_cursor", {"file": new.file, "offset": new.offset})
        return records

    def _remember_rows(self, records: list[dict[str, Any]], now: datetime) -> list[dict[str, Any]]:
        """허용 열만 남긴 최근 로그 줄(이슈 본문의 "직전 30분 로그")."""
        saved = self._store.kv_json_get("recent_rows")
        kept = saved if isinstance(saved, list) else []
        kept += [allowed_log_row(r, self._cfg.root) for r in records]
        cutoff = now - ROWS_WINDOW
        kept = _trim_rows(
            [r for r in kept if isinstance(r, dict) and (t := _parse(r.get("ts"))) is not None and t > cutoff]
        )
        self._store.kv_json_set("recent_rows", kept)
        return kept

    def _log_signals(self, records: list[dict[str, Any]], now: datetime) -> list[Signal]:
        saved = self._store.kv_json_get("warn_window") or {}
        window: dict[str, list[datetime]] = {}
        for event, stamps in saved.items() if isinstance(saved, dict) else []:
            window[event] = [t for s in stamps or [] if (t := _parse(s)) is not None]
        # log_signals가 1시간(WARN_WINDOW)보다 오래된 것을 제자리에서 지운다
        out = log_signals(records, self._cfg.root, now=now, warn_window=window)
        self._store.kv_json_set("warn_window", {e: [iso_utc(t) for t in ts] for e, ts in window.items()})
        return out

    def _signal_detail(self, sig: Signal, records: list[dict[str, Any]], now: datetime) -> dict[str, Any]:
        """신호를 만든 로그 줄에서 허용 목록만(예외 종류·가린 스택, 브라우저 에러 필드)."""
        if sig.kind == "warn_burst":
            return {"event": sig.fingerprint.partition(":")[2]}
        if sig.kind not in ("exception", "client_error"):
            return {}
        for rec in reversed(records):
            got = log_signals([rec], self._cfg.root, now=now, warn_window={})
            if not got or got[0].fingerprint != sig.fingerprint:
                continue
            if sig.kind == "exception":
                row = allowed_log_row(rec, self._cfg.root)
                return {"exc_type": row.get("exc_type", "?"), "exc_where": row.get("exc_where", [])}
            out = {k: safe_token(rec[k]) for k in ("app", "version", "route", "error_name") if k in rec}
            if isinstance(rec.get("frames"), list):
                out["frames"] = [safe_token(f) for f in rec["frames"][:10]]
            return out
        return {}

    # --- 헬스 -------------------------------------------------------------

    def _health(self, now: datetime, suppress: bool) -> tuple[list[Signal], dict[str, Any] | None]:
        status, body, _ = self._http.request(
            "GET",
            f"{self._cfg.api_base}/health",
            headers={"Authorization": f"Bearer {self._cfg.api_token}"},
            timeout=10,
        )
        probe = HealthProbe(None, None) if status == 0 else HealthProbe(status, body if isinstance(body, dict) else None)
        streak = self._store.kv_json_get("health_streak")
        bind = self._store.kv_json_get("bind_error_seen") is True
        signals, streak = health_signals(
            probe, now, streak=streak if isinstance(streak, int) else 0, suppress=suppress, cfg=self._cfg,
            bind_error=bind,
        )
        self._store.kv_json_set("health_streak", streak)
        if status == 200:
            self._store.kv_json_set("bind_error_seen", False)
        return signals, probe.body if status == 200 else None

    # --- 장애 기록 ----------------------------------------------------------

    def _record(self, sig: Signal, records: list[dict[str, Any]], rows: list[dict[str, Any]], now: datetime) -> None:
        prev = self._store.get(sig.fingerprint)
        inc = self._store.upsert_signal(sig, now)
        detail = {**inc.detail, **self._signal_detail(sig, records, now), "kind": sig.kind, "rows": rows}
        fields: dict[str, Any] = {}
        state = inc.state
        if prev is not None and prev.state == "resolved":
            state = "open"
            resolved_at = _parse(prev.resolved_at)
            if prev.issue_number is not None and resolved_at is not None and now - resolved_at <= RECUR_WINDOW:
                detail["reopen"] = True  # 같은 이슈를 다시 연다. 실패 수는 이어진다
                fields["resolved_at"] = None
            else:  # 24시간 뒤: 새 장애로 새 이슈
                detail.pop("reopen", None)
                at = iso_utc(sig.at)
                fields.update(
                    issue_number=None, count=1, first_seen=at, last_seen=at, synced_count=None,
                    last_synced_at=None, resolved_at=None, failures=0,
                )
        self._store.set_state(sig.fingerprint, state, detail=detail, **fields)

    # --- GitHub ----------------------------------------------------------

    def _sync(self, now: datetime, health: dict[str, Any] | None) -> None:
        sha = self._store.kv_get("deployed_sha") or "unknown"
        try:
            try:
                self._heartbeat(now, sha)
            except GitHubUnavailable as exc:
                if not exc.rejected:
                    raise  # 연결·인증·한도·5xx: 이번 회차의 GitHub 일을 멈춘다
                log.warning("github_heartbeat_rejected %s (%d)", exc.kind, exc.status)  # 장애 동기화는 계속
            self._sync_incidents(now, health, sha)
            self._import_actions(now)
            self._resolve_ci_main(now)
        except GitHubUnavailable as exc:
            log.warning("github_unavailable %s (%d)", exc.kind, exc.status)

    def _body(self, inc: Incident, health: dict[str, Any] | None, sha: str) -> str:
        return issue_body(inc, inc.detail.get("rows") or [], allowed_health(health) if health else None, sha)

    def _synced(self, inc: Incident, now: datetime, n: int) -> None:
        detail = {k: v for k, v in inc.detail.items() if k != "reopen"}
        self._store.set_state(
            inc.fingerprint, inc.state, issue_number=n, synced_count=inc.count, last_synced_at=iso_utc(now),
            detail=detail,
        )

    def _sync_incidents(self, now: datetime, health: dict[str, Any] | None, sha: str) -> None:
        for inc in self._store.by_state(*ACTIVE_STATES):
            if inc.detail.get("kind") == _ACTIONS_KIND:
                continue  # Actions가 쓴 본문은 덮지 않는다
            try:
                self._sync_one(inc, now, health, sha)
            except GitHubUnavailable as exc:
                if not exc.rejected:
                    raise  # 연결·인증·한도·5xx: 이번 회차의 GitHub 일을 멈춘다
                # 이 이슈만의 문제(지워진 이슈 404, 422 등): 다른 장애는 계속 올린다
                log.warning("github_incident_rejected %d", exc.status)

    def _sync_one(self, inc: Incident, now: datetime, health: dict[str, Any] | None, sha: str) -> None:
        record = inc.detail.get("kind") == "record"
        if inc.issue_number is None:
            found = self._gh.find_incident(inc.fingerprint)  # 응답이 끊긴 생성을 먼저 찾는다
            if found is not None and self._adoptable(found, inc):
                n = int(found["number"])
                self._gh.update_body(n, self._body(inc, health, sha))
            else:
                part = RECORD if record else inc.part
                n = self._gh.open_incident(inc.fingerprint, part, self._body(inc, health, sha))
            self._synced(inc, now, n)
        elif inc.detail.get("reopen"):
            if not record:
                # 닫힌 수리 이슈의 `merged`가 남으면 repair 게이트·sweep이 건너뛴다. 지난 `recurred`는 떼고 다시 달아야
                # `labeled` 이벤트가 다시 온다(webverify와 같은 방법)
                self._gh.remove_label(inc.issue_number, "merged")
                self._gh.remove_label(inc.issue_number, "recurred")
            self._gh.reopen(inc.issue_number, [] if record else ["recurred"])
            self._gh.update_body(inc.issue_number, self._body(inc, health, sha))
            self._synced(inc, now, inc.issue_number)
        elif inc.count != inc.synced_count:
            last = _parse(inc.last_synced_at)
            if last is None or now - last >= BODY_EVERY:
                self._gh.update_body(inc.issue_number, self._body(inc, health, sha))
                self._synced(inc, now, inc.issue_number)

    @staticmethod
    def _adoptable(found: dict[str, Any], inc: Incident) -> bool:
        """열린 이슈이거나 이 장애가 처음 보인 뒤에 만든 이슈. 24시간 넘어 닫힌 옛 이슈는 잇지 않는다."""
        if found.get("state") == "open":
            return True
        created, first = _parse(str(found.get("created_at", "")).replace("Z", "+00:00")), _parse(inc.first_seen)
        return created is not None and first is not None and created >= first

    def _heartbeat(self, now: datetime, sha: str) -> None:
        last = _parse(self._store.kv_get("last_heartbeat_at"))
        if last is not None and now - last < timedelta(minutes=self._cfg.heartbeat_minutes):
            return
        body = f"last_seen: {_z(now)}, sha: {safe_token(sha)}, next_run: {_z(next_run(self._cfg, now))}"
        n, labels = self._gh.heartbeat(body)
        self._store.kv_set("last_heartbeat_at", iso_utc(now))
        today = now.astimezone(zone(ACTIONS_TZ)).date()
        for label in labels:  # 오늘(서울) 표시는 남겨 같은 날 두 번째 알림을 막는다
            m = _STALE_RE.match(label)
            if m is None:
                continue
            try:
                day = date.fromisoformat(m[1])
            except ValueError:  # stale-2026-13-45 같은 틀만 맞는 라벨은 건드리지 않는다
                continue
            if day < today:
                self._gh.remove_label(n, label)

    def _import_actions(self, now: datetime) -> None:
        """Actions가 연 `vercel:`·`ci:main` 이슈를 `open`으로 들인다(30분마다)."""
        last = _parse(self._store.kv_get("last_import_at"))
        if last is not None and now - last < IMPORT_EVERY:
            return
        for issue in self._gh.open_incidents():
            title = str(issue.get("title", ""))
            if not title.startswith(_TITLE_PREFIX):
                continue
            fp, n = title[len(_TITLE_PREFIX):], int(issue["number"])
            if not _is_imported(fp):
                continue
            have = self._store.get(fp)
            if have is not None and (have.state != "resolved" or have.issue_number == n):
                continue
            at = _parse(str(issue.get("created_at", "")).replace("Z", "+00:00")) or now
            part = "ci" if fp == CI_MAIN else "vercel"
            self._store.upsert_signal(Signal(fp, part, "health", at), now)  # kind는 저장되지 않는다
            self._store.set_state(
                fp, "open", issue_number=n, count=1, first_seen=iso_utc(at), last_seen=iso_utc(at),
                synced_count=1, last_synced_at=iso_utc(now), resolved_at=None, failures=0,
                detail={"kind": _ACTIONS_KIND},
            )
        self._store.kv_set("last_import_at", iso_utc(now))

    def _resolve_ci_main(self, now: datetime) -> None:
        """`main` 머리 커밋의 `ci`가 성공이면 `ci:main` 장애를 닫는다."""
        inc = self._store.get(CI_MAIN)
        if inc is None or inc.state == "resolved" or inc.issue_number is None:
            return
        sha = self._gh.head_sha("main")
        if self._gh.ci_conclusion(sha) != "success":
            return
        # 댓글 → 닫기 → resolved. 어느 단계가 실패해도 resolved가 아니라 다음 회차에 다시 한다
        self._gh.comment(inc.issue_number, FIXED_COMMENT.format(sha=safe_token(sha)[:12]))
        self._gh.close(inc.issue_number)
        self._store.set_state(CI_MAIN, "resolved", resolved_at=iso_utc(now))
        self._notify_ci_fixed(inc.issue_number)

    def _notify_ci_fixed(self, n: int) -> None:
        """결과 알림 한 번(6장 "고침" 틀). 수리 PR이 있으면 그 제목·링크, 없으면 위 제목과 이슈 링크."""
        try:
            try:
                pr = self._gh.pr_for_issue(n)
            except GitHubUnavailable:
                pr = None
            title, url = pr or (CI_FIXED_TITLE, self._gh.issue_url(n))
            self._notifier.fixed(title, url)
        except Exception as exc:  # noqa: BLE001 - 알림 때문에 상태가 어긋나면 안 된다
            log.warning("notify_failed %s", type(exc).__name__)
