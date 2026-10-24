"""repair.yml의 publish 단계(리뷰 I1): Claude는 커밋만 하고, 셸 단계가 REPAIR_PAT으로 PR을 연다."""

from __future__ import annotations

import gh
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
