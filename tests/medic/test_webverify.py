from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from my_planner_medic.github import GitHub
from my_planner_medic.signals import Signal
from my_planner_medic.store import MedicStore
from my_planner_medic.webverify import WebVerifier

from .fakes import FakeClock, FakeGitHub, FakeHttp, FakeNotifier, make_config

REPO = "o/r"
START = datetime(2026, 10, 26, 1, 0, tzinfo=UTC)
APP_CTX = "Vercel – my-planner"  # 실제 컨텍스트(promote_check, 릴리스 흐름 스펙 6.2 5)
DASH_CTX = "Vercel – my-planner-dashboard"
APP_FP = "app:TypeError app.js:1:1"
DASH_FP = "dashboard:TypeError d.js:1:1"
VERCEL_FP = f"vercel:{APP_CTX}"
OTHER_FP = "vercel:Vercel – other"  # 폴더를 모르는 컨텍스트
BOT = {"login": "vercel[bot]"}


def st(context: str, state: str, creator: dict[str, str] | None = None) -> dict[str, Any]:
    return {"context": context, "state": state, "creator": BOT if creator is None else creator}


SUCCESS = [st(APP_CTX, "success")]
PENDING = [st(APP_CTX, "pending")]


@dataclass
class Env:
    clock: FakeClock
    server: FakeGitHub
    http: FakeHttp
    store: MedicStore
    notifier: FakeNotifier
    verifier: WebVerifier

    def merged(
        self, fp: str, part: str, labels: list[str] | None = None, *, repair_sha: str | None = "sha1",
        state: str = "open",
    ) -> int:
        """업데이터가 `Repairs #N` 커밋(`repair_sha`)을 보고 `merged`로 둔 웹 장애."""
        n = self.server.add_issue(f"[incident] {fp}", ["incident", part, "merged", *(labels or [])], state=state)
        self.store.upsert_signal(Signal(fp, part, "client_error", self.clock.now()), self.clock.now())
        detail = {"repair_sha": repair_sha} if repair_sha else {}
        self.store.set_state(fp, "merged", issue_number=n, detail=detail)
        self.server.pulls.append({
            "state": "closed", "merged_at": "2026-10-26T00:50:00Z", "title": "fix: 앱 오류",
            "body": f"Repairs #{n}", "html_url": f"https://github.com/{REPO}/pull/9",
        })
        return n

    def recur(self, fp: str, part: str) -> None:
        self.store.upsert_signal(Signal(fp, part, "client_error", self.clock.now()), self.clock.now())

    def vercel(self, sha: str, statuses: list[dict[str, Any]]) -> None:
        self.server.statuses[sha] = statuses

    def main_moves(self, head: str, later: list[str], *, touched: dict[str, list[str]] | None = None) -> None:
        """main이 `sha1`(수리 커밋) 뒤로 `later`(오래된 것부터)만큼 나아갔다. `touched`: 폴더 → 바꾼 커밋(새 것부터)."""
        self.server.branches["main"] = head
        self.server.compares[("sha1", head)] = [(c, "chore") for c in later]
        for path, shas in (touched or {}).items():
            self.server.path_commits[path] = shas

    def ok_at(self, fp: str) -> Any:
        return self.store.get(fp).detail["web"]["ok_at"]


def make(tmp_path: Path) -> Env:
    clock = FakeClock(START)
    server = FakeGitHub(REPO, clock)
    server.branches["main"] = "sha1"
    server.path_commits = {"web/app": ["sha1"], "web/dashboard": ["sha1"]}
    http = FakeHttp(route=server.route)
    store = MedicStore(tmp_path / "state" / "medic.db")
    notifier = FakeNotifier()
    verifier = WebVerifier(make_config(tmp_path, repo=REPO), store, GitHub(http, "t", REPO), notifier, clock)
    return Env(clock, server, http, store, notifier, verifier)


def test_web_incident_resolves_after_vercel_success_and_quiet_hour(tmp_path: Path) -> None:
    e = make(tmp_path)
    n = e.merged(APP_FP, "app")
    e.vercel("sha1", PENDING)
    e.verifier.tick()
    assert e.store.get(APP_FP).state == "merged"
    e.clock.advance(minutes=30)
    e.recur(APP_FP, "app")  # 옛 빌드가 낸 에러: Vercel 성공 전이라 세지 않는다
    e.verifier.tick()
    assert e.store.get(APP_FP).state == "merged" and e.store.get(APP_FP).failures == 0
    e.vercel("sha1", SUCCESS)
    e.clock.advance(minutes=1)
    e.verifier.tick()
    assert e.store.get(APP_FP).state == "merged"  # 이제부터 60분
    e.clock.advance(minutes=59)
    e.verifier.tick()
    assert e.store.get(APP_FP).state == "merged"
    assert e.server.issues[n]["state"] == "open"
    e.clock.advance(minutes=1)
    e.verifier.tick()
    inc = e.store.get(APP_FP)
    assert inc.state == "resolved" and inc.resolved_at is not None
    assert e.server.issues[n]["state"] == "closed"
    assert e.notifier.fixed_calls == [("fix: 앱 오류", f"https://github.com/{REPO}/pull/9")]
    e.clock.advance(minutes=5)
    e.verifier.tick()
    assert len(e.notifier.fixed_calls) == 1


def test_vercel_fingerprint_resolves_on_success_only(tmp_path: Path) -> None:
    e = make(tmp_path)
    n = e.merged(VERCEL_FP, "vercel")
    e.vercel("sha1", PENDING)
    for _ in range(3):
        e.clock.advance(minutes=30)
        e.verifier.tick()
    assert e.store.get(VERCEL_FP).state == "merged"  # 60분이 지나도 성공 전에는 안 닫는다
    e.vercel("sha1", SUCCESS)
    e.clock.advance(minutes=1)
    e.verifier.tick()
    assert e.store.get(VERCEL_FP).state == "resolved"  # 조용한 시간 없이 바로
    assert e.server.issues[n]["state"] == "closed"
    assert len(e.notifier.fixed_calls) == 1


def test_recurrence_during_web_verify_counts_failure(tmp_path: Path) -> None:
    e = make(tmp_path)
    n = e.merged(APP_FP, "app", labels=["failed-1"])
    e.vercel("sha1", SUCCESS)
    e.verifier.tick()
    e.clock.advance(minutes=20)
    e.recur(APP_FP, "app")
    e.verifier.tick()
    inc = e.store.get(APP_FP)
    assert inc.state == "open" and inc.failures == 2
    assert "web" not in inc.detail and "repair_sha" not in inc.detail
    labels = e.server.labels(n)
    assert "merged" not in labels and {"recurred", "failed-2", "failed-1"} <= set(labels)
    assert e.notifier.fixed_calls == [] and e.server.issues[n]["state"] == "open"
    e.clock.advance(minutes=90)
    e.verifier.tick()
    assert e.store.get(APP_FP).state == "open"


def test_no_vercel_success_in_3h_counts_failure(tmp_path: Path) -> None:
    e = make(tmp_path)
    n = e.merged(APP_FP, "app")
    e.vercel("sha1", PENDING)
    e.verifier.tick()
    e.clock.advance(hours=2, minutes=59)
    e.verifier.tick()
    assert e.store.get(APP_FP).state == "merged"
    e.clock.advance(minutes=1)
    e.verifier.tick()
    inc = e.store.get(APP_FP)
    assert inc.state == "open" and inc.failures == 1
    labels = e.server.labels(n)
    assert "merged" not in labels and "failed-1" in labels and "recurred" not in labels
    assert e.notifier.fixed_calls == []


def test_be_incidents_and_github_outage_are_left_alone(tmp_path: Path) -> None:
    e = make(tmp_path)
    e.merged("be:KeyError x.py:f", "be")
    e.merged(APP_FP, "app")
    e.verifier.tick()
    assert "web" not in e.store.get("be:KeyError x.py:f").detail
    e.http.outage = 503
    e.clock.advance(hours=4)
    before = len(e.http.requests)
    e.verifier.tick()  # 예외 없이, 상태 그대로
    assert e.store.get(APP_FP).state == "merged"
    assert len(e.http.requests) - before == 1  # 첫 장애에서 멈춘다(다음 장애로 넘어가지 않는다)


def test_lost_label_response_does_not_double_count_failure(tmp_path: Path) -> None:
    e = make(tmp_path)
    n = e.merged(APP_FP, "app")
    e.vercel("sha1", SUCCESS)
    e.verifier.tick()
    e.clock.advance(minutes=20)
    e.recur(APP_FP, "app")
    e.http.lose_next("POST", f"/repos/{REPO}/issues/{n}/labels")  # 적용은 되고 응답만 끊김
    e.verifier.tick()
    assert e.store.get(APP_FP).state == "merged"
    assert "failed-1" in e.server.labels(n)
    e.verifier.tick()  # 다음 회차
    labels = e.server.labels(n)
    assert "failed-2" not in labels and labels.count("recurred") == 1
    assert e.store.get(APP_FP).state == "open" and e.store.get(APP_FP).failures == 1
    removed = [r for r in e.http.calls("DELETE", f"/repos/{REPO}/issues/{n}/labels/recurred")]
    assert len(removed) == 1  # `recurred`를 다시 떼고 달지 않는다(두 번째 `labeled` 방지)


# --- 최종 리뷰 I-3: 맞는 컨텍스트, 맞는 커밋 ---------------------------------------


def test_app_incident_checks_exactly_the_app_context(tmp_path: Path) -> None:
    """`app` 낱말은 `Vercel – my-planner`에 없다: 예전에는 모든 `Vercel*`(대시보드 포함)이 성공이어야 했다."""
    e = make(tmp_path)
    e.merged(APP_FP, "app")
    e.vercel("sha1", [st(DASH_CTX, "failure"), st(APP_CTX, "pending")])
    e.verifier.tick()
    assert e.ok_at(APP_FP) is None
    e.vercel("sha1", [st(DASH_CTX, "failure"), st(APP_CTX, "success")])  # 대시보드가 깨져도 앱 수리는 확인된다
    e.clock.advance(minutes=1)
    e.verifier.tick()
    assert e.ok_at(APP_FP) is not None


def test_dashboard_incident_checks_exactly_the_dashboard_context(tmp_path: Path) -> None:
    """`Vercel – my-planner`는 `Vercel – my-planner-dashboard`의 접두지만 맞지 않는다(정확히 같아야)."""
    e = make(tmp_path)
    e.merged(DASH_FP, "dashboard")
    e.vercel("sha1", [st(APP_CTX, "success"), st(DASH_CTX, "pending")])
    e.verifier.tick()
    assert e.ok_at(DASH_FP) is None
    e.vercel("sha1", [st(APP_CTX, "pending"), st(DASH_CTX, "success")])
    e.verifier.tick()
    assert e.ok_at(DASH_FP) is not None


def test_contexts_come_from_config(tmp_path: Path) -> None:
    e = make(tmp_path)
    cfg = make_config(tmp_path, repo=REPO, vercel_context_app="Vercel – planner-web")
    e.verifier = WebVerifier(cfg, e.store, GitHub(e.http, "t", REPO), e.notifier, e.clock)
    e.merged(APP_FP, "app")
    e.vercel("sha1", [st(APP_CTX, "success"), st("Vercel – planner-web", "pending")])
    e.verifier.tick()
    assert e.ok_at(APP_FP) is None
    e.vercel("sha1", [st("Vercel – planner-web", "success")])
    e.verifier.tick()
    assert e.ok_at(APP_FP) is not None


def test_only_vercel_bot_statuses_count(tmp_path: Path) -> None:
    e = make(tmp_path)
    e.merged(APP_FP, "app")
    e.vercel("sha1", [st(APP_CTX, "pending"), st(APP_CTX, "success", {"login": "someone"})])  # 가짜가 더 새 것
    e.verifier.tick()
    assert e.ok_at(APP_FP) is None
    e.vercel("sha1", [st(APP_CTX, "success", {"login": "someone"}), st(APP_CTX, "success")])
    e.verifier.tick()
    assert e.ok_at(APP_FP) is not None


def test_newest_bot_status_wins(tmp_path: Path) -> None:
    e = make(tmp_path)
    e.merged(APP_FP, "app")
    e.vercel("sha1", [st(APP_CTX, "success"), st(APP_CTX, "pending")])  # 다시 빌드 중
    e.verifier.tick()
    assert e.ok_at(APP_FP) is None


def test_later_head_that_did_not_touch_the_folder_checks_the_repair_commit(tmp_path: Path) -> None:
    """main이 앱을 안 바꾼 커밋으로 나아갔다(그 커밋엔 앱 상태가 없다): 수리 커밋의 앱 배포를 본다.
    예전에는 머리의 대시보드 성공만으로 확인되었다."""
    e = make(tmp_path)
    e.merged(APP_FP, "app")
    e.main_moves("sha3", ["sha2", "sha3"], touched={"web/app": ["sha1", "old"], "web/dashboard": ["sha3"]})
    e.vercel("sha3", [st(DASH_CTX, "success")])
    e.vercel("sha1", [st(APP_CTX, "pending")])
    e.verifier.tick()
    assert e.ok_at(APP_FP) is None
    e.vercel("sha1", [st(APP_CTX, "success")])
    e.verifier.tick()
    assert e.ok_at(APP_FP) is not None


def test_later_commit_that_touched_the_folder_is_what_is_live(tmp_path: Path) -> None:
    """수리 뒤 앱을 또 바꾼 커밋이 있으면 Vercel 운영은 그 커밋이다: 그 배포를 본다(promote_check의 W)."""
    e = make(tmp_path)
    e.merged(APP_FP, "app")
    e.main_moves("sha3", ["sha2", "sha3"], touched={"web/app": ["sha2", "sha1"]})
    e.vercel("sha1", SUCCESS)
    e.vercel("sha2", PENDING)
    e.verifier.tick()
    assert e.ok_at(APP_FP) is None
    e.vercel("sha2", SUCCESS)
    e.verifier.tick()
    assert e.ok_at(APP_FP) is not None


def test_repair_that_did_not_touch_the_folder_skips_the_vercel_wait(tmp_path: Path) -> None:
    """재리뷰 I-4 장면 A: 수리가 웹 폴더를 안 바꿨다(BE에서 고친 앱 오류). 그 폴더를 바꾼 가장 새 커밋은 지난 승격의
    중간 커밋이라 Vercel 상태가 없다(Vercel은 푸시 머리만 빌드). 다시 빌드할 것이 없으니 기다리지 않고 조용한 60분으로."""
    e = make(tmp_path)
    n = e.merged(APP_FP, "app")
    e.server.path_commits["web/app"] = ["promote-mid", "older"]  # 둘 다 상태 없음
    e.verifier.tick()
    assert e.ok_at(APP_FP) is not None
    e.clock.advance(minutes=60)
    e.verifier.tick()
    assert e.store.get(APP_FP).state == "resolved" and e.server.issues[n]["state"] == "closed"


def test_promote_after_repair_judges_the_push_head_build(tmp_path: Path) -> None:
    """재리뷰 I-4 장면 B: 노트북이 꺼진 사이 앱을 바꾸는 승격(커밋 여러 개, 한 푸시)이 수리 뒤에 들어왔다. W(승격 안에서
    앱을 바꾼 마지막 커밋)에는 상태가 없고 푸시 머리만 있다: W에서 main을 따라 처음 상태가 있는 커밋을 본다."""
    e = make(tmp_path)
    e.merged(APP_FP, "app")
    e.main_moves("p4", ["p1", "p2", "p3", "p4"], touched={"web/app": ["p2", "p1", "sha1"]})
    e.vercel("sha1", [st(APP_CTX, "success")])  # 수리 자체의 배포(지금 운영은 아니다)
    e.vercel("p4", [st(APP_CTX, "pending")])
    e.verifier.tick()
    assert e.ok_at(APP_FP) is None
    e.vercel("p4", [st(APP_CTX, "failure")])
    e.verifier.tick()
    assert e.ok_at(APP_FP) is None
    e.vercel("p4", [st(APP_CTX, "success")])
    e.verifier.tick()
    assert e.ok_at(APP_FP) is not None


def test_repair_in_a_multi_commit_push_judges_the_push_head(tmp_path: Path) -> None:
    """수리 커밋 R 자신도 푸시 머리가 아닐 수 있다(R 뒤 커밋과 함께 한 푸시): R에서 앞으로 걸어 상태를 찾는다."""
    e = make(tmp_path)
    e.merged(APP_FP, "app")
    e.main_moves("sha2", ["sha2"], touched={"web/app": ["sha1"]})
    e.vercel("sha2", [st(APP_CTX, "success")])
    e.verifier.tick()
    assert e.ok_at(APP_FP) is not None


def test_vercel_build_failure_is_not_skipped_when_repair_did_not_touch_the_folder(tmp_path: Path) -> None:
    """`vercel:` 빌드 실패는 새 빌드가 성공해야 고쳐진다: 폴더를 안 바꾼 수리로는 건너뛰지 않는다."""
    e = make(tmp_path)
    e.merged(VERCEL_FP, "vercel")
    e.server.path_commits["web/app"] = ["older"]
    e.vercel("older", [st(APP_CTX, "failure")])
    e.verifier.tick()
    assert e.store.get(VERCEL_FP).state == "merged"


def test_walk_to_the_built_commit_is_bounded(tmp_path: Path) -> None:
    e = make(tmp_path)
    e.merged(APP_FP, "app")
    later = [f"c{i}" for i in range(80)]
    e.main_moves("c79", later, touched={"web/app": ["sha1"]})
    e.vercel("c79", [st(APP_CTX, "success")])  # 50개 너머
    e.verifier.tick()
    assert e.ok_at(APP_FP) is None
    statuses = [r for r in e.http.requests if r.path.endswith("/statuses")]
    assert len(statuses) == 50


def test_web_sha_is_the_repairs_commit_not_main_head(tmp_path: Path) -> None:
    e = make(tmp_path)
    e.main_moves("sha3", ["sha2", "sha3"], touched={"web/app": ["sha1"]})
    e.merged(APP_FP, "app")
    e.verifier.tick()
    assert e.store.get(APP_FP).detail["web"]["sha"] == "sha1"


def test_without_recorded_repair_commit_falls_back_to_main_head(tmp_path: Path) -> None:
    """업그레이드 전 `merged`가 된 장애(수리 커밋을 모른다): 예전처럼 처음 본 main 머리."""
    e = make(tmp_path)
    e.server.branches["main"] = "sha9"
    e.server.path_commits["web/app"] = ["sha9"]
    e.merged(APP_FP, "app", repair_sha=None)
    e.vercel("sha9", SUCCESS)
    e.verifier.tick()
    assert e.store.get(APP_FP).detail["web"]["sha"] == "sha9" and e.ok_at(APP_FP) is not None


def test_vercel_fingerprint_uses_its_own_context(tmp_path: Path) -> None:
    e = make(tmp_path)
    e.merged(f"vercel:{DASH_CTX}", "vercel")
    e.vercel("sha1", [st(APP_CTX, "success"), st(DASH_CTX, "failure")])
    e.verifier.tick()
    assert e.store.get(f"vercel:{DASH_CTX}").state == "merged"
    e.vercel("sha1", [st(DASH_CTX, "success")])
    e.verifier.tick()
    assert e.store.get(f"vercel:{DASH_CTX}").state == "resolved"


def test_unknown_vercel_context_uses_first_commit_with_that_status(tmp_path: Path) -> None:
    """폴더를 모르는 컨텍스트: 수리 커밋부터 차례로, 그 컨텍스트 상태가 처음 있는 커밋을 본다."""
    e = make(tmp_path)
    e.merged(OTHER_FP, "vercel")
    e.main_moves("sha3", ["sha2", "sha3"])
    e.vercel("sha2", [st("Vercel – other", "success")])
    e.vercel("sha3", [st("Vercel – other", "failure")])
    e.verifier.tick()
    assert e.store.get(OTHER_FP).state == "resolved"


def test_unknown_vercel_context_needs_exact_match(tmp_path: Path) -> None:
    e = make(tmp_path)
    e.merged(OTHER_FP, "vercel")
    e.vercel("sha1", [st("Vercel – other-preview", "success")])
    e.verifier.tick()
    assert e.store.get(OTHER_FP).state == "merged"


# --- 최종 리뷰 I-1: 닫힌 이슈는 다시 연다 -----------------------------------------


def test_recurrence_reopens_issue_closed_by_merge(tmp_path: Path) -> None:
    e = make(tmp_path)
    n = e.merged(APP_FP, "app", state="closed")  # 수리 PR의 `Fixes #n`(또는 손)으로 닫혔다
    e.vercel("sha1", SUCCESS)
    e.verifier.tick()
    e.clock.advance(minutes=20)
    e.recur(APP_FP, "app")
    e.verifier.tick()
    assert e.server.issues[n]["state"] == "open"
    assert {"recurred", "failed-1"} <= set(e.server.labels(n))


def test_vercel_timeout_reopens_issue_closed_by_merge(tmp_path: Path) -> None:
    e = make(tmp_path)
    n = e.merged(APP_FP, "app", state="closed")
    e.vercel("sha1", PENDING)
    e.verifier.tick()
    e.clock.advance(hours=3)
    e.verifier.tick()
    assert e.server.issues[n]["state"] == "open" and "failed-1" in e.server.labels(n)
