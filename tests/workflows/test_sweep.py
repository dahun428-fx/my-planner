"""watch.yml의 sweep (스펙 4.3 repair-sweep 규칙): 다시 부르기, 죽은 시도 정리, 머지만 다시."""

from __future__ import annotations

from datetime import UTC, datetime

import gh
import sweep
from medic.fakes import FakeGitHub, FakeHttp

NOW = datetime(2026, 10, 26, 3, 7, tzinfo=UTC)
OLD = "2026-10-26T01:00:00Z"  # 10분보다 오래 전


def _ci(n: int) -> dict:
    return {"path": ".github/workflows/ci.yml", "head_branch": f"auto-repair/{n}-1"}


def _env():
    server = FakeGitHub()
    http = FakeHttp(route=server.route)
    return server, gh.Api("tok", "o/r", http=http)


def _issue(server, title, labels):
    n = server.add_issue(title, labels)
    server.issues[n]["updated_at"] = "2026-10-26T03:06:00Z"  # medic이 본문을 자주 고쳐도 sweep은 막히지 않는다
    return n


def test_sweep_dispatches_idle_incidents():
    server, api = _env()
    n = _issue(server, "[incident] be:A x:f", ["incident", "be"])
    m = _issue(server, "[incident] be:B x:f", ["incident", "failed-2"])  # 한도는 게이트가 본다
    assert sorted(sweep.sweep(api, now=NOW)) == sorted([("dispatch", n), ("dispatch", m)])


def test_sweep_skips_merged_and_needs_dahun():
    server, api = _env()
    _issue(server, "[incident] be:A x:f", ["incident", "merged"])
    _issue(server, "[incident] be:B x:f", ["incident", "needs-dahun"])
    _issue(server, "[incident] health:safe_mode", ["record"])
    _issue(server, "heartbeat", ["heartbeat"])
    assert sweep.sweep(api, now=NOW) == []


def test_sweep_skips_issue_with_live_run():
    server, api = _env()
    n = _issue(server, "[incident] be:A x:f", ["incident"])
    k = _issue(server, "[incident] be:B x:f", ["incident", "repairing"])
    server.workflow_runs["repair.yml"] += [
        {"id": 1, "display_title": f"repair #{n}", "status": "queued"},
        {"id": 2, "display_title": f"repair #{k}", "status": "in_progress"},
    ]
    assert sweep.sweep(api, now=NOW) == []


def test_sweep_abandons_dead_repairing_without_green_pr():
    server, api = _env()
    n = _issue(server, "[incident] be:A x:f", ["incident", "repairing"])
    server.workflow_runs["repair.yml"].append(
        {"id": 1, "display_title": f"repair #{n}", "status": "completed", "updated_at": OLD}
    )
    server.add_pull(f"auto-repair/{n}-1", head_sha="abc")
    server.runs.append({"id": 5, "name": "ci", "head_sha": "abc", "event": "pull_request", **_ci(n),
                        "status": "completed", "conclusion": "failure", "created_at": OLD})
    m = _issue(server, "[incident] be:B x:f", ["incident", "repairing"])  # PR이 아예 없다
    assert sorted(sweep.sweep(api, now=NOW)) == sorted([("abandon", n), ("abandon", m)])


def test_sweep_merge_only_for_dead_repairing_with_green_pr():
    server, api = _env()
    n = _issue(server, "[incident] be:A x:f", ["incident", "repairing"])
    server.add_pull(f"auto-repair/{n}-1", head_sha="abc")
    server.runs.append({"id": 5, "name": "ci", "head_sha": "abc", "event": "pull_request", **_ci(n),
                        "status": "completed", "conclusion": "success", "created_at": OLD})
    assert sweep.sweep(api, now=NOW) == [("merge_only", n)]


def test_sweep_waits_while_pr_ci_pending_or_run_just_ended():
    server, api = _env()
    n = _issue(server, "[incident] be:A x:f", ["incident", "repairing"])
    server.add_pull(f"auto-repair/{n}-1", head_sha="abc")
    server.runs.append({"id": 5, "name": "ci", "head_sha": "abc", "event": "pull_request", **_ci(n),
                        "status": "in_progress", "conclusion": None, "created_at": OLD})
    m = _issue(server, "[incident] be:B x:f", ["incident", "repairing"])
    server.workflow_runs["repair.yml"].append(
        {"id": 3, "display_title": f"repair #{m}", "status": "completed", "updated_at": "2026-10-26T03:00:00Z"}
    )
    assert sweep.sweep(api, now=NOW) == []


def test_apply_dispatches_on_main_and_abandons(monkeypatch):
    server, api = _env()
    n = _issue(server, "[incident] be:A x:f", ["incident", "repairing"])
    sweep.apply(api, [("dispatch", 3), ("merge_only", 4), ("abandon", n)], auto_repair="on")
    assert server.dispatches == [
        ("repair.yml", {"ref": "main", "inputs": {"issue": "3", "mode": "full"}}),
        ("repair.yml", {"ref": "main", "inputs": {"issue": "4", "mode": "merge_only"}}),
    ]
    assert "failed-1" in server.labels(n) and "repairing" not in server.labels(n)


def test_apply_off_only_cleans_up():
    server, api = _env()
    n = _issue(server, "[incident] be:A x:f", ["incident", "repairing"])
    sweep.apply(api, [("dispatch", 3), ("merge_only", 4), ("abandon", n)], auto_repair="off")
    assert server.dispatches == []
    assert "failed-1" in server.labels(n)


# --- 고침 1회차 (리뷰 I3, M2, M3) ------------------------------------------------------


def test_sweep_finishes_dead_attempt_that_already_merged():
    server, api = _env()
    n = _issue(server, "[incident] be:A x:f", ["incident", "repairing"])
    server.events[n].append({"event": "labeled", "label": {"name": "repairing"}, "created_at": "2026-10-26T01:00:00Z"})
    server.add_pull(f"auto-repair/{n}-1", state="closed", merged_at="2026-10-26T01:40:00Z")
    assert sweep.sweep(api, now=NOW) == [("mark_merged", n)]
    sweep.apply(api, [("mark_merged", n)], auto_repair="on")
    assert "merged" in server.labels(n) and "repairing" not in server.labels(n)
    assert not any(x.startswith("failed-") for x in server.labels(n))
    assert sweep.sweep(api, now=NOW) == []  # 새 full 수리를 부르지 않는다


def test_sweep_abandon_uses_attempt_from_branch():
    server, api = _env()
    n = _issue(server, "[incident] be:A x:f", ["incident", "repairing", "failed-1", "failed-2"])
    server.add_pull(f"auto-repair/{n}-2", head_sha="abc")
    server.runs.append({"id": 5, "name": "ci", "head_sha": "abc", "event": "pull_request",
                        "path": ".github/workflows/ci.yml", "head_branch": f"auto-repair/{n}-2",
                        "status": "completed", "conclusion": "failure", "created_at": OLD})
    actions = sweep.sweep(api, now=NOW)
    assert actions == [("abandon", n)]
    sweep.apply(api, actions, auto_repair="on")
    assert [x for x in server.labels(n) if x.startswith("failed-")] == ["failed-1", "failed-2"]  # 이미 센 시도


def test_sweep_abandons_pr_stuck_without_ci_for_6h():
    server, api = _env()
    n = _issue(server, "[incident] be:A x:f", ["incident", "repairing"])
    pr = server.add_pull(f"auto-repair/{n}-1", head_sha="abc")  # ci 실행이 영영 안 생겼다
    server.pull(pr)["updated_at"] = "2026-10-25T20:00:00Z"
    assert sweep.sweep(api, now=NOW) == [("abandon", n)]
    server.pull(pr)["updated_at"] = "2026-10-26T00:00:00Z"
    assert sweep.sweep(api, now=NOW) == []
