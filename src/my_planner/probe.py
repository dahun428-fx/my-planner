"""개발용 결함 주입 (SP6 스펙 12장 인수 시험). 평소에는 아무것도 하지 않는다.

노트북 `state/probe/` 아래 표지 파일이 있을 때만 켜진다. 환경 변수 대신 파일을 쓰는 까닭: BE는 `.env`의 비밀값만
읽고, 작업 스케줄러로 뜬 프로세스의 환경은 재시작 없이 못 바꾼다. 표지는 요청마다 다시 본다.

- `state/probe/command`: `/medic_probe` 명령이 `KeyError("probe")`를 던진다(12장 1–3행).
- `state/probe/health`: 안에 적힌 커밋이 아닌 코드로 돌면 `GET /health`가 500(12장 4행). 그 커밋을 적어 두고
  다음 배포를 머지하면 배포 확인이 실패해 롤백되고, 롤백된 코드(적힌 커밋)에서는 다시 200이다.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]  # 편집 설치(`pip install -e`): src/my_planner → 저장소 뿌리


def _marker(name: str, root: Path | None = None) -> Path:
    return (root or _ROOT) / "state" / "probe" / name


def command_probe_on(root: Path | None = None) -> bool:
    return _marker("command", root).is_file()


def _head(root: Path) -> str | None:
    try:
        out = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True, timeout=5, check=False
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return out.stdout.strip() if out.returncode == 0 else None


def health_probe_fails(root: Path | None = None) -> bool:
    """표지에 적힌 커밋과 지금 커밋이 다르면 True. 표지가 없거나 비었거나 git을 못 읽으면 False."""
    base = root or _ROOT
    try:
        good = _marker("health", base).read_text(encoding="utf-8").strip()
    except OSError:
        return False
    if not good:
        return False
    head = _head(base)
    return head is not None and not head.startswith(good)
