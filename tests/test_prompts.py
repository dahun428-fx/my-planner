"""프롬프트 파일 (앱 시작과 운영 산출물 경계): 루프마다 지시문이 있고, 금지어가 없다."""

import re

from my_planner.harness import prompts
from my_planner.harness.dispatcher import LOOP_PROMPTS

BANNED = ("놓쳤어요", "밀렸어요", "늦었지만", "실패")
_BANNED_BLOCK = re.compile(r"<!-- banned-words:start -->.*?<!-- banned-words:end -->", re.DOTALL)


def test_prompts_have_no_banned_words():
    files = sorted(prompts.PROMPTS_DIR.glob("*.md"))
    names = {f.name for f in files}
    assert set(LOOP_PROMPTS.values()) <= names  # 루프마다 지시문 파일이 있다(복귀 인사는 return.md)
    assert {"system.md", "chat.md"} <= names
    for f in files:
        text = f.read_text(encoding="utf-8")
        if f.name == "system.md":  # 금지어 목록 자체는 뺀다
            assert _BANNED_BLOCK.search(text), "system.md에 banned-words 블록이 있어야 한다"
            text = _BANNED_BLOCK.sub("", text)
        for word in BANNED:
            assert word not in text, (f.name, word)
