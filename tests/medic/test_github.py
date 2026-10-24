from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from my_planner_medic.github import GitHub, GitHubUnavailable
from my_planner_medic.http import UrllibHttp

from .fakes import FakeGitHub, FakeHttp, FakeResponse

REPO = "o/r"
ISSUES = f"/repos/{REPO}/issues"


def make() -> tuple[GitHub, FakeGitHub, FakeHttp]:
    server = FakeGitHub(REPO)
    http = FakeHttp(route=server.route)
    return GitHub(http, "tok", REPO), server, http


# --- 요청 모양과 실패 분류 --------------------------------------------------------


def test_requests_carry_api_headers_and_base() -> None:
    gh, _, http = make()
    gh.open_incident("be:KeyError x.py:f", "be", "body")
    req = http.requests[-1]
    assert req.url == f"https://api.github.com{ISSUES}"
    assert req.headers["Authorization"] == "Bearer tok"
    assert req.headers["Accept"] == "application/vnd.github+json"
    assert req.headers["X-GitHub-Api-Version"] == "2022-11-28"


@pytest.mark.parametrize(
    ("status", "headers", "kind"),
    [
        (0, {}, "network"),
        (401, {}, "auth"),
        (403, {"x-ratelimit-remaining": "0"}, "rate_limit"),
        (403, {"X-RateLimit-Remaining": "0"}, "rate_limit"),
        (403, {"x-ratelimit-remaining": "4999"}, "auth"),
        (429, {}, "rate_limit"),
        (500, {}, "server"),
        (503, {}, "server"),
    ],
)
def test_failures_raise_unavailable_with_kind(status: int, headers: dict[str, str], kind: str) -> None:
    gh, _, http = make()
    http.queue("POST", ISSUES, FakeResponse(status, None, headers))
    with pytest.raises(GitHubUnavailable) as err:
        gh.open_incident("fp", "be", "b")
    assert err.value.kind == kind


# --- 이슈 -------------------------------------------------------------------


def test_open_incident_labels_part_and_record_only() -> None:
    gh, server, _ = make()
    n = gh.open_incident("be:KeyError x.py:f", "be", "body")
    assert server.issues[n]["title"] == "[incident] be:KeyError x.py:f"
    assert server.labels(n) == ["incident", "be"]
    m = gh.open_incident("health:safe_mode", "record", "body")
    assert server.labels(m) == ["record"]


def test_find_incident_matches_title_in_incident_and_record_lists_without_search() -> None:
    gh, server, http = make()
    server.add_issue("[incident] other", ["incident"])
    old = server.add_issue("[incident] be:X a.py:f", ["incident", "be"], state="closed")
    rec = server.add_issue("[incident] health:safe_mode", ["record"])
    assert gh.find_incident("be:X a.py:f")["number"] == old
    assert gh.find_incident("health:safe_mode")["number"] == rec
    assert gh.find_incident("nope") is None
    assert not [r for r in http.requests if "/search/" in r.path]
    queries = [r.query for r in http.requests if r.path == ISSUES]
    assert {"labels": "incident", "state": "all", "per_page": "100"} in queries
    assert {"labels": "record", "state": "all", "per_page": "100"} in queries


def test_find_incident_prefers_newest_of_same_title() -> None:
    gh, server, _ = make()
    server.add_issue("[incident] fp", ["incident"], state="closed")
    new = server.add_issue("[incident] fp", ["incident"])
    assert gh.find_incident("fp")["number"] == new


def test_issue_edits() -> None:
    gh, server, _ = make()
    n = gh.open_incident("fp", "app", "b1")
    gh.update_body(n, "b2")
    gh.close(n)
    assert (server.issues[n]["body"], server.issues[n]["state"]) == ("b2", "closed")
    gh.reopen(n, ["recurred"])
    assert server.issues[n]["state"] == "open"
    assert server.labels(n) == ["incident", "app", "recurred"]
    gh.add_labels(n, ["x", "y"])
    gh.remove_label(n, "x")
    gh.remove_label(n, "not-there")  # 404는 이미 없는 것이라 괜찮다
    assert server.labels(n) == ["incident", "app", "recurred", "y"]
    gh.comment(n, "hi")
    assert server.comments[n] == ["hi"]


def test_heartbeat_creates_once_then_edits_body() -> None:
    gh, server, _ = make()
    n, labels = gh.heartbeat("last_seen: a")
    assert server.issues[n]["title"] == "heartbeat"
    assert labels == ["heartbeat"]
    server.issues[n]["labels"].append({"name": "stale-2026-10-26"})
    m, labels = gh.heartbeat("last_seen: b")
    assert m == n
    assert server.issues[n]["body"] == "last_seen: b"
    assert labels == ["heartbeat", "stale-2026-10-26"]
    assert len(server.issues) == 1


# --- CI·상태·커밋 ------------------------------------------------------------


def test_ci_conclusion_reads_ci_push_runs_only() -> None:
    gh, server, http = make()
    assert gh.ci_conclusion("s0") == "unknown"
    server.runs += [
        {"name": "other", "head_sha": "s1", "event": "push", "status": "completed", "conclusion": "failure"},
        {"name": "ci", "head_sha": "s1", "event": "push", "status": "completed", "conclusion": "success"},
        {"name": "ci", "head_sha": "s2", "event": "push", "status": "in_progress", "conclusion": None},
        {"name": "ci", "head_sha": "s3", "event": "push", "status": "completed", "conclusion": "failure"},
        {"name": "ci", "head_sha": "s4", "event": "pull_request", "status": "completed", "conclusion": "success"},
    ]
    assert [gh.ci_conclusion(s) for s in ("s1", "s2", "s3", "s4")] == ["success", "pending", "failure", "unknown"]
    assert http.requests[-1].query == {"head_sha": "s4", "event": "push", "per_page": "100"}
    http.outage = 502
    with pytest.raises(GitHubUnavailable):
        gh.ci_conclusion("s1")  # 조회 실패는 "unknown"이 아니라 예외


def test_commit_state_by_context_prefix() -> None:
    gh, server, _ = make()
    server.statuses["s"] = [
        {"context": "ci/other", "state": "failure"},
        {"context": "Vercel – app", "state": "success"},
    ]
    assert gh.commit_state("s", "Vercel") == "success"
    assert gh.commit_state("s", "nothing") == "unknown"


def test_repairs_in_range_reads_commit_messages() -> None:
    gh, server, _ = make()
    server.compares[("a", "b")] = ["fix x\n\nRepairs #12", "docs", "y (#40)\n\nRepairs #7\nRepairs #12", "Repairs #123x"]
    assert gh.repairs_in_range("a", "b") == [12, 7]


def test_pr_for_issue_finds_merged_repair_pr() -> None:
    gh, server, _ = make()
    server.pulls += [
        {"state": "closed", "merged_at": None, "body": "Repairs #5", "title": "no", "html_url": "u0"},
        {"state": "closed", "merged_at": "2026-10-26T00:00:00Z", "body": "Repairs #51", "title": "no", "html_url": "u1"},
        {"state": "closed", "merged_at": "2026-10-26T00:00:00Z", "body": "Repairs #5\n원인…", "title": "fix", "html_url": "u2"},
    ]
    assert gh.pr_for_issue(5) == ("fix", "u2")
    assert gh.pr_for_issue(9) is None


def test_head_sha_of_branch() -> None:
    gh, server, _ = make()
    server.branches["main"] = "abc"
    assert gh.head_sha("main") == "abc"


# --- 진짜 urllib ------------------------------------------------------------


class _Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", 0))
        got = json.loads(self.rfile.read(length))
        body = json.dumps({"got": got, "auth": self.headers.get("Authorization")}).encode()
        code = 503 if self.path == "/fail" else 201
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("X-RateLimit-Remaining", "7")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: object) -> None:
        pass


@pytest.fixture
def server_url() -> Iterator[str]:
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        yield f"http://127.0.0.1:{srv.server_address[1]}"
    finally:
        srv.shutdown()
        srv.server_close()


def test_urllib_http_round_trip_and_error_status(server_url: str) -> None:
    http = UrllibHttp()
    status, body, headers = http.request("POST", server_url + "/ok", headers={"Authorization": "Bearer t"}, json={"a": 1})
    assert status == 201
    assert body == {"got": {"a": 1}, "auth": "Bearer t"}
    assert headers["x-ratelimit-remaining"] == "7"
    assert http.request("POST", server_url + "/fail", json={})[0] == 503


def test_urllib_http_connection_failure_is_zero(caplog: pytest.LogCaptureFixture) -> None:
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    port = srv.server_address[1]
    srv.server_close()  # 닫힌 포트
    status, body, headers = UrllibHttp().request(
        "GET", f"http://127.0.0.1:{port}/health?x=1", headers={"Authorization": "Bearer SECRET"}, timeout=2
    )
    assert (status, body, headers) == (0, None, {})
    assert "SECRET" not in caplog.text
    assert "x=1" not in caplog.text
