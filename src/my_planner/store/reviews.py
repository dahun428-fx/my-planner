"""회고 저장 `data/reviews/week/<YYYY-Www>.md` (스펙 5.4, ADR 0003). 사람이 읽는 md다."""

from __future__ import annotations

import os
from pathlib import Path


def save_weekly_review(data_dir: Path, period: str, text: str, *, included: str | None = None) -> Path:
    """그 주의 회고를 쓴다. 같은 주 파일이 있으면 덮어쓴다. 임시 파일에 쓴 뒤 바꿔 끼운다.

    `included`: 월말·분기·연말 회고면 머리글 아래에 붙이는 한 줄(SP3-4 11.1 "회고 파일",
    `포함: 월간(2026-10), 분기(2026-Q4)`). 점수는 md에 복사하지 않는다(마스터 5.4).
    """
    path = Path(data_dir).resolve() / "reviews" / "week" / f"{period}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".md.tmp")
    head = f"# 주간 회고 {period}\n\n" + (f"{included}\n\n" if included else "")
    tmp.write_text(f"{head}{text.strip()}\n", encoding="utf-8", newline="\n")
    os.replace(tmp, path)
    return path
