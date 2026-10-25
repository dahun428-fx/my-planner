"""repair.yml 시작 전 검사 (스펙 4.3). Claude 없이 셸 단계가 한다."""

from __future__ import annotations

from datetime import UTC, datetime

import gh
import repair_gate
from medic.fakes import FakeGitHub, FakeHttp

# 2026-10-26(월) 10:00 KST
NOW = datetime(2026, 10, 26, 1, 0, tzinfo=UTC)


def _env():
    server = FakeGitHub()
    http = FakeHttp(route=server.route)
    sent: list[str] = []
    api = gh.Api("tok", "o/r", http=http)
    return server, api, sent


def _gate(api, n, sent, **kw):
    args = {"now": NOW, "auto_repair": "on", "max_failures": 2, "max_merges": 3, "send": sent.append}
    args.update(kw)
    return repair_gate.gate(api, n, **args)


def test_gate_off():
    server, api, sent = _env()
    n = server.add_issue("[incident] be:KeyError src/x.py:f", ["incident", "be"])
    assert _gate(api, n, sent, auto_repair="off") == "stop_off"
    assert server.labels(n) == ["incident", "be"]
    assert sent == []


def test_gate_failures_at_limit_gives_up_and_notifies():
    server, api, sent = _env()
    n = server.add_issue("[incident] be:KeyError src/x.py:f", ["incident", "be", "rolled-back", "failed-1", "failed-2"])
    assert _gate(api, n, sent) == "gave_up"
    assert "needs-dahun" in server.labels(n)
    assert "repairing" not in server.labels(n)
    assert sent == [
        ("⚠️ 자동으로 못 고쳤어요: be:KeyError src/x.py:f. 지금은 이전 버전으로 돌려 둠. "
        f"https://github.com/o/r/issues/{n}")
    ]
    # 이미 needs-dahun이면 다시 알리지 않는다(장애 하나에 결과 알림 한 번)
    assert _gate(api, n, sent) == "skip"
    assert len(sent) == 1


def test_gate_failures_below_limit_goes():
    server, api, sent = _env()
    n = server.add_issue("[incident] be:KeyError src/x.py:f", ["incident", "failed-1"])
    assert _gate(api, n, sent) == "go"
    assert repair_gate.attempt(server.labels(n)) == 2


def test_gate_merges_today_at_limit():
    server, api, sent = _env()
    n = server.add_issue("[incident] app:TypeError /today", ["incident", "app"])
    # Asia/Seoul 오늘 00:30(= 전날 15:30 UTC) 둘 + 오늘 09:00 하나 = 셋. 전날 23:30 KST 것은 세지 않는다
    for at in ("2026-10-25T15:30:00Z", "2026-10-25T15:30:00Z", "2026-10-26T00:00:00Z"):
        server.add_pull("auto-repair/1-1", state="closed", merged_at=at, labels=["auto-repair"])
    server.add_pull("auto-repair/2-1", state="closed", merged_at="2026-10-25T14:30:00Z", labels=["auto-repair"])
    server.add_pull("claude/x", state="closed", merged_at="2026-10-26T00:10:00Z")  # 수리 PR이 아님
    assert repair_gate.merges_today(api, NOW) == 3
    assert _gate(api, n, sent) == "gave_up"
    assert sent and sent[0].startswith("⚠️ 자동으로 못 고쳤어요: app:TypeError /today. 지금은 그대로. ")


def test_gate_merges_yesterday_late_not_counted():
    server, api, sent = _env()
    n = server.add_issue("[incident] app:TypeError /today", ["incident", "app"])
    for _ in range(3):  # 전날 23:30 KST
        server.add_pull("auto-repair/2-1", state="closed", merged_at="2026-10-25T14:30:00Z", labels=["auto-repair"])
    assert repair_gate.merges_today(api, NOW) == 0
    assert _gate(api, n, sent) == "go"


def test_gate_go_adds_repairing():
    server, api, sent = _env()
    n = server.add_issue("[incident] be:KeyError src/x.py:f", ["incident", "be"])
    assert _gate(api, n, sent) == "go"
    assert "repairing" in server.labels(n)
    assert sent == []


def test_gate_skips_record_closed_merged_and_repairing():
    server, api, sent = _env()
    record = server.add_issue("[incident] health:safe_mode", ["record"])
    closed = server.add_issue("[incident] be:A x:f", ["incident"], state="closed")
    merged = server.add_issue("[incident] be:B x:f", ["incident", "merged"])
    busy = server.add_issue("[incident] be:C x:f", ["incident", "repairing"])
    for n in (record, closed, merged, busy):
        assert _gate(api, n, sent) == "skip"
    assert sent == []


def test_gate_merge_only_needs_repairing():
    server, api, sent = _env()
    dead = server.add_issue("[incident] be:C x:f", ["incident", "repairing"])
    fresh = server.add_issue("[incident] be:D x:f", ["incident"])
    assert _gate(api, dead, sent, mode="merge_only") == "merge_only"
    assert _gate(api, fresh, sent, mode="merge_only") == "skip"
    assert "repairing" not in server.labels(fresh)


def test_outputs_describe_attempt_retry_and_part():
    labels = ["incident", "app", "recurred", "failed-1"]
    assert repair_gate.outputs("go", 7, labels) == {
        "decision": "go", "issue": "7", "attempt": "2", "retry": "true", "part": "app",
    }
    assert repair_gate.outputs("skip", 7, ["incident", "be"])["retry"] == "false"
    assert repair_gate.outputs("go", 7, ["incident"])["part"] == ""
