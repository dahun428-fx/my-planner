"""REPAIR_PAT이 아직 없으면(Dahun이 시크릿을 넣기 전) 워크플로 진입점은 한 줄만 찍고 0으로 끝난다. 빨갛게 남지 않는다."""

from __future__ import annotations

import heartbeat_check
import pytest
import repair_gate
import repair_merge
import repair_publish
import signal_issue
import sweep

NOT_SET = "REPAIR_PAT not set; auto-repair not set up yet"

ENTRIES = {
    "heartbeat_check": (heartbeat_check.main, []),
    "sweep": (sweep.main, []),
    "signal_issue": (signal_issue.main, []),
    "repair_gate": (repair_gate.main, []),
    "repair_publish": (repair_publish.main, ["--issue", "1", "--branch", "auto-repair/1-1", "--pushed", "true", "--out", "x"]),
    "repair_merge_merge": (repair_merge.main, ["merge", "--issue", "1"]),
    "repair_merge_settle": (repair_merge.main, ["settle", "--issue", "1"]),
}


@pytest.mark.parametrize("name", sorted(ENTRIES))
@pytest.mark.parametrize("empty", ["", None])
def test_entry_point_is_a_noop_without_pat(name, empty, monkeypatch, capsys, tmp_path):
    for var in ("GITHUB_EVENT_PATH", "GITHUB_EVENT_NAME", "ISSUE"):
        monkeypatch.delenv(var, raising=False)  # 토큰 검사가 다른 입력을 읽기 전에 와야 한다
    monkeypatch.setenv("GITHUB_OUTPUT", str(tmp_path / "out"))
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
    if empty is None:
        monkeypatch.delenv("REPAIR_PAT", raising=False)
    else:
        monkeypatch.setenv("REPAIR_PAT", empty)
    main, argv = ENTRIES[name]
    code = main(argv) if argv else main()
    assert code == 0
    assert NOT_SET in capsys.readouterr().out


def test_repair_gate_outputs_a_skip_decision(monkeypatch, tmp_path):
    out = tmp_path / "out"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    monkeypatch.setenv("REPAIR_PAT", "")
    monkeypatch.setenv("ISSUE", "7")
    assert repair_gate.main() == 0
    text = out.read_text(encoding="utf-8")
    assert "decision=stop_no_token" in text  # fix·publish·merge 작업은 'go'/'merge_only'만 받는다


def test_repair_gate_does_not_pass_a_non_numeric_issue_to_the_output(monkeypatch, tmp_path):
    out = tmp_path / "out"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    monkeypatch.setenv("REPAIR_PAT", "")
    monkeypatch.setenv("ISSUE", "7\ndecision=go")
    assert repair_gate.main() == 0
    lines = out.read_text(encoding="utf-8").splitlines()
    assert lines == ["decision=stop_no_token", "issue="]
