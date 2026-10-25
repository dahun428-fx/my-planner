"""SP9 S3: Claude Agent SDK 세션 파일 경로를 한 줄로 찍는다. 없으면 종료 코드 1.

사용: python scripts/spike_session_path.py <session_id>
SDK는 ~/.claude/projects/<cwd의 / 와 . 을 -로 바꾼 이름>/<session_id>.jsonl 에 저장한다.
cwd 인코딩이 확실하지 않아 현재 cwd 인코딩을 먼저 보고, 없으면 projects 아래 전체를 찾는다.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path


def find_session_file(session_id: str, projects: Path | None = None, cwd: Path | None = None) -> Path | None:
    projects = projects or Path.home() / ".claude" / "projects"
    if not projects.is_dir():
        return None
    name = f"{session_id}.jsonl"
    encoded = re.sub(r"[/\\.:]", "-", str(cwd or Path.cwd()))
    exact = projects / encoded / name
    if exact.is_file():
        return exact
    for hit in sorted(projects.glob(f"*/{name}")):
        if hit.is_file():
            return hit
    return None


def main(argv: list[str]) -> int:
    if len(argv) != 2 or not re.fullmatch(r"[\w-]+", argv[1]):
        print("usage: spike_session_path.py <session_id>", file=sys.stderr)
        return 2
    found = find_session_file(argv[1])
    if found is None:
        return 1
    print(found)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
