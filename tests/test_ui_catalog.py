"""SP6 카탈로그: 새 조각 넷의 props 모델, 쌓기 규칙 B1~B9, 글 검사, 공유 props 자료 (SP6 스펙 5~7장, 10.1, 10.3, 10.6).

`tests/fixtures/ui_props/<컴포넌트>/{ok,bad}/*.json`은 앱 시험도 제자리에서 읽는다. `bad/<code>-<설명>.json`은 오류에
그 `code`가 있어야 한다. 내용은 모두 꾸며 낸 것이다.
"""

import json
import re
from pathlib import Path

import jsonschema
import pytest
from test_tools_tasks import ToolEnv

from my_planner.bot.commands import command_of
from my_planner.domain import RunContext
from my_planner.store.repos.cards import CardsRepo
from my_planner.tools.mcp_adapter import TOOL_NAMES, tool_names_for
from my_planner.tools.ui import (
    BRAIN_COMPONENTS,
    PINNABLE_COMPONENTS,
    UI_COMPONENTS,
    banned_words,
    validate_props,
)

PROPS = Path(__file__).parent / "fixtures" / "ui_props"
OK = sorted(PROPS.glob("*/ok/*.json"))
BAD = sorted(PROPS.glob("*/bad/*.json"))
NEW = ("ui_date_choice", "ui_result", "ui_period_list", "ui_block")


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _id(path: Path) -> str:
    return f"{path.parent.parent.name}/{path.parent.name}/{path.stem}"


def _block(*children, title="꾸민 카드"):
    return {"title": title, "children": list(children)}


TEXT = {"type": "text", "md": "꾸민 글이에요."}


@pytest.mark.parametrize("path", OK, ids=_id)
def test_shared_ok_fixtures_pass(path):
    assert validate_props(path.parent.parent.name, _load(path)) is None


@pytest.mark.parametrize("path", BAD, ids=_id)
def test_shared_bad_fixtures_fail_with_code(path):
    code = path.stem.split("-", 1)[0]
    err = validate_props(path.parent.parent.name, _load(path))
    assert err is not None and f": {code}" in err, err


def test_fixtures_cover_every_component():
    for name in (*NEW, *PINNABLE_COMPONENTS, "ui_habit_check"):
        assert list((PROPS / name / "ok").glob("*.json")), name
        assert list((PROPS / name / "bad").glob("*.json")), name
    for name in ("ui_date_choice", "ui_block", *PINNABLE_COMPONENTS):  # 자유 글이 있는 조각
        stems = {p.stem.split("-", 1)[0] for p in (PROPS / name / "bad").glob("*.json")}
        assert {"bad_char", "banned_word"} <= stems, name
    assert any(p.stem.startswith("slash-") for p in (PROPS / "ui_block" / "bad").glob("*.json"))
    assert any(p.stem.startswith("slash-") for p in (PROPS / "ui_choice" / "bad").glob("*.json"))


def test_fixtures_are_utf8_indent_2():
    for path in (*OK, *BAD):
        raw = path.read_bytes().decode("utf-8")
        # 방향 문자는 `\uXXXX`로 적어 파일을 열어도 글이 뒤집혀 보이지 않게 한다
        assert raw == re.sub(r"[\u202a-\u202e\u2066-\u2069]", lambda m: f"\\u{ord(m.group()):04x}",
                             json.dumps(json.loads(raw), ensure_ascii=False, indent=2)) + "\n", path


def test_every_block_rule_has_bad_fixture():
    stems = {p.stem.split("-", 1)[0] for p in (PROPS / "ui_block" / "bad").glob("*.json")}
    assert stems >= {
        "block_too_many", "union_tag_invalid", "buttons_place", "todo_rows_too_many", "divider_place",
        "block_no_content", "complete_not_in_rows", "too_large",
    }
    assert {"union_tag_not_found", "too_short"} <= stems  # B2·B3


def test_all_elements_fixture_uses_ten_types():
    def types(v):
        if isinstance(v, dict):
            if isinstance(v.get("type"), str):
                yield v["type"]
            for x in v.values():
                yield from types(x)
        elif isinstance(v, list):
            for x in v:
                yield from types(x)

    props = _load(PROPS / "ui_block" / "ok" / "all-elements.json")
    assert set(types(props["children"])) == {
        "heading", "text", "stat", "progress", "todo_rows", "tags", "bullets", "buttons", "divider", "group",
    }


def test_error_text_has_no_values():
    secret = "비밀제목XYZ"
    bad = [
        ("ui_block", _block(*[TEXT] * 13, title=secret)),
        ("ui_block", _block({"type": "text", "md": f"{secret} 달성률"}, title=secret)),
        ("ui_block", _block({"type": "heading", "text": f"{secret}\u202e"}, TEXT, title=secret)),
        ("ui_block", _block({"type": "divider"}, TEXT, title=secret)),
        ("ui_block", _block(TEXT, title=secret * 10)),
        ("ui_block", _block(*[{"type": "text", "md": "가" * 280}] * 12, title=secret)),
        ("ui_date_choice", {"task_id": 1, "question": secret, "candidates": [{"date": "2026-10-27"}] * 2}),
        ("ui_date_choice", {"task_id": 1, "question": f"{secret}\x07", "candidates": [
            {"date": "2026-10-27"}, {"date": "2026-10-28"}]}),
        ("ui_todo_list", {"title": f"{secret} 실패", "task_ids": [1]}),
        ("ui_choice", {"question": secret, "options": [{"id": "a", "label": f"/{secret}"}, {"id": "b", "label": "나"}]}),
        ("ui_summary_card", {"title": secret, "lines": [f"{secret}\t"]}),
    ]
    for component, props in bad:
        err = validate_props(component, props)
        assert err is not None and secret not in err and "XYZ" not in err, (component, err)


def test_new_codes_have_korean_hint():
    assert validate_props("ui_block", _block(*[TEXT] * 6, {"type": "group", "layout": "row", "children": [
        {"type": "stat", "label": "가", "value": "1"}] * 3}, *[TEXT] * 4)) == (
        "props: block_too_many (부품은 모두 12개까지예요)")
    assert validate_props("ui_block", _block(
        {"type": "buttons", "items": [{"label": "더 알려 줘", "do": {"kind": "send"}}]}, TEXT)) == (
        "props: buttons_place (버튼 줄은 하나만, 맨 끝에 둬요)")
    assert validate_props("ui_period_list", {"day": "2026-10-24", "week": "2026-W43"}) == "props: period_one"


def test_text_md_allows_four_newlines_only():
    assert validate_props("ui_block", _block({"type": "text", "md": "가\n나\n다\n라\n마"})) is None
    assert validate_props("ui_block", _block({"type": "text", "md": "가\n나\n다\n라\n마\n바"})) == (
        "children.0.md: bad_char (쓸 수 없는 글자가 있어요)")
    assert validate_props("ui_block", _block({"type": "heading", "text": "가\n나"}, TEXT)) == (
        "children.0.text: bad_char (쓸 수 없는 글자가 있어요)")
    assert validate_props("ui_block", _block({"type": "text", "md": "가\r나"})).endswith(": bad_char (쓸 수 없는 글자가 있어요)")
    assert validate_props("ui_block", _block({"type": "text", "md": "가\u202e나"})) == (
        "children.0.md: bad_char (쓸 수 없는 글자가 있어요)")
    for ch in ("\u202a", "\u2066", "\u2069", "\x7f", "\x00"):
        assert "bad_char" in validate_props("ui_summary_card", {"title": "정리", "lines": [f"가{ch}"]})
    assert validate_props("ui_summary_card", {"title": "정리", "lines": ["가\n나"]}) == "lines.0: bad_char (쓸 수 없는 글자가 있어요)"


def test_banned_words_read_from_system_md():
    words = banned_words()
    assert "놓쳤어요" in words and "달성률" in words and "연속" in words and "스트릭" in words
    assert all(w and '"' not in w and "," not in w for w in words)
    assert validate_props("ui_todo_list", {"title": "어제 놓쳤어요", "task_ids": [1]}) == (
        "title: banned_word (쓰지 않는 말이 있어요)")
    assert validate_props("ui_block", _block({"type": "bullets", "items": ["괜찮아요", "스트릭 3일"]})) == (
        "children.0.items.1: banned_word (쓰지 않는 말이 있어요)")


def test_slash_rejected_for_send_and_choice():
    def buttons(label, do):
        return _block({"type": "todo_rows", "task_ids": [7]}, {"type": "buttons", "items": [{"label": label, "do": do}]})

    assert validate_props("ui_block", buttons("/pause 3", {"kind": "send"})) == (
        "children.1.items.0.label: slash (/로 시작하는 글은 쓸 수 없어요)")
    assert validate_props("ui_block", buttons("/x", {"kind": "open", "screen": "today"})) is None
    assert validate_props("ui_block", buttons("/x", {"kind": "complete", "task_id": 7})) is None
    assert validate_props("ui_block", buttons("멈춰 /pause", {"kind": "send"})) is None  # 시작만 본다
    choice = {"question": "어느 쪽?", "options": [{"id": "a", "label": "/today"}, {"id": "b", "label": "산책"}]}
    assert validate_props("ui_choice", choice) == "options.0.label: slash (/로 시작하는 글은 쓸 수 없어요)"
    assert validate_props("ui_summary_card", {"title": "정리", "lines": ["/today"]}) is None


@pytest.mark.parametrize("label", [" /pause 14", "\N{IDEOGRAPHIC SPACE}/done"])
def test_slash_ignores_leading_space_like_command_of(label):
    """`/chat`의 `command_of`는 앞뒤 공백(U+3000 포함)을 빼고 명령을 읽으므로 `slash`도 같게 본다(12장)."""
    assert command_of(label) is not None
    send = _block(TEXT, {"type": "buttons", "items": [{"label": label, "do": {"kind": "send"}}]})
    assert validate_props("ui_block", send) == "children.1.items.0.label: slash (/로 시작하는 글은 쓸 수 없어요)"
    choice = {"question": "어느 쪽?", "options": [{"id": "a", "label": "산책"}, {"id": "b", "label": label}]}
    assert validate_props("ui_choice", choice) == "options.1.label: slash (/로 시작하는 글은 쓸 수 없어요)"


def test_extra_key_name_not_echoed():
    err = validate_props("ui_block", _block({"type": "text", "md": "가", "비밀제목XYZ": 1}))
    assert err == "children.0.text: extra_forbidden"
    assert validate_props("ui_todo_list", {"title": "가", "task_ids": [1], "비밀제목XYZ": 1}) == "props: extra_forbidden"


def test_banned_words_need_the_block(monkeypatch):
    from my_planner.harness import prompts

    monkeypatch.setattr(prompts, "load", lambda name: "표지 없는 지시문")
    banned_words.cache_clear()
    try:
        with pytest.raises(RuntimeError):
            banned_words()
    finally:
        monkeypatch.undo()
        banned_words.cache_clear()
    assert "놓쳤어요" in banned_words()


def test_harness_components_skip_text_checks():
    assert validate_props("ui_confirm", {"summary": "어제 놓쳤어요\n", "confirm_token": "t", "action": "a", "args": {}}) is None


def test_period_list_needs_exactly_one():
    assert validate_props("ui_period_list", {"day": "2026-10-24", "week": "2026-W43"}) == "props: period_one"
    assert validate_props("ui_period_list", {}) == "props: period_one"
    assert validate_props("ui_period_list", {"highlight_task_ids": [1]}) == "props: period_one"
    assert validate_props("ui_period_list", {"day": "2026-10-24"}) is None
    assert validate_props("ui_period_list", {"week": "2026-W44", "highlight_task_ids": []}) is None
    assert "string_pattern_mismatch" in validate_props("ui_period_list", {"week": "2026-44"})


def test_distinct_lists():
    assert validate_props("ui_result", {"task_ids": [53, 53]}) == "props: not_unique"
    assert validate_props("ui_period_list", {"week": "2026-W44", "highlight_task_ids": [1, 2, 1]}) == "props: not_unique"
    assert validate_props("ui_block", _block({"type": "todo_rows", "task_ids": [3, 3]})) == "props: not_unique"
    same_date = {"task_id": 53, "question": "언제 할까요?", "candidates": [
        {"date": "2026-10-27", "note": "오후"}, {"date": "2026-10-27"}]}
    assert validate_props("ui_date_choice", same_date) == "props: not_unique"

    schema = UI_COMPONENTS["ui_result"]["schema"]
    assert schema["properties"]["task_ids"]["uniqueItems"] is True
    assert UI_COMPONENTS["ui_period_list"]["schema"]["properties"]["highlight_task_ids"]["uniqueItems"] is True
    defs = UI_COMPONENTS["ui_block"]["schema"]["$defs"]
    assert defs["TodoRowsEl"]["properties"]["task_ids"]["uniqueItems"] is True
    v = jsonschema.Draft202012Validator(schema)
    assert not v.is_valid({"task_ids": [53, 53]}) and v.is_valid({"task_ids": [53, 54]})


def test_value_over_max_and_too_large():
    assert validate_props("ui_block", _block({"type": "progress", "label": "운동", "value": 5, "max": 4})) == (
        "props: value_over_max")
    assert validate_props("ui_block", _block({"type": "progress", "label": "운동", "value": 4, "max": 4})) is None
    big = _block(*[{"type": "text", "md": "가" * 280}] * 12)
    assert len(json.dumps(big, ensure_ascii=False).encode()) > 8192
    assert validate_props("ui_block", big) == "props: too_large (조각이 너무 커요)"


def test_block_rules_count_inside_groups():
    stack = {"type": "group", "layout": "stack", "children": [TEXT, {"type": "divider"}]}
    assert validate_props("ui_block", _block(stack)) == "props: divider_place (구분선은 처음·끝에 두지 않고 둘을 붙이지 않아요)"
    rows = {"type": "todo_rows", "task_ids": [1]}
    nested = {"type": "group", "layout": "stack", "children": [rows, rows]}
    assert validate_props("ui_block", _block(nested, rows)) == "props: todo_rows_too_many (할 일 줄은 둘까지예요)"
    complete = {"type": "buttons", "items": [{"label": "끝났어", "do": {"kind": "complete", "task_id": 2}}]}
    in_stack = {"type": "group", "layout": "stack", "children": [TEXT, {"type": "todo_rows", "task_ids": [2]}]}
    assert validate_props("ui_block", _block(in_stack, complete)) is None
    assert validate_props("ui_block", _block(TEXT, complete)) == (
        "props: complete_not_in_rows (완료 버튼의 할 일은 같은 카드의 할 일 줄에 있어야 해요)")
    assert validate_props("ui_block", _block({"type": "heading", "text": "제목"}, {"type": "divider"},
                                             {"type": "heading", "text": "둘"})) == (
        "props: block_no_content (내용 부품이 하나는 있어야 해요)")


def test_group_layout_errors():
    assert validate_props("ui_block", _block({"type": "group", "children": [TEXT, TEXT]})) == (
        "children.0.group: union_tag_not_found")
    assert validate_props("ui_block", _block({"type": "group", "layout": "grid", "children": [TEXT, TEXT]})) == (
        "children.0.group: union_tag_invalid")
    inner = {"type": "group", "layout": "stack", "children": [TEXT, TEXT]}
    err = validate_props("ui_block", _block({"type": "group", "layout": "stack", "children": [TEXT, inner]}))
    assert err.endswith(": union_tag_invalid")


def test_app_tool_count_unchanged():
    assert set(tool_names_for(RunContext(None, None, channel="app"))) - set(TOOL_NAMES) == {
        "ui_todo_list", "ui_choice", "ui_summary_card", "ui_habit_check", "pin_card", "unpin_card", "reorder_cards",
        "set_checkin_time",  # SP9-02(화면 조각이 아니다)
        "search_memos", "read_memo", "create_memo",  # SP9-03
    }
    assert not set(NEW) & set(tool_names_for(RunContext(None, None, channel="app")))
    assert set(NEW) <= set(BRAIN_COMPONENTS) and len(BRAIN_COMPONENTS) == 8
    assert PINNABLE_COMPONENTS == ("ui_todo_list", "ui_choice", "ui_summary_card")


@pytest.fixture
def cenv(tmp_path, conn):
    env = ToolEnv(tmp_path, conn)
    env.cards = CardsRepo(conn, env.clock)
    env.tools.cards = env.cards
    return env


def test_pin_card_rejects_new_components(cenv):
    ctx = RunContext(conversation_id=1, run_id=None, events=[], channel="app")
    for name in NEW:
        props = _load(min((PROPS / name / "ok").glob("*.json")))
        assert validate_props(name, props) is None
        out = cenv.tools.pin_card(ctx, component=name, props=props)
        assert out == {"error": "고정할 수 있는 화면 조각은 ui_todo_list, ui_choice, ui_summary_card이에요."}
    assert cenv.cards.active() == [] and ctx.events == []


@pytest.mark.parametrize("path", OK, ids=_id)
def test_ok_fixtures_pass_json_schema(path):
    schema = UI_COMPONENTS[path.parent.parent.name]["schema"]
    assert jsonschema.Draft202012Validator(schema).is_valid(_load(path))


def test_schema_only_bad_fixtures_fail_json_schema():
    """앱이 같은 판정을 하는 `bad`(BE 전용 code 밖)는 JSON Schema로도 실패한다(빈 곳 10)."""
    be_only = {"period_one", "value_over_max", "too_large", "bad_char", "banned_word", "slash",
               *("block_too_many", "buttons_place", "todo_rows_too_many", "divider_place", "block_no_content",
                 "complete_not_in_rows")}
    for path in BAD:
        code = path.stem.split("-", 1)[0]
        if code in be_only or (code == "not_unique" and path.parent.parent.name == "ui_date_choice"):
            continue
        schema = UI_COMPONENTS[path.parent.parent.name]["schema"]
        assert not jsonschema.Draft202012Validator(schema).is_valid(_load(path)), path


def test_catalog_schema_uses_nested_oneof():
    schema = UI_COMPONENTS["ui_block"]["schema"]
    defs = schema["$defs"]

    def resolve(s):
        return defs[s["$ref"].rsplit("/", 1)[1]] if "$ref" in s else s

    def oneofs(v):
        if isinstance(v, dict):
            if isinstance(v.get("oneOf"), list):
                yield v["oneOf"]
            for x in v.values():
                yield from oneofs(x)
        elif isinstance(v, list):
            for x in v:
                yield from oneofs(x)

    groups = [
        o for o in oneofs(schema)
        if len(o) == 2 and all(resolve(m).get("properties", {}).get("type", {}).get("const") == "group" for m in o)
    ]
    assert groups, "group은 layout으로 가르는 oneOf 둘이어야 한다"
    assert sorted(resolve(m)["properties"]["layout"]["const"] for m in groups[0]) == ["row", "stack"]
    # 바깥 oneOf는 부품 열 가지(group은 안쪽 oneOf 하나)
    outer = schema["properties"]["children"]["items"]["oneOf"]
    assert len(outer) == 10 and groups[0] in [m.get("oneOf") for m in outer]
