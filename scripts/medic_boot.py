"""medic 실행기 (스펙 5장 "medic 자신의 갱신"). 표준 라이브러리만 쓴다: 이 파일이 깨지면 되돌릴 곳이 없다.

작업 `my-planner-medic`이 `pythonw.exe scripts\\medic_boot.py`로 띄운다. medic을 자식으로 실행하고
- 자식이 3(자기 갱신)으로 끝나면 바로 다시 띄운다. 다른 코드면 그 코드로 끝나고 5분 감시 트리거가 다시 띄운다.
- 자식이 60초 안에 죽은 것이 연속 3번이면 `state/medic-last-good.json`의 커밋으로 `src/my_planner_medic`만 되돌린다.
  그 배포의 `new_sha`는 `medic.db`의 `bad_shas`에, 되돌린 표시는 `kv["medic_pinned"]`에 적는다(업데이터가 읽는다).
- 자식이 60초를 넘겨 살아 있으면 `new_sha`를 마지막 좋은 커밋으로 올린다(그전까지는 이전 커밋이 마지막 좋은 것).
`PYTHONPATH=<root>\\src`로 띄우므로 editable 설치가 깨져도 돈다.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import sqlite3
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

EXIT_SELF_UPDATE = 3
FAST_S = 60
MAX_FAST = 3
MEDIC_PATH = "src/my_planner_medic"
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def _read(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _write(path: Path, data: dict[str, Any]) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data), encoding="utf-8")
    os.replace(tmp, path)


def _kv_set(root: Path, key: str, value: object, *, append: bool = False) -> None:
    db = sqlite3.connect(root / "state" / "medic.db")  # 스키마는 medic store와 같다
    with contextlib.closing(db), db:
        db.execute("CREATE TABLE IF NOT EXISTS kv(key TEXT PRIMARY KEY, value TEXT)")
        if append:
            row = db.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
            old = json.loads(row[0]) if row else []
            value = [*(old if isinstance(old, list) else []), value]
        db.execute("INSERT OR REPLACE INTO kv(key, value) VALUES(?, ?)", (key, json.dumps(value)))


def revert(root: Path) -> bool:
    good = _read(root / "state" / "medic-last-good.json")
    sha, new = good.get("sha"), good.get("new_sha")
    if not isinstance(sha, str) or not _SHA_RE.match(sha):
        return False
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0  # type: ignore[attr-defined]
    done = subprocess.run(["git", "checkout", sha, "--", MEDIC_PATH], cwd=root, check=False,
                          capture_output=True, creationflags=flags)
    if done.returncode != 0:
        return False
    if isinstance(new, str) and _SHA_RE.match(new):
        _kv_set(root, "bad_shas", new, append=True)
    _kv_set(root, "medic_pinned", sha)
    return True


def main(
    root: Path,
    *,
    python: str | None = None,
    popen: Callable[..., Any] = subprocess.Popen,
    clock: Callable[[], float] = time.time,
) -> int:
    state = root / "state"
    state.mkdir(exist_ok=True)
    crashes = state / "medic-crashes.json"
    python = python or str(root / ".venv" / "Scripts" / "python.exe")
    path = [str(root / "src"), *filter(None, [os.environ.get("PYTHONPATH")])]
    env = {**os.environ, "PYTHONPATH": os.pathsep.join(path)}
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0  # type: ignore[attr-defined]
    while True:
        started = clock()
        proc = popen([python, "-m", "my_planner_medic"], cwd=root, env=env, creationflags=flags)
        try:
            code = proc.wait(timeout=FAST_S)
            survived = False
        except subprocess.TimeoutExpired:
            survived = True
            good = _read(state / "medic-last-good.json")
            if isinstance(good.get("new_sha"), str):
                _write(state / "medic-last-good.json", {"sha": good["new_sha"]})
            code = proc.wait()
        fast = [] if survived else _read(crashes).get("fast", [])
        if not survived and code != 0:
            fast = [*fast, started][-MAX_FAST:]
        _write(crashes, {"fast": fast})
        if len(fast) >= MAX_FAST:
            if revert(root):
                _write(crashes, {"fast": []})
                continue  # 되돌린 코드로 바로 다시
            return code
        if code == EXIT_SELF_UPDATE:
            continue  # 자기 갱신: 새 코드로 바로. 60초 안의 3은 위 세 번 규칙이 끊는다
        return code


if __name__ == "__main__":
    raise SystemExit(main(Path(__file__).resolve().parents[1]))
