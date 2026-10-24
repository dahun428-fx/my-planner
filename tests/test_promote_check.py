"""develop → main 자동 승격 검사 (배포 흐름 스펙 6.2, 10장)."""

import importlib.util
import re
import sys
import tomllib
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("promote_check", ROOT / "scripts" / "promote_check.py")
pc = importlib.util.module_from_spec(_spec)
sys.modules["promote_check"] = pc
_spec.loader.exec_module(pc)

CONFIG = tomllib.loads((ROOT / "config.toml").read_text(encoding="utf-8"))
APP_CTX = "Vercel – my-planner"
DASH_CTX = "Vercel – my-planner-dashboard"
DEV = "dahun428-fx"
# 2026-10-28(수) 14:00 KST: 차단 구간 밖
NOW = datetime(2026, 10, 28, 5, 0, tzinfo=UTC)


def kst(day: int, hh: int, mm: int) -> datetime:
    return datetime(2026, 10, day, hh, mm, tzinfo=UTC) - timedelta(hours=9)


def commit(sha, *files, ago=60):
    return pc.Commit(sha, tuple(files), NOW - timedelta(minutes=ago))


def ok(state="success", creator=DEV):
    return pc.Status(state, creator)


def inputs(commits, **kw):
    head = commits[-1].sha
    base = {
        "head": head,
        "main": "m0",
        "behind_by": 0,
        "commits": commits,
        "ci": {c.sha: "success" for c in commits},
        "windows": {c.sha: "skipped" for c in commits},
        "statuses": {head: {pc.STAGING_CONTEXT: ok()}},
        "now": NOW,
        "blackouts": pc.blackouts(CONFIG, NOW),
        "require_staging_be": True,
        "dev_login": DEV,
        "vercel_contexts": {"web/app/": APP_CTX, "web/dashboard/": DASH_CTX},
    }
    base.update(kw)
    return pc.Inputs(**base)


def test_docs_only_promotes():
    d = pc.decide(inputs([commit("a1", "docs/x.md")]))
    assert d.action == "promote"


def test_trigger_not_head_is_noop():
    d = pc.decide(inputs([commit("a1", "docs/x.md")], trigger_sha="old"))
    assert d.action == "noop"


def test_already_promoted_is_noop():
    d = pc.decide(inputs([commit("a1", "docs/x.md")], main="a1"))
    assert d.action == "noop"


def test_not_ancestor_blocks():
    d = pc.decide(inputs([commit("a1", "docs/x.md")], behind_by=2))
    assert d.action == "blocked"
    assert "동기화" in d.reason


def test_head_ci_failure_blocks_and_pending_waits():
    cs = [commit("a1", "docs/x.md")]
    assert pc.decide(inputs(cs, ci={"a1": "failure"})).action == "blocked"
    assert pc.decide(inputs(cs, ci={"a1": None})).action == "wait"
    assert pc.decide(inputs(cs, ci={})).action == "wait"


def test_windows_checked_on_last_be_commit_not_head():
    cs = [commit("a1", "src/my_planner/app.py"), commit("a2", "docs/x.md")]
    w = {"a1": "failure", "a2": "skipped"}
    assert pc.decide(inputs(cs, windows=w)).action == "blocked"
    w = {"a1": "success", "a2": "skipped"}
    assert pc.decide(inputs(cs, windows=w)).action == "promote"
    # BE 커밋이 Windows를 건너뛰었으면(실제 통과 아님) 막는다
    w = {"a1": "skipped", "a2": "skipped"}
    assert pc.decide(inputs(cs, windows=w)).action == "blocked"


def test_windows_bundled_push_uses_later_run():
    # a1(BE)과 a2가 한 번에 푸시돼 a1에는 실행이 없다: 그 변경을 시험한 a2 실행을 본다(더 앞 커밋이 아님)
    cs = [commit("a0", "src/old.py"), commit("a1", "src/a.py"), commit("a2", "docs/x.md")]
    ci = {"a0": "success", "a2": "success"}
    assert pc.decide(inputs(cs, ci=ci, windows={"a0": "success", "a2": "success"})).action == "promote"
    assert pc.decide(inputs(cs, ci=ci, windows={"a0": "success", "a2": "failure"})).action == "blocked"
    assert pc.decide(inputs(cs, ci=ci, windows={"a0": "success", "a2": None})).action == "wait"


def test_staging_be_rules():
    cs = [commit("a1", "docs/x.md")]
    assert pc.decide(inputs(cs, statuses={})).action == "wait"
    assert pc.decide(inputs(cs, statuses={"a1": {pc.STAGING_CONTEXT: ok("pending")}})).action == "wait"
    assert pc.decide(inputs(cs, statuses={"a1": {pc.STAGING_CONTEXT: ok("failure")}})).action == "blocked"
    other = {"a1": {pc.STAGING_CONTEXT: ok(creator="someone")}}
    assert pc.decide(inputs(cs, statuses=other)).action == "wait"
    assert pc.decide(inputs(cs, dev_login=None)).action == "reject"


def test_without_staging_be_waits_30_minutes():
    assert pc.decide(inputs([commit("a1", "docs/x.md", ago=29)], require_staging_be=False)).action == "wait"
    assert pc.decide(inputs([commit("a1", "docs/x.md", ago=30)], require_staging_be=False)).action == "promote"


def test_vercel_checked_on_last_commit_touching_folder():
    cs = [commit("a1", "web/app/src/x.ts"), commit("a2", "src/a.py")]
    st = {"a2": {pc.STAGING_CONTEXT: ok()}}
    w = {"a1": "skipped", "a2": "success"}
    # a2는 web/app을 안 바꿔 Vercel이 건너뜀: S에 상태가 없어도 a1을 본다
    assert pc.decide(inputs(cs, statuses=st, windows=w)).action == "wait"
    st["a1"] = {APP_CTX: pc.Status("success", pc.VERCEL_LOGIN)}
    assert pc.decide(inputs(cs, statuses=st, windows=w)).action == "promote"
    st["a1"] = {APP_CTX: pc.Status("failure", pc.VERCEL_LOGIN)}
    assert pc.decide(inputs(cs, statuses=st, windows=w)).action == "blocked"
    st["a1"] = {APP_CTX: pc.Status("success", DEV)}  # 위조: vercel[bot]이 아님
    assert pc.decide(inputs(cs, statuses=st, windows=w)).action == "wait"


def test_dashboard_context():
    cs = [commit("a1", "web/dashboard/src/x.ts")]
    st = {"a1": {pc.STAGING_CONTEXT: ok(), DASH_CTX: pc.Status("success", pc.VERCEL_LOGIN)}}
    assert pc.decide(inputs(cs, statuses=st)).action == "promote"


@pytest.mark.parametrize(
    ("at", "blocked"),
    [
        (kst(28, 8, 39), False),
        (kst(28, 8, 40), True),
        (kst(28, 9, 39), True),
        (kst(28, 9, 40), False),
        (kst(28, 17, 10), True),
        (kst(28, 18, 10), False),
        (kst(31, 9, 40), True),  # 토요일 10:00
        (kst(25, 18, 30), True),  # 일요일 18:00(저녁 체크인 + 회고)
    ],
)
def test_blackout_boundaries_for_be_changes(at, blocked):
    cs = [commit("a1", "src/a.py", ago=60)]
    cs = [replace(c, committed_at=at - timedelta(hours=1)) for c in cs]
    i = inputs(cs, now=at, blackouts=pc.blackouts(CONFIG, at), windows={"a1": "success"})
    assert (pc.decide(i).action == "wait") is blocked


def test_blackout_ignored_for_web_and_tests_only():
    at = kst(28, 9, 0)
    st = {"a1": {pc.STAGING_CONTEXT: ok(), APP_CTX: pc.Status("success", pc.VERCEL_LOGIN)}}
    cs = [commit("a1", "web/app/src/x.ts", "tests/test_a.py")]
    i = inputs(cs, now=at, blackouts=pc.blackouts(CONFIG, at), statuses=st, windows={"a1": "success"})
    assert pc.decide(i).action == "promote"


def test_skip_staging_be():
    cs = [commit("a1", "docs/x.md")]
    assert pc.decide(inputs(cs, statuses={}, skip_staging_be=True)).action == "promote"
    cs = [commit("a1", "src/a.py")]
    assert pc.decide(inputs(cs, statuses={}, skip_staging_be=True, windows={"a1": "success"})).action == "reject"


def test_recheck_cron_matches_schedule_end_of_blackout():
    """promote.yml의 재확인 cron(UTC)이 config.toml 회차 시각 + 40분(KST)과 같다(스펙 6.2의 6)."""
    text = (ROOT / ".github" / "workflows" / "promote.yml").read_text(encoding="utf-8")
    crons = set(re.findall(r'cron: "(\d+ \d+ \* \* [0-9,\-]+)"  # recheck', text))
    sched = CONFIG["schedule"]
    expected = set()
    for kind, dow in (("weekday", "1-5"), ("weekend", "0,6")):
        for key in ("morning_brief", "evening_checkin"):
            h, m = map(int, sched[key][kind].split(":"))
            end = (h * 60 + m + 40 - 9 * 60) % (24 * 60)
            expected.add(f"{end % 60} {end // 60} * * {dow}")
    assert crons == expected


def test_promote_lists_prs_and_truncated_blocks():
    cs = [replace(commit("a1", "docs/x.md"), prs=("148",)), replace(commit("a2", "docs/y.md"), prs=("149",))]
    d = pc.decide(inputs(cs))
    assert d.action == "promote"
    assert d.prs == ("148", "149")
    assert "#148 #149" in d.reason
    assert pc.decide(inputs(cs, truncated=True)).action == "blocked"


def test_develop_behind_main_is_noop():
    d = pc.decide(replace(inputs([commit("a1", "docs/x.md")]), commits=[]))
    assert d.action == "noop"
    assert "새 커밋이 없음" in d.reason
