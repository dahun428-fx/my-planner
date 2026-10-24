"""`.github/scripts`와 medic의 약속: 같은 라벨·제목·알림 틀, `src/`를 가져오지 않음, 토큰을 찍지 않음."""

from __future__ import annotations

import ast
import re
from pathlib import Path

import gh
import notify_telegram
from medic.fakes import FakeHttp, FakeResponse

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / ".github" / "scripts"
MEDIC = ROOT / "src" / "my_planner_medic"


def test_format_constants_match_medic():
    # 시험 안에서만 둘을 함께 가져온다(스크립트는 src/를 모른다)
    from my_planner_medic import github as mg
    from my_planner_medic import notify as mn
    from my_planner_medic import updater as mu
    from my_planner_medic import watcher as mw

    assert gh.INCIDENT == mg.INCIDENT
    assert gh.RECORD == mg.RECORD
    assert gh.HEARTBEAT == mg.HEARTBEAT
    assert gh.PART_LABELS == mg.PART_LABELS
    assert gh.TITLE_PREFIX == mg.TITLE_PREFIX == mw._TITLE_PREFIX
    assert gh.incident_title("be:X a:b") == mg.incident_title("be:X a:b")
    assert gh.CI_MAIN == mw.CI_MAIN
    assert gh.TZ == mw.ACTIONS_TZ
    assert gh.STALE_RE.pattern == mw._STALE_RE.pattern
    assert gh.FAILED_RE.pattern == mu._FAILED_RE.pattern
    assert gh.GAVE_UP_TEXT == mn.GAVE_UP_TEXT
    assert gh.ROLLED_BACK_TEXT == mn.ROLLED_BACK
    assert gh.AS_IS_TEXT == mn.AS_IS


def test_literal_labels_match_medic_source():
    medic_src = "\n".join(p.read_text(encoding="utf-8") for p in MEDIC.glob("*.py"))
    for label in (gh.REPAIRING, gh.MERGED, gh.ROLLED_BACK, gh.RECURRED, gh.NEEDS_DAHUN):
        assert f'"{label}"' in medic_src, label
    # 4.4: repairing·merged는 medic 상태 이름과도 같다
    from my_planner_medic.store import STATES

    assert gh.REPAIRING in STATES and gh.MERGED in STATES


def test_heartbeat_body_format_matches_medic_writer():
    src = (MEDIC / "watcher.py").read_text(encoding="utf-8")
    assert 'f"last_seen: {_z(now)}, sha: {safe_token(sha)}, next_run: {_z(next_run(self._cfg, now))}"' in src
    import heartbeat_check

    got = heartbeat_check.parse_body("last_seen: 2026-10-26T05:00:00Z, sha: abc, next_run: 2026-10-26T08:30:00Z")
    assert got is not None and got[0].isoformat() == "2026-10-26T05:00:00+00:00"


def test_scripts_do_not_import_src():
    for path in SCRIPTS.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            for name in names:
                assert not name.startswith(("my_planner", "src")), f"{path.name}: {name}"


def test_telegram_failure_never_prints_token(capsys):
    http = FakeHttp()
    http.queue("POST", "/bot123:SECRET/sendMessage", FakeResponse(401, {"description": "bot123:SECRET bad"}))
    assert notify_telegram.send("hi", http=http, token="123:SECRET", chat_id="42") is False
    http.outage = 0
    assert notify_telegram.send("hi", http=http, token="123:SECRET", chat_id="42") is False
    out = capsys.readouterr()
    assert "SECRET" not in out.out + out.err
    assert http.requests[0].json == {"chat_id": "42", "text": "hi"}


def test_telegram_not_configured_is_false(capsys):
    assert notify_telegram.send("hi", http=FakeHttp(), token="", chat_id="42") is False
    assert "not configured" in capsys.readouterr().out


def test_workflows_never_interpolate_event_text_into_run():
    """`${{ github.event.* }}`·`inputs.*`는 `run:`에 바로 넣지 않고 env로 넘긴다(워크플로 주입 막기)."""
    for name in ("repair.yml", "watch.yml", "signal.yml"):
        text = (ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")
        in_run = False
        indent = 0
        for line in text.splitlines():
            stripped = line.lstrip()
            cur = len(line) - len(stripped)
            if in_run and stripped and cur <= indent:
                in_run = False
            if re.match(r"(- )?run: ?", stripped):
                in_run, indent = True, cur
            if in_run:
                assert "${{" not in line, f"{name}: {line.strip()}"


def _jobs(text: str) -> dict[str, str]:
    """`jobs:` 아래 작업 이름 → 그 작업의 글(PyYAML 없이 들여쓰기로)."""
    body = text[text.index("\njobs:\n") + len("\njobs:\n"):]
    out: dict[str, str] = {}
    name = None
    for line in body.splitlines():
        m = re.match(r"^  ([A-Za-z0-9_-]+):$", line)
        if m:
            name = m[1]
            out[name] = ""
        elif name is not None:
            out[name] += line + "\n"
    return out


def test_workflows_write_with_repair_pat_not_github_token():
    for name in ("repair.yml", "watch.yml", "signal.yml"):
        text = (ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")
        assert "secrets.REPAIR_PAT" in text
        assert "secrets.GITHUB_TOKEN" not in text
        assert "permissions:" in text
        for job, body in _jobs(text).items():
            if "github.token" in body:
                # 읽기 전용 GITHUB_TOKEN은 Claude 작업에만, 쓰기 권한 없이
                assert (name, job) in {("repair.yml", "fix"), ("repair.yml", "refix")}, job
                assert ": write" not in body, job


def test_claude_jobs_never_see_repair_pat():
    """리뷰 I1: Claude와 의존성 설치는 머지 권한 있는 PAT을 env·git 설정 어디에서도 못 본다."""
    jobs = _jobs((ROOT / ".github" / "workflows" / "repair.yml").read_text(encoding="utf-8"))
    for job in ("fix", "refix"):
        assert "anthropics/claude-code-action@v1" in jobs[job]
        assert "secrets.REPAIR_PAT" not in jobs[job], job
        assert "persist-credentials: false" in jobs[job]
    for job, body in jobs.items():
        if "actions/checkout@v4" in body:
            assert "persist-credentials: false" in body, job
            assert "token:" not in body.split("actions/checkout@v4")[1].split("- ")[0], job
    # 푸시·PR은 Claude 없는 작업에서만
    for job in ("publish", "republish"):
        assert "claude-code-action" not in jobs[job] and "git push origin" in jobs[job]
        assert "::add-mask::" in jobs[job]


def test_workflow_triggers_and_names():
    wf = ROOT / ".github" / "workflows"
    watch = (wf / "watch.yml").read_text(encoding="utf-8")
    assert watch.startswith("name: watch\n")
    assert "    - cron: '7 */2 * * *'" in watch  # 2시간(GitHub Free 분량, Dahun 결정)
    assert watch.index("heartbeat_check.py") < watch.index("sweep.py")
    signal = (wf / "signal.yml").read_text(encoding="utf-8")
    assert "  workflow_run:\n    workflows: [ci]\n    types: [completed]\n    branches: [main]\n" in signal
    assert "contains(github.event.branches.*.name, 'main')" in signal
    repair = (wf / "repair.yml").read_text(encoding="utf-8")
    assert 'run-name: "repair #${{ github.event.issue.number || inputs.issue }}"' in repair  # sweep이 잇는 제목
    assert "format('repair-{0}', github.event.issue.number || inputs.issue)" in repair
    assert "cancel-in-progress: false" in repair and "group: repair-merge" in repair
    assert repair.count("ref: main") == 6  # 수리 PR 브랜치를 쓰는 refix·republish 말고는 main에서(핫픽스)
    assert "claude_code_oauth_token: ${{ secrets.CLAUDE_CODE_OAUTH_TOKEN }}" in repair
    assert "anthropics/claude-code-action@v1" in repair and "--max-turns 60" in repair
    ci = (wf / "ci.yml").read_text(encoding="utf-8")
    assert ci.count("run: ruff check src tests .github/scripts\n") == 2
    assert "rhysd/actionlint/v1.7.7/scripts/download-actionlint.bash" in ci
