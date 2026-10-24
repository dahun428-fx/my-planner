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


def _system() -> str:
    return (prompts.PROMPTS_DIR / "system.md").read_text(encoding="utf-8")


def test_system_prompt_has_principles_12_to_14():
    text = _system()
    assert "\n12. 습관은 사용자가 한 것만 체크한다. 체크한 것만 말하고, 하지 않은 습관을 세거나 " \
        "\"끊겼다\", \"며칠째 안 했다\"고 말하지 않는다.\n" in text
    assert "\n13. 주간 회고에서 습관은 \"이번 주에 한 것\"으로 돌아본다." in text
    assert "목표를 줄이거나 쉬어 가기를 **질문으로** 제안한다(먼저 바꾸지 않는다, H7).\n" in text
    assert "\n14. 새 습관이 도움이 될 것 같으면 말로 제안하고, 사용자가 원할 때 `add_habit`을 부른다." in text


def test_banned_words_include_new_three():
    block = _BANNED_BLOCK.search(_system()).group(0)
    for word in ("밀렸다", "놓쳤다", "실패", "끊겼", "며칠째", "남음"):  # SP5 목록(블록에 있던 것) + 새 세 낱말
        assert f'"{word}"' in block, word
    # 새 세 낱말은 다른 지시문과 두뇌 메모에도 없다(원칙 12가 금지 표현을 인용하는 system.md는 뺀다)
    for f in sorted(prompts.PROMPTS_DIR.glob("*.md")):
        if f.name != "system.md":
            for word in ("끊겼", "며칠째", "남음"):
                assert word not in f.read_text(encoding="utf-8"), (f.name, word)
