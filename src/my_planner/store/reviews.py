"""회고 저장 `data/reviews/week/<YYYY-Www>.md` (스펙 5.4, ADR 0003). 사람이 읽는 md다."""

from __future__ import annotations

import os
from pathlib import Path


def save_weekly_review(data_dir: Path, period: str, text: str) -> Path:
    """그 주의 회고를 쓴다. 같은 주 파일이 있으면 덮어쓴다. 임시 파일에 쓴 뒤 바꿔 끼운다."""
    path = Path(data_dir).resolve() / "reviews" / "week" / f"{period}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".md.tmp")
    tmp.write_text(f"# 주간 회고 {period}\n\n{text.strip()}\n", encoding="utf-8", newline="\n")
    os.replace(tmp, path)
    return path
