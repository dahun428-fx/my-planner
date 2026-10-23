"""두뇌 지시문 파일(`*.md`)을 읽는다."""

from __future__ import annotations

from functools import cache
from pathlib import Path

PROMPTS_DIR = Path(__file__).parent


@cache
def load(name: str) -> str:
    return (PROMPTS_DIR / name).read_text(encoding="utf-8").strip()
