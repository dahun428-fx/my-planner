"""medic 패키지는 표준 라이브러리만 가져온다(스펙 2장)."""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ALLOWED_OWN = "my_planner_medic"


def forbidden_imports(source: str) -> list[str]:
    """소스에서 표준 라이브러리도 medic 자신도 아닌 import의 첫 이름을 모은다."""
    bad: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.level > 0:  # 상대 import는 같은 패키지 안이다
                continue
            names = [node.module or ""]
        else:
            continue
        for name in names:
            top = name.split(".")[0]
            if top not in sys.stdlib_module_names and top != ALLOWED_OWN:
                bad.append(top)
    return bad


def medic_files() -> list[Path]:
    files = sorted((ROOT / "src" / "my_planner_medic").rglob("*.py"))
    boot = ROOT / "scripts" / "medic_boot.py"
    if boot.exists():
        files.append(boot)
    return files


def test_medic_imports_only_stdlib() -> None:
    files = medic_files()
    assert files, "my_planner_medic 소스를 찾지 못했다"
    offenders = {
        str(path.relative_to(ROOT)): bad
        for path in files
        if (bad := forbidden_imports(path.read_text(encoding="utf-8")))
    }
    assert offenders == {}


def test_checker_rejects_non_stdlib_imports() -> None:
    assert forbidden_imports("import my_planner") == ["my_planner"]
    assert forbidden_imports("import aiohttp.web") == ["aiohttp"]
    assert forbidden_imports("from my_planner.db import x") == ["my_planner"]
    assert forbidden_imports("import json, sqlite3, my_planner_medic.x") == []
    assert forbidden_imports("from . import a\nfrom .b import c") == []
