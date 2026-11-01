"""아래층 상대는 먼저 말하지 않는다 (SP14 스펙 1장 4, T13 정적 쪽).

하루 끝 판단·받은편지함·관찰 모듈에는 보내는 호출이 없고, 디스패처의 하루 끝 판단 함수 몸통도 보내는 길을 쓰지 않는다.
사용자에게 가는 길은 아침 브리핑 끝의 관찰 줄뿐이다(`harness/brief_notes.py`는 글만 만든다).
"""

from __future__ import annotations

import ast
from pathlib import Path

import my_planner

SRC = Path(my_planner.__file__).parent
SEND_CALLS = frozenset({
    "deliver_run", "deliver_notice", "deliver_reminder", "deliver_digest", "send_notice", "send_run_telegram",
    "send_with_retry",
})
SILENT = frozenset({
    "my_planner.harness.dayend", "my_planner.harness.inbox", "my_planner.harness.brief_notes",
    "my_planner.tools.agents", "my_planner.store.repos.agents",
})
DAYEND_FORBIDDEN = frozenset({
    "send_notice", "_run_notice_auth", "_run_notice_rate_limit", "_send_reply", "_send_run", "_fixed_reply",
})


def _module(path: Path) -> str:
    rel = path.relative_to(SRC.parent).with_suffix("")
    parts = list(rel.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _called_name(node: ast.Call) -> str | None:
    f = node.func
    if isinstance(f, ast.Name):
        return f.id
    if isinstance(f, ast.Attribute):
        return f.attr
    return None


def _calls(tree: ast.AST) -> set[str]:
    return {n for c in ast.walk(tree) if isinstance(c, ast.Call) and (n := _called_name(c)) is not None}


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _imports(tree: ast.AST) -> set[str]:
    out: set[str] = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            out.update(a.name for a in n.names)
        elif isinstance(n, ast.ImportFrom) and n.module:
            out.add(n.module)
            out.update(f"{n.module}.{a.name}" for a in n.names)
    return out


def test_lower_agents_have_no_send_path():
    senders = {_module(p) for p in SRC.rglob("*.py") if _calls(_parse(p)) & SEND_CALLS}
    assert "my_planner.harness.dispatcher" in senders  # 검사가 실제로 보고 있다
    assert senders & SILENT == set()

    for rel in ("harness/dayend.py", "tools/agents.py"):
        imported = _imports(_parse(SRC / rel))
        bad = {m for m in imported if m.startswith(("my_planner.harness.delivery", "my_planner.bot"))}
        assert bad == set(), rel

    tree = _parse(SRC / "harness" / "dispatcher.py")
    (cls,) = [n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Dispatcher"]
    bodies = {
        n.name: n for n in cls.body
        if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef) and n.name in ("_handle_dayend", "_dayend_one")
    }
    assert set(bodies) == {"_handle_dayend", "_dayend_one"}
    for name, fn in bodies.items():
        called = _calls(fn)
        assert called & DAYEND_FORBIDDEN == set(), name
        assert not {c for c in called if c.startswith("deliver_")}, name
        reads = {
            n.attr for n in ast.walk(fn)
            if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id == "self"
        }
        assert reads & {"sender", "delivery"} == set(), name
