"""tasks.py가 만드는 PowerShell 명령 문자열(최종 리뷰 I-2): BE 프로세스는 저장소 루트 + `\\`로만 맞힌다."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from my_planner_medic.tasks import FIND_BE_PIDS, POWERSHELL, TaskControl, be_root

from .fakes import FakeShell

PROD = r'"E:\my-planner\.venv\Scripts\pythonw.exe" -m my_planner'
DEV = r'"E:\my-planner-dev\.venv\Scripts\pythonw.exe" -m my_planner'


def _query(root: str) -> str:
    shell = FakeShell()
    shell.on(*POWERSHELL, returns=(0, ""))
    TaskControl(shell, Path(root), own_pid=4242).be_pids()
    return shell.calls[-1].args[-1]


def _root_literal(query: str) -> str:
    """`$r = '<값>'.ToLowerInvariant()`의 값(PowerShell 작은따옴표 글: `''`만 `'`로)."""
    m = re.search(r"\$r = '((?:[^']|'')*)'\.ToLowerInvariant\(\)", query)
    assert m is not None
    return m[1].replace("''", "'")


def _matches(query: str, cmdline: str) -> bool:
    """PowerShell 필터의 루트 부분을 그대로 흉내 낸다: `CommandLine.ToLowerInvariant().Contains($r)`."""
    return _root_literal(query).lower() in cmdline.lower()


def test_prod_root_does_not_match_dev_checkout() -> None:
    q = _query(r"E:\my-planner")
    assert _root_literal(q) == "E:\\my-planner\\"
    assert _matches(q, PROD)
    assert not _matches(q, DEV)


def test_dev_root_matches_only_dev() -> None:
    q = _query(r"E:\my-planner-dev")
    assert _matches(q, DEV) and not _matches(q, PROD)


@pytest.mark.parametrize("root", [r"E:\my-planner", "E:\\my-planner\\", "E:/my-planner", "E:/my-planner/"])
def test_root_is_normalised_with_one_trailing_backslash(root: str) -> None:
    assert be_root(Path(root)) == "E:\\my-planner\\"
    assert _root_literal(_query(root)) == "E:\\my-planner\\"


def test_drive_root_keeps_single_backslash() -> None:
    assert be_root(Path("E:\\")) == "E:\\"


def test_quote_in_root_is_escaped_for_powershell() -> None:
    q = _query(r"E:\dahun's planner")
    assert "'E:\\dahun''s planner\\'" in q
    assert _root_literal(q) == "E:\\dahun's planner\\"


def test_query_shape_still_excludes_medic_and_own_pid() -> None:
    q = FIND_BE_PIDS.format(root=be_root(Path(r"E:\my-planner")), own_pid=4242)
    assert "-ne 4242" in q and "my_planner(\\s|$)" in q
    assert '"' not in q  # 큰따옴표 없음(모듈 머리말)
