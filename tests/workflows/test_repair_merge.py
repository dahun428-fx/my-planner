"""repair.yml 머지 단계 (스펙 4.3). CI 확인은 Claude가 아니라 이 셸 단계가 `GET /actions/runs`로 직접 한다."""

from __future__ import annotations

import gh
import repair_merge
from medic.fakes import FakeGitHub, FakeHttp


class Ticker:
    """가짜 시계와 sleep. sleep할 때마다 `on_sleep`을 부른다(그 사이 CI가 끝나는 것을 흉내)."""

    def __init__(self, on_sleep=None) -> None:
        self.t = 0.0
        self.on_sleep = on_sleep
        self.sleeps = 0

    def now(self) -> float:
        return self.t

    def sleep(self, s: float) -> None:
        self.t += s
        self.sleeps += 1
        if self.on_sleep:
            self.on_sleep(self.sleeps)


def _env():
    server = FakeGitHub()
    http = FakeHttp(route=server.route)
    return server, http, gh.Api("tok", "o/r", http=http)


def _run(sha: str, status: str, conclusion: str | None, *, event: str = "pull_request", rid: int = 1) -> dict:
    return {"id": rid, "name": "ci", "head_sha": sha, "event": event, "status": status, "conclusion": conclusion,
            "created_at": f"2026-10-26T00:0{rid}:00Z"}


def test_merge_waits_for_ci_then_squashes_with_repairs_body():
    server, _http, api = _env()
    n = server.add_issue("[incident] be:KeyError src/x.py:f", ["incident", "be", "repairing"])
    pr = server.add_pull(f"auto-repair/{n}-1", head_sha="abc")
    run = _run("abc", "in_progress", None)
    server.runs.append(run)

    def finish(k: int) -> None:
        if k == 2:
            run.update(status="completed", conclusion="success")

    tick = Ticker(finish)
    assert repair_merge.merge(api, pr, n, wait_s=1800, poll_s=30, sleep=tick.sleep, clock=tick.now) == "merged"
    assert tick.sleeps == 2
    assert server.merges == [(pr, {"merge_method": "squash", "commit_message": f"Repairs #{n}", "sha": "abc"})]
    assert "merged" in server.labels(n) and "repairing" not in server.labels(n)
    assert "auto-repair" in [x["name"] for x in server.pull(pr)["labels"]]  # 하루 머지 수를 세는 라벨


def test_merge_ci_failure_returns_ci_failed():
    server, _, api = _env()
    n = server.add_issue("[incident] be:KeyError src/x.py:f", ["incident", "repairing"])
    pr = server.add_pull(f"auto-repair/{n}-1", head_sha="abc")
    server.runs.append(_run("abc", "completed", "failure"))
    tick = Ticker()
    assert repair_merge.merge(api, pr, n, sleep=tick.sleep, clock=tick.now) == "ci_failed"
    assert server.merges == []
    assert "repairing" in server.labels(n)


def test_merge_timeout_when_ci_never_finishes():
    server, _, api = _env()
    n = server.add_issue("[incident] be:KeyError src/x.py:f", ["incident", "repairing"])
    pr = server.add_pull(f"auto-repair/{n}-1", head_sha="abc")  # 실행이 아직 없다
    tick = Ticker()
    assert repair_merge.merge(api, pr, n, wait_s=120, poll_s=30, sleep=tick.sleep, clock=tick.now) == "timeout"
    assert server.merges == []


def test_merge_does_not_use_required_checks():
    server, http, api = _env()
    n = server.add_issue("[incident] be:KeyError src/x.py:f", ["incident", "repairing"])
    pr = server.add_pull(f"auto-repair/{n}-1", head_sha="abc")
    server.runs.append(_run("abc", "completed", "success"))
    tick = Ticker()
    repair_merge.merge(api, pr, n, sleep=tick.sleep, clock=tick.now)
    paths = [r.path for r in http.requests]
    assert not any("/check-suites" in p or "/check-runs" in p for p in paths)
    runs = [r for r in http.requests if r.path == "/repos/o/r/actions/runs"]
    assert runs and runs[0].query == {"head_sha": "abc", "event": "pull_request", "per_page": "100"}


def test_ci_state_uses_newest_run_and_ignores_other_workflows():
    server, _, api = _env()
    server.runs += [
        _run("abc", "completed", "failure", rid=1),
        _run("abc", "completed", "success", rid=2),
        {**_run("abc", "completed", "failure", rid=3), "name": "promote"},
    ]
    assert repair_merge.ci_state(api, "abc") == "success"


def test_find_pr_by_branch_prefix():
    server, _, api = _env()
    server.add_pull("auto-repair/12-1", state="closed")
    newer = server.add_pull("auto-repair/12-2")
    server.add_pull("auto-repair/120-1")
    server.add_pull("auto-repair/12-3", base="develop")
    assert repair_merge.find_pr(api, 12)["number"] == newer
    assert repair_merge.find_pr(api, 13) is None


def test_settle_abandons_failed_attempt():
    server, _, api = _env()
    n = server.add_issue("[incident] be:KeyError src/x.py:f", ["incident", "repairing", "failed-1"])
    pr = server.add_pull(f"auto-repair/{n}-2", head_sha="abc")
    assert repair_merge.settle(api, n, "ci_failed") == "abandoned"
    assert server.pull(pr)["state"] == "closed"
    assert server.deleted_refs == [f"auto-repair/{n}-2"]
    assert "failed-2" in server.labels(n) and "repairing" not in server.labels(n)


def test_settle_no_pr_counts_as_failure():
    server, _, api = _env()
    n = server.add_issue("[incident] be:KeyError src/x.py:f", ["incident", "repairing"])
    assert repair_merge.settle(api, n, "no_pr") == "abandoned"
    assert "failed-1" in server.labels(n)


def test_settle_keeps_merged_and_timeout():
    server, _, api = _env()
    n = server.add_issue("[incident] be:KeyError src/x.py:f", ["incident", "repairing"])
    assert repair_merge.settle(api, n, "timeout") == "kept"  # repairing을 두면 sweep이 머지만 다시 한다
    assert repair_merge.settle(api, n, "merged") == "kept"
    assert server.labels(n) == ["incident", "repairing"]
