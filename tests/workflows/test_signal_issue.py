"""signal.yml: Vercel `status`와 main `ci` 실패 `workflow_run`을 장애 이슈로 (스펙 3.1, 3.5)."""

from __future__ import annotations

from datetime import UTC, datetime

import gh
import signal_issue
from medic.fakes import FakeGitHub, FakeHttp

NOW = datetime(2026, 10, 26, 1, 0, tzinfo=UTC)


def _status(**kw):
    ev = {
        "sha": "abc1234def", "state": "failure", "context": "Vercel – my-planner-app",
        "branches": [{"name": "main"}, {"name": "develop"}],
    }
    ev.update(kw)
    return ev


def _run(**kw):
    wr = {"name": "ci", "conclusion": "failure", "head_branch": "main", "event": "push", "head_sha": "abc", "id": 9}
    wr.update(kw)
    return {"workflow_run": wr}


def test_status_event_to_fingerprint():
    assert signal_issue.from_status(_status()) == "vercel:Vercel – my-planner-app"


def test_status_event_ignores_non_failure_non_vercel_and_develop_only():
    assert signal_issue.from_status(_status(state="success")) is None
    assert signal_issue.from_status(_status(state="error")) is None
    assert signal_issue.from_status(_status(context="staging/be")) is None
    # develop 미리보기만 담은 커밋은 장애가 아니다
    assert signal_issue.from_status(_status(branches=[{"name": "develop"}])) is None
    assert signal_issue.from_status(_status(branches=[])) is None


def test_workflow_run_failure_on_main_to_ci_main():
    assert signal_issue.from_workflow_run(_run()) == "ci:main"


def test_workflow_run_ignores_success_other_branch_and_pull_request():
    # already_green으로 작업을 건너뛴 main 실행은 success로 끝난다
    assert signal_issue.from_workflow_run(_run(conclusion="success")) is None
    assert signal_issue.from_workflow_run(_run(conclusion="cancelled")) is None
    assert signal_issue.from_workflow_run(_run(head_branch="develop")) is None
    assert signal_issue.from_workflow_run(_run(event="pull_request")) is None
    assert signal_issue.from_workflow_run(_run(name="promote")) is None


def test_new_fingerprint_opens_incident_issue():
    server = FakeGitHub()
    api = gh.Api("tok", "o/r", http=FakeHttp(route=server.route))
    n = signal_issue.ensure_issue(api, "ci:main", "ci", now=NOW, sha="abc1234def", run_id=9)
    issue = server.issues[n]
    assert issue["title"] == "[incident] ci:main"
    assert server.labels(n) == ["incident"]  # 조각 라벨은 be/app/dashboard만
    assert "abc1234def" in issue["body"] and "ci:main" in issue["body"]


def test_existing_open_issue_gets_comment():
    server = FakeGitHub()
    api = gh.Api("tok", "o/r", http=FakeHttp(route=server.route))
    old = server.add_issue("[incident] vercel:Vercel – my-planner-app", ["incident"], state="closed")
    n = server.add_issue("[incident] vercel:Vercel – my-planner-app", ["incident", "repairing"])
    got = signal_issue.ensure_issue(api, "vercel:Vercel – my-planner-app", "vercel", now=NOW, sha="abc1234def")
    assert got == n
    assert len(server.issues) == 2 and old in server.issues
    assert len(server.comments[n]) == 1 and "abc1234" in server.comments[n][0]
