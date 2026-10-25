"""scripts/medic_boot.py (스펙 5장 "medic 자신의 갱신"). 임시 git 저장소에서 진짜 자식 프로세스를 띄운다."""

from __future__ import annotations

import contextlib
import importlib.util
import json
import os
import sqlite3
import subprocess
import sys
import types
from pathlib import Path

import pytest

BOOT = Path(__file__).resolve().parents[2] / "scripts" / "medic_boot.py"
GOOD = "raise SystemExit(0)\n"
BAD = "raise RuntimeError('boom')\n"


def load_boot() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location("medic_boot", BOOT)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def git(root: Path, *args: str) -> str:
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@t"}
    out = subprocess.run(["git", *args], cwd=root, env=env, check=True, capture_output=True, text=True)
    return out.stdout.strip()


def make_repo(root: Path, main_py: str) -> str:
    pkg = root / "src" / "my_planner_medic"
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / "__init__.py").write_text("")
    (pkg / "__main__.py").write_text(main_py)
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "c")
    return git(root, "rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path: Path) -> tuple[Path, str, str]:
    git(tmp_path, "init", "-q")
    (tmp_path / ".gitignore").write_text("state/\n")
    good = make_repo(tmp_path, GOOD)
    bad = make_repo(tmp_path, BAD)
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "medic-last-good.json").write_text(json.dumps({"sha": good, "new_sha": bad}))
    return tmp_path, good, bad


def kv(root: Path, key: str) -> object:
    if not (root / "state" / "medic.db").exists():
        return None
    with contextlib.closing(sqlite3.connect(root / "state" / "medic.db")) as db:
        row = db.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
    if row is None:
        return None
    try:
        return json.loads(row[0])
    except ValueError:
        return row[0]  # medic_pinned는 원문 sha


def test_boot_reverts_medic_after_three_fast_crashes(repo: tuple[Path, str, str]) -> None:
    root, good, bad = repo
    boot = load_boot()
    assert boot.main(root, python=sys.executable) == 1
    assert boot.main(root, python=sys.executable) == 1
    assert "boom" in (root / "src" / "my_planner_medic" / "__main__.py").read_text()  # 아직 그대로
    assert kv(root, "bad_shas") is None
    # 세 번째: 되돌린 뒤 좋은 코드가 바로 0으로 끝난다
    assert boot.main(root, python=sys.executable) == 0
    assert (root / "src" / "my_planner_medic" / "__main__.py").read_text() == GOOD
    assert git(root, "status", "--porcelain", "--untracked-files=no").startswith("M")  # git checkout <sha> -- 경로
    assert kv(root, "bad_shas") == [bad]
    assert kv(root, "medic_pinned") == good
    assert not json.loads((root / "state" / "medic-crashes.json").read_text())["fast"]


class Survivor:
    """60초를 넘겨 사는 자식."""

    def __init__(self, args: list[str], **kw: object) -> None:
        pass

    def wait(self, timeout: float | None = None) -> int:
        if timeout is not None:
            raise subprocess.TimeoutExpired("x", timeout)
        return 0


def test_revert_clears_new_sha_so_surviving_good_medic_never_promotes_bad(repo: tuple[Path, str, str]) -> None:
    root, good, _bad = repo
    boot = load_boot()
    (root / "state" / "medic-crashes.json").write_text(json.dumps({"fast": [1.0, 2.0]}))
    calls: list[int] = []

    def popen(args: list[str], **kw: object) -> object:
        calls.append(1)
        if len(calls) == 1:
            return subprocess.Popen([sys.executable, *args[1:]], **kw)  # type: ignore[call-overload]
        return Survivor(args, **kw)

    assert boot.main(root, python=sys.executable, popen=popen) == 0
    assert len(calls) == 2
    assert json.loads((root / "state" / "medic-last-good.json").read_text()) == {"sha": good}
    assert kv(root, "medic_pinned") == good  # 따옴표 없는 원문(업데이터가 kv_set으로 쓰는 모양)


def test_three_fast_crashes_without_pending_self_update_do_not_touch_the_tree(
    repo: tuple[Path, str, str],
) -> None:
    root, _good, bad = repo
    (root / "state" / "medic-last-good.json").write_text(json.dumps({"sha": bad}))  # 보통 배포: new_sha 없음
    main_py = root / "src" / "my_planner_medic" / "__main__.py"
    main_py.write_text("raise RuntimeError('hand edit')\n")  # 손으로 고친, 커밋 안 된 파일
    boot = load_boot()
    for _ in range(4):
        assert boot.main(root, python=sys.executable) == 1
    assert main_py.read_text() == "raise RuntimeError('hand edit')\n"
    assert kv(root, "medic_pinned") is None and kv(root, "bad_shas") is None


def test_fast_exit_0_resets_the_streak_and_corrupt_crash_file_is_tolerated(repo: tuple[Path, str, str]) -> None:
    root, _good, _bad = repo
    boot = load_boot()
    (root / "state" / "medic-crashes.json").write_text(json.dumps({"fast": 5}))
    assert boot.main(root, python=sys.executable) == 1
    (root / "src" / "my_planner_medic" / "__main__.py").write_text(GOOD)
    assert boot.main(root, python=sys.executable) == 0
    assert json.loads((root / "state" / "medic-crashes.json").read_text()) == {"fast": []}


def test_boot_relaunches_at_once_on_exit_3_and_other_codes_end_boot(tmp_path: Path) -> None:
    boot = load_boot()
    codes = iter([3, 3, 7])
    launched: list[list[str]] = []

    class Proc:
        def __init__(self, args: list[str], **kw: object) -> None:
            launched.append(args)
            self.env = kw.get("env")
            self.rc = next(codes)

        def wait(self, timeout: float | None = None) -> int:
            return self.rc

    (tmp_path / "state").mkdir()
    assert boot.main(tmp_path, python="py", popen=Proc, clock=iter(range(0, 1000, 100)).__next__) == 7
    assert len(launched) == 3 and launched[0] == ["py", "-m", "my_planner_medic"]


def test_boot_promotes_new_sha_to_last_good_after_60_seconds(repo: tuple[Path, str, str]) -> None:
    root, _good, bad = repo
    boot = load_boot()

    class Proc:
        def __init__(self, args: list[str], **kw: object) -> None:
            self.env = kw["env"]
            self.waited = 0

        def wait(self, timeout: float | None = None) -> int:
            self.waited += 1
            if timeout is not None:
                raise subprocess.TimeoutExpired("x", timeout)  # 60초를 넘겨 살아 있다
            return 0

    assert boot.main(root, python="py", popen=Proc) == 0
    assert json.loads((root / "state" / "medic-last-good.json").read_text()) == {"sha": bad}
    assert kv(root, "medic_pinned") is None


def test_boot_sets_pythonpath_to_src(tmp_path: Path) -> None:
    boot = load_boot()
    seen: dict[str, str] = {}

    class Proc:
        def __init__(self, args: list[str], **kw: object) -> None:
            seen.update(kw["env"])  # type: ignore[arg-type]
            seen["cwd"] = str(kw["cwd"])

        def wait(self, timeout: float | None = None) -> int:
            return 0

    (tmp_path / "state").mkdir()
    boot.main(tmp_path, python="py", popen=Proc)
    assert seen["PYTHONPATH"].split(os.pathsep)[0] == str(tmp_path / "src") and seen["cwd"] == str(tmp_path)
