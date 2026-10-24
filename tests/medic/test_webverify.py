from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from my_planner_medic.github import GitHub
from my_planner_medic.signals import Signal
from my_planner_medic.store import MedicStore
from my_planner_medic.webverify import WebVerifier

from .fakes import FakeClock, FakeGitHub, FakeHttp, FakeNotifier, make_config

REPO = "o/r"
START = datetime(2026, 10, 26, 1, 0, tzinfo=UTC)
APP_FP = "app:TypeError app.js:1:1"
VERCEL_FP = "vercel:Vercel – app"
SUCCESS = [{"context": "Vercel – app", "state": "success"}]
PENDING = [{"context": "Vercel – app", "state": "pending"}]


@dataclass
class Env:
    clock: FakeClock
    server: FakeGitHub
    http: FakeHttp
    store: MedicStore
    notifier: FakeNotifier
    verifier: WebVerifier

    def merged(self, fp: str, part: str, labels: list[str] | None = None) -> int:
        n = self.server.add_issue(f"[incident] {fp}", ["incident", part, "merged", *(labels or [])])
        self.store.upsert_signal(Signal(fp, part, "client_error", self.clock.now()), self.clock.now())
        self.store.set_state(fp, "merged", issue_number=n)
        self.server.pulls.append({
            "state": "closed", "merged_at": "2026-10-26T00:50:00Z", "title": "fix: 앱 오류",
            "body": f"Repairs #{n}", "html_url": f"https://github.com/{REPO}/pull/9",
        })
        return n

    def recur(self, fp: str, part: str) -> None:
        self.store.upsert_signal(Signal(fp, part, "client_error", self.clock.now()), self.clock.now())

    def vercel(self, sha: str, statuses: list[dict[str, str]]) -> None:
        self.server.statuses[sha] = statuses


def make(tmp_path: Path) -> Env:
    clock = FakeClock(START)
    server = FakeGitHub(REPO, clock)
    server.branches["main"] = "sha1"
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


def test_newer_main_commit_with_success_counts(tmp_path: Path) -> None:
    e = make(tmp_path)
    e.merged(APP_FP, "dashboard")
    e.store.set_state(APP_FP, "merged")
    e.verifier.tick()  # sha1을 잡는다
    e.server.branches["main"] = "sha2"
    e.vercel("sha2", SUCCESS)
    e.clock.advance(minutes=1)
    e.verifier.tick()
    assert e.store.get(APP_FP).detail["web"]["ok_at"] is not None


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
    assert "web" not in inc.detail
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
    e.verifier.tick()  # 예외 없이, 상태 그대로
    assert e.store.get(APP_FP).state == "merged"
