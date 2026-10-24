from __future__ import annotations

import sys
from pathlib import Path

from my_planner_medic.shell import SubprocessShell


def test_subprocess_shell_merges_stderr_and_times_out(tmp_path: Path) -> None:
    sh = SubprocessShell()
    code, out = sh.run(
        [sys.executable, "-c", "import sys;print('a');print('b',file=sys.stderr);sys.exit(3)"],
        cwd=tmp_path,
    )
    assert code == 3 and "a" in out and "b" in out
    code, out = sh.run([sys.executable, "-c", "import time;time.sleep(5)"], cwd=tmp_path, timeout=1)
    assert code == 124 and out


def test_missing_executable_returns_127(tmp_path: Path) -> None:
    code, out = SubprocessShell().run(["no-such-exe-xyz"], cwd=tmp_path)
    assert code == 127 and "not found" in out
