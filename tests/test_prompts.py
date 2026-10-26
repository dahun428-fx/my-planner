"""프롬프트 파일 (앱 시작과 운영 산출물 경계): 루프마다 지시문이 있고, 금지어가 없다."""

import json
import re
from pathlib import Path

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
    # 새 세 낱말은 지시문 어디에도 없다. system.md는 금지어 블록과 금지 표현을 인용하는 원칙 12 줄만 뺀다
    for f in sorted(prompts.PROMPTS_DIR.glob("*.md")):
        text = f.read_text(encoding="utf-8")
        if f.name == "system.md":
            text = _BANNED_BLOCK.sub("", text)
            text = "\n".join(line for line in text.splitlines() if not line.startswith("12. "))
        for word in ("끊겼", "며칠째", "남음"):
            assert word not in text, (f.name, word)


# --- SP6 G-BE2: 앱 대화 지시문(9.2)과 도구 설명(9.3) ---

SP6_SPEC = (Path(__file__).parent.parent / "docs" / "superpowers" / "specs"
            / "2026-10-24-sp6-chat-generative-ui-design.md")


def _spec_section(title: str) -> str:
    text = SP6_SPEC.read_text(encoding="utf-8")
    start = text.index(f"\n### {title}")
    end = text.index("\n### ", start + 1)
    return text[start:end]


def test_channel_app_is_spec_text():
    """`channel_app.md`는 스펙 9.2 블록(공백까지)으로 시작한다. 그 뒤는 SP9 줄(메모, 지난 대화, 일정)이 빈 줄 하나 뒤에 붙는다."""
    block = re.search(r"```markdown\n(.*?)\n```", _spec_section("9.2"), re.DOTALL).group(1)
    raw = (prompts.PROMPTS_DIR / "channel_app.md").read_text(encoding="utf-8")
    assert raw.startswith(block + "\n\n")
    rest = raw.removeprefix(block + "\n\n").splitlines()
    assert [line.split(" ", 1)[0] for line in rest] == ["메모는", "메모", "지난", "시간이"]
    assert "`find_conversations`" in rest[2] and "`create_event`" in rest[3]


def test_old_echo_sentence_gone():
    from my_planner.tools.mcp_adapter import _SPECS

    texts = [f.read_text(encoding="utf-8") for f in prompts.PROMPTS_DIR.glob("*.md")]
    texts += [desc for desc, _ in _SPECS.values()]
    for t in texts:
        assert "답 글에도 같은 뜻을 씁니다" not in t
        assert "답 글에도 씁니다" not in t  # "같은 뜻을/같은 질문을 답 글에도 씁니다"(9.2와 맞춘다)


def test_new_tool_descriptions():
    from my_planner.tools.mcp_adapter import _SPECS

    rows = dict(re.findall(r'^\| `(ui_\w+)` \| "(.+?)" \|', _spec_section("9.3"), re.MULTILINE))
    assert set(rows) == {"ui_date_choice", "ui_result", "ui_period_list", "ui_block"}
    for name, desc in rows.items():
        assert _SPECS[name][0] == desc, name


def test_moments_prompt_rules():
    """하루 끝 순간 지시문(SP8 6.3 규칙 1~6). 대화 원칙(`system.md`)은 싣지 않고 금지어 블록만 붙인다."""
    from my_planner.harness.moments import moments_system_prompt
    from my_planner.tools.ui import banned_words

    text = prompts.load("moments.md")
    for phrase in ("해낸 일", "60자", "0개", "병명", "sources", "save_moments", "포트폴리오 사례 하나를 끝까지 다듬었어요"):
        assert phrase in text, phrase
    for word in banned_words():
        assert word not in text, word
    full = moments_system_prompt()
    assert full.startswith(text + "\n\n")
    block = _BANNED_BLOCK.search(_system()).group(0)
    assert full.endswith(block)
    line_before = _system().split(block)[0].rstrip("\n").splitlines()[-1]
    assert full == f"{text}\n\n{line_before}\n{block}"
    assert "## 할 일을 다루는 방식" not in full and "## 말하는 방식" not in full
    assert _system().splitlines()[0] not in full


P15 = (
    "15. 이룬 순간은 비서가 하루 끝에 조용히 남기는 기록이다. 사용자가 지우고 싶어 하면 앱 상태창에서 밀어서 숨기거나 "
    "지울 수 있다고 안내한다. 대화에서 직접 고치지 않는다."
)
P16 = (
    "16. 보너스와 이룬 순간은 사용자가 물을 때 말한다. 보너스가 줄었다거나, 순간이 없던 날을 세어 말하지 않는다. "
    "텔레그램 대화에서는 순간의 글을 받지 않으므로 개수만 말하고 \"운영 앱 상태창에서 볼 수 있어요\"라고 안내한다."
)
ASK_LINE = "순간 하나를 곡선에 남길지 묻는 것은 앱 대화에서 `get_status`로 순간의 글을 받았을 때만 한다"
REVIEW_LINE = (
    "앞머리의 이룬 순간은 날짜와 개수만 보인다. 회고에서 순간의 글을 짐작해 말하거나 곡선에 남기자고 묻지 않는다. "
    "사용자가 앱에서 이어 물으면 그때 `get_status`로 본다."
)


def test_system_prompt_has_principles_15_16():
    """SP8 10.3 원칙 15·16 그대로, 그리고 "곡선에 남길까요?"는 앱 대화의 `get_status`에서만(계획 결정 10)."""
    text = _system()
    section = text.split("## 이룬 순간\n", 1)[1].split("\n## ", 1)[0]
    assert f"\n{P15}\n" in f"\n{section}"
    assert f"\n{P16}\n" in f"\n{section}"
    assert ASK_LINE in section


def test_review_week_moments_counts_only_no_ask():
    text = prompts.load("review_week.md")
    assert REVIEW_LINE in text
    assert "날짜와 개수" in text
    assert "곡선에 남길까요" not in text


def test_prompts_use_new_kind_names():
    """SP8 8.7: 사건 종류는 "높은 때", "힘든 때", "전환점"이다. 프롬프트와 도구 설명에 옛 이름이 없다."""
    from my_planner.tools.mcp_adapter import _SPECS as TOOL_SPECS

    old = ("고점", "저점")
    for f in sorted(prompts.PROMPTS_DIR.glob("*.md")):
        text = f.read_text(encoding="utf-8")
        assert not any(w in text for w in old), f.name
    tools_text = json.dumps(TOOL_SPECS, ensure_ascii=False)
    assert not any(w in tools_text for w in old)
    assert "곡선에 높은 때로 남길까요?" in _system()
    assert "높은 때, 힘든 때, 전환점" in tools_text


# --- SP9c 4.3: 퀵 칩 알림 ---

SP9C_SPEC = (Path(__file__).parent.parent / "docs" / "superpowers" / "specs"
             / "2026-10-26-sp9c-quick-chip-cards-design.md")


def test_chip_prompts_are_spec_text():
    """`chip_<키>.md`는 스펙 4.3의 그 키 문장 그대로(따옴표 밖)다. 키마다 하나, 금지어 없음."""
    from typing import get_args

    from my_planner.api.models import ChipKey
    from my_planner.tools.ui import banned_words

    text = SP9C_SPEC.read_text(encoding="utf-8")
    section = text[text.index("\n### 4.3"):text.index("\n### 4.4")]
    rows = dict(re.findall(r'^- `(\w+)`: "(.+)"$', section, re.MULTILINE))
    assert set(rows) == set(get_args(ChipKey)) == {"todo", "event", "memo", "today", "next"}
    for key, sentence in rows.items():
        got = prompts.load(f"chip_{key}.md")
        assert got == sentence, key
        assert [w for w in banned_words() if w in got] == [], key
