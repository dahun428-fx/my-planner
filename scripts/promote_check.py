"""develop → main 자동 승격 (배포 흐름 스펙 6장). 표준 라이브러리만 쓴다.

`decide`는 GitHub 응답을 모은 `Inputs`만 보고 판정하는 순수 함수다(테스트 대상).
`main`은 `promote.yml`에서 돌며 GitHub에서 입력을 모으고, 판정대로 `main`을 빨리감기하거나
`release:blocked` 이슈를 열고 닫는다. 읽기는 `GITHUB_TOKEN`, ref 쓰기는 `RELEASE_PAT`.
"""

from __future__ import annotations

import base64
import json
import os
import re
import sys
import tomllib
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

# 바뀌면 운영 BE가 재시작하는 파일(SP6 업데이터 재시작 목록). 회차 차단 구간은 이것만 본다
BE_RESTART = ("src/", "scripts/", "requirements.lock", "pyproject.toml", "config.toml")
# CI의 be 필터(재시작 목록 + tests/). Windows 검사는 이것을 본다
BE_CI = (*BE_RESTART, "tests/")
WINDOWS_JOB = "be (windows-latest)"
# CI 웹 작업과 그 경로 필터(ci.yml의 web·dashboard 필터와 같다). develop은 Vercel이 빌드하지 않으므로 이것이 웹을 막는다
WEB_JOBS = {
    "web-app": ("web/app/", "web/shared/", "DESIGN.md"),
    "web-dashboard": ("web/dashboard/", "web/shared/", "DESIGN.md"),
}
STAGING_CONTEXT = "staging/be"
QUIET = timedelta(minutes=30)  # staging/be가 없을 때(임시) develop 머리가 조용해야 하는 시간
BLACKOUT_BEFORE = timedelta(minutes=20)
BLACKOUT_AFTER = timedelta(minutes=40)
BLOCKED_LABEL = "release:blocked"
WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


@dataclass(frozen=True)
class Commit:
    sha: str
    files: tuple[str, ...]
    committed_at: datetime  # UTC
    prs: tuple[str, ...] = ()  # 커밋 메시지의 (#N)


@dataclass(frozen=True)
class Status:
    state: str  # success | failure | error | pending
    creator: str


@dataclass
class Inputs:
    head: str  # develop 머리 S
    main: str
    behind_by: int  # compare main...S 의 behind_by (0이면 main이 S의 조상)
    commits: list[Commit]  # main..S, 오래된 것부터
    ci: dict[str, str | None]  # sha → 그 sha의 develop push `ci` 결론(실행이 없거나 진행 중이면 None)
    windows: dict[str, str | None]  # sha → 그 실행의 `be (windows-latest)` 결론(skipped 포함)
    web: dict[str, dict[str, str | None]]  # sha → 웹 작업 이름 → 그 실행의 결론(실행이 있는 sha만)
    statuses: dict[str, dict[str, Status]]  # sha → context → 가장 새 상태
    now: datetime  # UTC
    blackouts: list[tuple[datetime, datetime]]  # [시작, 끝) UTC
    require_staging_be: bool
    dev_login: str | None
    trigger_sha: str | None = None  # status 트리거의 sha
    skip_staging_be: bool = False
    truncated: bool = False  # compare가 커밋을 다 주지 못함(250개 넘음)


@dataclass(frozen=True)
class Decision:
    action: str  # promote | wait | noop | blocked | reject
    reason: str
    prs: tuple[str, ...] = field(default=())


def _touches(c: Commit, prefixes: tuple[str, ...]) -> bool:
    return any(f.startswith(p) or f == p for f in c.files for p in prefixes)


def decide(i: Inputs) -> Decision:
    if i.trigger_sha is not None and i.trigger_sha != i.head:
        return Decision("noop", f"트리거 {i.trigger_sha[:7]}은 develop 머리가 아님")
    if i.main == i.head:
        return Decision("noop", "main이 이미 develop 머리")
    if not i.commits:
        return Decision("noop", "develop에 main보다 새 커밋이 없음")
    if i.truncated:
        return Decision("blocked", "main..develop 커밋이 250개를 넘어 검사할 수 없음")
    # 1. 빨리감기 가능
    if i.behind_by != 0:
        return Decision("blocked", "main이 develop의 조상이 아님: main → develop 동기화 필요")
    be_restart = any(_touches(c, BE_RESTART) for c in i.commits)
    if i.skip_staging_be and be_restart:
        return Decision("reject", "skip_staging_be는 BE 파일이 바뀐 승격에 쓸 수 없음")
    # 2. S의 CI
    ci = i.ci.get(i.head)
    if ci is None:
        return Decision("wait", f"{i.head[:7]} CI 진행 중이거나 없음")
    if ci != "success":
        return Decision("blocked", f"{i.head[:7]} CI {ci}")
    # 3. BE를 바꾼 마지막 커밋의 Windows 작업, 웹을 바꾼 마지막 커밋의 웹 작업. 묶음 푸시라 그 커밋에 실행이 없으면,
    # 그 변경을 시험한 실행은 같은 푸시의 머리(더 뒤 커밋)에 있다. 머리 CI만 보면 뒤 커밋이 경로 필터로
    # 그 작업을 건너뛰어 앞 커밋의 실패를 놓친다
    gates = [(WINDOWS_JOB, BE_CI, i.windows)]
    gates += [(job, paths, {sha: r.get(job) for sha, r in i.web.items()}) for job, paths in WEB_JOBS.items()]
    for job, paths, results in gates:
        last = next((k for k in range(len(i.commits) - 1, -1, -1) if _touches(i.commits[k], paths)), None)
        if last is None:
            continue
        run = next((c for c in i.commits[last:] if c.sha in results), None)
        if run is None:
            return Decision("wait", f"{i.commits[last].sha[:7]} {job} 실행 없음")
        w = results[run.sha]
        if w is None:
            return Decision("wait", f"{run.sha[:7]} {job} 진행 중")
        if w != "success":
            hint = ", CI 재실행 필요" if w == "cancelled" else ""
            return Decision("blocked", f"{run.sha[:7]} {job} {w}{hint}")
    # 4. 스테이징 BE
    if i.require_staging_be and not i.skip_staging_be:
        st = i.statuses.get(i.head, {}).get(STAGING_CONTEXT)
        if st is None or st.state == "pending":
            return Decision("wait", f"{i.head[:7]} staging/be 대기")
        if not i.dev_login:
            return Decision("reject", "DEV_STATUS_LOGIN 미설정")
        if st.creator != i.dev_login:
            return Decision("wait", f"{i.head[:7]} staging/be를 다른 계정({st.creator})이 올림")
        if st.state != "success":
            return Decision("blocked", f"{i.head[:7]} staging/be {st.state}")
    elif not i.require_staging_be:
        head_time = next(c.committed_at for c in i.commits if c.sha == i.head)
        if i.now - head_time < QUIET:
            return Decision("wait", f"{i.head[:7]} 30분 대기")
    # 5. Vercel 스테이징은 보지 않는다: develop은 자동 배포하지 않는다(하루 배포 한도, 스펙 5.1).
    # 웹 빌드·테스트는 CI의 web 작업이 막는다
    # 6. 회차 차단 구간
    if be_restart and any(start <= i.now < end for start, end in i.blackouts):
        return Decision("wait", "회차 차단 구간")
    prs = tuple(dict.fromkeys(pr for c in i.commits for pr in c.prs))
    listed = f", {' '.join('#' + n for n in prs)}" if prs else ""
    return Decision("promote", f"{i.main[:7]} → {i.head[:7]} ({len(i.commits)}커밋{listed})", prs)


def blackouts(config: dict, now: datetime, tz: str | None = None) -> list[tuple[datetime, datetime]]:
    """`config.toml [schedule]`의 회차 시각 t마다 [t−20분, t+40분). 어제·오늘·내일을 UTC로 돌려준다."""
    zone = ZoneInfo(tz or config.get("timezone", "Asia/Seoul"))
    sched = config.get("schedule", {})
    local_today = now.astimezone(zone).date()
    out: list[tuple[datetime, datetime]] = []
    for delta in (-1, 0, 1):
        d = local_today + timedelta(days=delta)
        for t in _times_on(sched, d):
            at = datetime.combine(d, t, zone)
            out.append(((at - BLACKOUT_BEFORE).astimezone(UTC), (at + BLACKOUT_AFTER).astimezone(UTC)))
    return out


def _parse_hhmm(s: str) -> time:
    h, m = s.split(":")
    return time(int(h), int(m))


def _times_on(sched: dict, d: date) -> list[time]:
    weekend = d.weekday() >= 5
    times = []
    for key in ("morning_brief", "evening_checkin"):
        entry = sched.get(key, {})
        value = entry.get("weekend" if weekend else "weekday")
        if value:
            times.append(_parse_hhmm(value))
    review = sched.get("review", {}).get("week", {})
    if review.get("day") == WEEKDAYS[d.weekday()] and review.get("time"):
        times.append(_parse_hhmm(review["time"]))
    return times


# ---- GitHub ------------------------------------------------------------------------------


class GitHub:
    def __init__(self, repo: str, token: str) -> None:
        self.repo = repo
        self.token = token

    def call(self, method: str, path: str, body: dict | None = None, token: str | None = None) -> object:
        url = path if path.startswith("https://") else f"https://api.github.com/repos/{self.repo}{path}"
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Authorization", f"Bearer {token or self.token}")
        req.add_header("Accept", "application/vnd.github+json")
        req.add_header("X-GitHub-Api-Version", "2022-11-28")
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
        return json.loads(raw) if raw else None

    def get(self, path: str) -> object:
        return self.call("GET", path)


def _ci_for(gh: GitHub, sha: str) -> tuple[str | None, dict[str, str | None], bool]:
    """(ci 결론, 작업 이름 → 결론, 실행 있음). 가장 새 develop push `ci` 실행을 본다."""
    names = (WINDOWS_JOB, *WEB_JOBS)
    runs = gh.get(f"/actions/runs?head_sha={sha}&event=push&branch=develop&per_page=20")["workflow_runs"]
    runs = [r for r in runs if r["name"] == "ci"]
    if not runs:
        return None, {}, False
    run = max(runs, key=lambda r: r["id"])
    if run["status"] != "completed":
        return None, dict.fromkeys(names), True
    if run["conclusion"] == "cancelled":
        # concurrency 대기열에서 밀려 취소된 실행: 다음 실행은 이 커밋의 변경을 시험하지 않으므로 막힘으로 본다
        return run["conclusion"], dict.fromkeys(names, "cancelled"), True
    jobs = {j["name"]: j for j in gh.get(f"/actions/runs/{run['id']}/jobs?per_page=50")["jobs"]}
    out = {n: jobs[n]["conclusion"] if n in jobs and jobs[n]["status"] == "completed" else None for n in names}
    return run["conclusion"], out, True


def _statuses_for(gh: GitHub, sha: str) -> dict[str, Status]:
    out: dict[str, Status] = {}
    for s in gh.get(f"/commits/{sha}/statuses?per_page=100"):  # 가장 새 것부터
        out.setdefault(s["context"], Status(s["state"], (s.get("creator") or {}).get("login", "")))
    return out


def gather(gh: GitHub, env: dict[str, str], config: dict, now: datetime, head: str) -> Inputs:
    main_sha = gh.get("/branches/main")["commit"]["sha"]
    cmp = gh.get(f"/compare/main...{head}")
    commits: list[Commit] = []
    ci: dict[str, str | None] = {}
    windows: dict[str, str | None] = {}
    web: dict[str, dict[str, str | None]] = {}
    statuses: dict[str, dict[str, Status]] = {}
    for c in cmp.get("commits", []):
        detail = gh.get(f"/commits/{c['sha']}")
        files = tuple(f["filename"] for f in detail.get("files", []))
        at = datetime.fromisoformat(detail["commit"]["committer"]["date"])
        prs = tuple(re.findall(r"\(#(\d+)\)", c["commit"]["message"].split("\n", 1)[0]))
        commits.append(Commit(c["sha"], files, at, prs))
    for c in commits:
        conclusion, jobs, has_run = _ci_for(gh, c.sha)
        if c.sha == head or has_run:
            ci[c.sha] = conclusion
        if has_run:
            windows[c.sha] = jobs[WINDOWS_JOB]
            web[c.sha] = {n: jobs[n] for n in WEB_JOBS}
        if c.sha == head:
            statuses[c.sha] = _statuses_for(gh, c.sha)
    trigger = env.get("TRIGGER_SHA") or None
    return Inputs(
        head=head,
        main=main_sha,
        behind_by=int(cmp.get("behind_by", 0)),
        commits=commits,
        ci=ci,
        windows=windows,
        web=web,
        statuses=statuses,
        now=now,
        blackouts=blackouts(config, now),
        require_staging_be=env.get("REQUIRE_STAGING_BE", "").lower() == "true",
        dev_login=env.get("DEV_STATUS_LOGIN") or None,
        trigger_sha=trigger,
        skip_staging_be=env.get("SKIP_STAGING_BE", "").lower() == "true",
        truncated=int(cmp.get("total_commits", 0)) > len(commits),
    )


def _open_blocked(gh: GitHub) -> dict | None:
    issues = gh.get(f"/issues?state=open&labels={urllib.request.quote(BLOCKED_LABEL)}&per_page=10")
    issues = [x for x in issues if "pull_request" not in x]  # /issues는 PR도 준다
    return issues[0] if issues else None


def report_blocked(gh: GitHub, reason: str, sha: str) -> None:
    line = f"승격 막힘: {reason} (develop `{sha[:7]}`)"
    issue = _open_blocked(gh)
    if issue is None:
        gh.call("POST", "/issues", {"title": "develop → main 승격이 막혔어요", "body": line, "labels": [BLOCKED_LABEL]})
        return
    last = issue.get("body", "")
    if issue.get("comments", 0):  # 오래된 것부터 오므로 마지막 쪽을 읽는다
        page = (int(issue["comments"]) - 1) // 100 + 1
        comments = gh.get(f"/issues/{issue['number']}/comments?per_page=100&page={page}")
        last = comments[-1]["body"] if comments else last
    if last.strip() != line:
        gh.call("POST", f"/issues/{issue['number']}/comments", {"body": line})


def close_blocked(gh: GitHub, sha: str) -> None:
    issue = _open_blocked(gh)
    if issue is None:
        return
    gh.call("POST", f"/issues/{issue['number']}/comments", {"body": f"풀렸어요: `{sha[:7]}`가 main으로 승격됐어요."})
    gh.call("PATCH", f"/issues/{issue['number']}", {"state": "closed", "state_reason": "completed"})


def main() -> int:
    env = dict(os.environ)
    gh = GitHub(env["GITHUB_REPOSITORY"], env["GITHUB_TOKEN"])
    # 스크립트는 main(기본 브랜치)의 것으로 돌고, 회차 시각은 승격할 develop 머리의 config.toml에서 읽는다
    head = gh.get("/branches/develop")["commit"]["sha"]
    raw = gh.get(f"/contents/config.toml?ref={head}")["content"]
    config = tomllib.loads(base64.b64decode(raw).decode("utf-8"))
    inputs = gather(gh, env, config, datetime.now(UTC), head)
    d = decide(inputs)
    print(f"{d.action}: {d.reason}")
    summary = env.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write(f"**{d.action}**: {d.reason}\n")
    if d.action == "promote":
        try:
            gh.call("PATCH", "/git/refs/heads/main", {"sha": inputs.head, "force": False}, token=env["RELEASE_PAT"])
        except urllib.error.HTTPError as e:  # 경합 등: 다음 트리거가 다시 본다
            print(f"빨리감기 실패 {e.code}: {e.read().decode(errors='replace')}")
            return 1
        close_blocked(gh, inputs.head)
    elif d.action == "blocked":
        report_blocked(gh, d.reason, inputs.head)
    elif d.action == "reject":
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
