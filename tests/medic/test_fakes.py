from __future__ import annotations

from pathlib import Path

from tests.medic.fakes import FakeShell


def test_fake_shell_sequences_records_and_missing(tmp_path: Path) -> None:
    sh = FakeShell()
    sh.on("git", "x", returns=[(1, "a"), (0, "b")])
    sh.missing("nope")
    assert sh.run(["git", "x"], cwd=tmp_path, timeout=5, env={"A": "1"}) == (1, "a")
    assert sh.run(["git", "x"], cwd=tmp_path) == (0, "b")
    assert sh.run(["git", "x"], cwd=tmp_path) == (0, "b")
    assert sh.run(["nope", "y"], cwd=tmp_path)[0] == 127
    assert sh.commands[0] == ["git", "x"]
    assert (sh.calls[0].cwd, sh.calls[0].timeout, sh.calls[0].env) == (tmp_path, 5, {"A": "1"})
