"""repair.yml의 publish 단계(리뷰 I1): Claude는 커밋만 하고, 셸 단계가 REPAIR_PAT으로 PR을 연다."""

from __future__ import annotations

import gh
import pytest
import repair_publish
from medic.fakes import FakeGitHub, FakeHttp


def _env():
    server = FakeGitHub()
    return server, gh.Api("tok", "o/r", http=FakeHttp(route=server.route))


def test_pr_body_starts_with_repairs_line():
    assert repair_publish.pr_body(7, "원인: x\n수정: y").splitlines()[:2] == ["Repairs #7", ""]
    assert repair_publish.pr_body(7, "Repairs #7\n\n원인").startswith("Repairs #7\n\n원인")
    assert repair_publish.pr_body(7, "").splitlines()[0] == "Repairs #7"
    # 다른 번호를 적었어도 첫 줄은 이 이슈
    assert repair_publish.pr_body(7, "Repairs #8\n원인").splitlines()[0] == "Repairs #7"


def test_publish_opens_pr_on_main_with_label():
    server, api = _env()
    n = server.add_issue("[incident] be:A x:f", ["incident", "repairing"])
    got = repair_publish.publish(api, n, f"auto-repair/{n}-1", pushed=True, title="fix: A", body="원인", comment="")
    assert got == "opened"
    pr = server.created_pulls[0]
    assert (pr["head"]["ref"], pr["base"]["ref"], pr["title"]) == (f"auto-repair/{n}-1", "main", "fix: A")
    assert pr["body"].startswith(f"Repairs #{n}\n")
    assert [x["name"] for x in pr["labels"]] == ["auto-repair"]


def test_publish_reuses_open_pr_and_defaults_title():
    server, api = _env()
    n = server.add_issue("[incident] be:A x:f", ["incident", "repairing"])
    server.add_pull(f"auto-repair/{n}-1")
    assert repair_publish.publish(api, n, f"auto-repair/{n}-1", pushed=True, title="", body="", comment="") == "exists"
    assert server.created_pulls == []
    m = server.add_issue("[incident] be:B x:f", ["incident", "repairing"])
    repair_publish.publish(api, m, f"auto-repair/{m}-1", pushed=True, title="x" * 500, body="", comment="")
    assert len(server.created_pulls[0]["title"]) == 200
    k = server.add_issue("[incident] be:C x:f", ["incident", "repairing"])
    repair_publish.publish(api, k, f"auto-repair/{k}-1", pushed=True, title="  ", body="", comment="")
    assert server.created_pulls[1]["title"] == f"fix: incident #{k}"


def test_publish_without_commits_posts_diagnosis_comment():
    server, api = _env()
    n = server.add_issue("[incident] be:A x:f", ["incident", "repairing"])
    assert repair_publish.publish(api, n, f"auto-repair/{n}-1", pushed=False, title="", body="",
                                  comment="재현 못 함") == "commented"
    assert server.comments[n] == ["재현 못 함"]
    assert server.created_pulls == []
    assert repair_publish.publish(api, n, f"auto-repair/{n}-1", pushed=False, title="", body="", comment="") == "nothing"


def test_publish_rejects_unexpected_branch_name():
    server, api = _env()
    n = server.add_issue("[incident] be:A x:f", ["incident", "repairing"])
    try:
        repair_publish.publish(api, n, "main", pushed=True, title="t", body="", comment="")
        raise AssertionError("must refuse")
    except ValueError:
        pass
    assert server.created_pulls == []


# --- 최종 리뷰 I-1: 수리 PR이 장애 이슈를 저절로 닫으면 안 된다 ------------------------


@pytest.mark.parametrize(("raw", "want"), [
    ("Fixes #42", "Refs #42"),
    ("fixes #42", "Refs #42"),
    ("CLOSES #42", "Refs #42"),
    ("close #42", "Refs #42"),
    ("closed #42", "Refs #42"),
    ("fix #42", "Refs #42"),
    ("fixed #42", "Refs #42"),
    ("resolve #42", "Refs #42"),
    ("Resolves #42", "Refs #42"),
    ("resolved #42", "Refs #42"),
    ("Fixes: #42", "Refs #42"),
    ("Fixes:#42", "Refs #42"),
    ("**Fixes** #42", "**Refs #42"),
    ("Closes o/r#42", "Refs o/r#42"),
    ("closes dahun428-fx/my-planner#42", "Refs dahun428-fx/my-planner#42"),
    ("Fixes https://github.com/o/r/issues/42", "Refs https://github.com/o/r/issues/42"),
    ("Fixes GH-42", "Refs GH-42"),
    ("원인 고침. Fixes #1, closes #2", "원인 고침. Refs #1, Refs #2"),
])
def test_neutralise_closing_keywords(raw, want):
    assert repair_publish.neutralise(raw) == want


@pytest.mark.parametrize("text", [
    "fix: 날짜 경계 오류",          # 이슈를 가리키지 않는 낱말은 그대로
    "fixed the bug in #section",    # `#` 뒤가 숫자가 아님
    "prefix #42",                   # 낱말 경계 밖
    "Repairs #42",
    "fixture #42",
    "See #42",
])
def test_neutralise_keeps_non_closing_text(text):
    assert repair_publish.neutralise(text) == text


def test_publish_strips_closing_keywords_from_title_and_body():
    server, api = _env()
    n = server.add_issue("[incident] be:A x:f", ["incident", "repairing"])
    repair_publish.publish(api, n, f"auto-repair/{n}-1", pushed=True, title=f"Fix #{n}: 날짜",
                           body=f"Fixes #{n}\n\n원인. Closes o/r#{n}. resolved #{n}", comment="")
    pr = server.created_pulls[0]
    assert pr["title"] == f"Refs #{n}: 날짜"
    assert pr["body"].splitlines()[0] == f"Repairs #{n}"
    assert not repair_publish.CLOSING_RE.search(pr["title"])
    assert not repair_publish.CLOSING_RE.search(pr["body"])
    # 첫 줄의 `Fixes #n`도 본문에서 이웃 줄로 남지 않고 중화된다
    assert f"Refs #{n}" in pr["body"]



def test_prompt_forbids_closing_keywords():
    from pathlib import Path

    prompt = (Path(__file__).resolve().parents[2] / ".github" / "repair-prompt.md").read_text(encoding="utf-8")
    assert "닫기 낱말" in prompt and "`Fixes #N`" in prompt and "`Refs #N`" in prompt
