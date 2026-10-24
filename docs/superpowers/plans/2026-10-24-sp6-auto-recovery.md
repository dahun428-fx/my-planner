# SP6 자동 복구 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan ticket-by-ticket. Steps use checkbox (`- [ ]`) syntax for tracking. 티켓 하나를 끝낼 때마다 `.claude/agents/code-reviewer.md`로 리뷰하고, 지적을 반영한 뒤 다음 티켓으로 간다.

**Goal:** 노트북의 medic(감시자 + 업데이터)이 BE·운영 앱의 장애를 GitHub 이슈로 올리고, GitHub Actions의 Claude가 고쳐 CI 확인 뒤 머지하고, medic이 CI 성공 커밋을 배포하고 확인 실패 시 배포 롤백한다.

**Architecture:**
- `src/my_planner_medic/`: 표준 라이브러리만 쓰는 별도 패키지(스펙 2장). `my_planner`와 외부 패키지를 가져오지 않는다(티켓 01의 시험이 지킨다). 바깥 세계(시계, HTTP, git·PowerShell 실행, 파일)는 생성자로 받는 작은 이음매 뒤에 두고, 시험은 가짜로 돈다.
- BE 쪽 변경은 작다: `/health` 필드 하나, `POST /client-errors`, `POST /internal/notify`. 쓰기 경로(ADR 0007)는 늘지 않는다(둘 다 DB에 쓰지 않는다).
- 워크플로는 얇은 YAML + `.github/scripts/*.py`(표준 라이브러리, GitHub REST를 `urllib`로). 판단 로직은 파이썬 함수라서 `tests/workflows/`에서 가짜 HTTP로 시험한다.
- 순서: 착수 전 검증 → CI(이후 모든 PR의 문) → BE 계약 → medic 순수 로직(감지) → medic GitHub·감시자 → 업데이터 → 알림·웹 확인 → 작업 등록 → Actions 수리 → 노트북 수용 확인.

**Tech Stack:** Python 3.12 표준 라이브러리(`urllib.request`, `sqlite3`, `subprocess`, `tomllib`, `zoneinfo` + `tzdata`는 이미 venv에 있으나 medic은 venv 밖 경로를 대비해 `ZoneInfo` 실패 시 고정 `+09:00`), GitHub Actions(`anthropics/claude-code-action@v1`, `actions/checkout@v4`, `actions/setup-python@v5`, `actions/setup-node@v4`), 운영 앱은 기존 Next.js 15 + Vitest.

**Spec:** [`docs/superpowers/specs/2026-10-24-sp6-auto-recovery-design.md`](../specs/2026-10-24-sp6-auto-recovery-design.md) (v3, main `8d8bd4b`). ADR [0010](../../adr/0010-full-auto-repair-in-cloud-laptop-only-deploys.md). 용어 [`GLOSSARY.md`](../../../GLOSSARY.md) "자동 복구 (SP6)".
- 스펙과 이 계획이 다르면 스펙이 맞다. 이 계획이 스펙의 빈 곳을 정한 자리는 끝의 "계획의 결정"에 모았고, 1은 티켓 08이, 나머지는 티켓 10이 스펙에 옮긴다.

## Global Constraints

- (2장) medic은 "**표준 라이브러리만** 쓴다(`urllib`, `sqlite3`, `subprocess`, `json`). `my_planner` 패키지와 venv의 외부 패키지를 가져오지 않는다."
- (2장) "medic은 `planner.db`에 쓰지 않고 자기 DB `state/medic.db`만 쓴다. 예외는 배포 롤백 때 `planner.db` 파일을 백업으로 바꾸는 것 하나이고, 그때 BE 작업은 꺼져 있다."
- (7장) 이슈에는 **허용 목록**만: "지문, 예외 종류, 가린 파일·줄·함수, 이벤트 이름, 수준, 로거 이름, 횟수, 시각, 커밋, 4.1의 `/health` 필드, 3.3의 `client_error` 필드". 경로는 3.1 "경로 가리기" 규칙.
- (3.3) 브라우저 에러 "**메시지는 보내지 않는다**".
- (4.3) 머지는 "**CI 성공 확인**이 필수이고, 그것을 Claude가 아니라 셸 단계가 한다."
- (4.2) 워크플로 안의 쓰기는 기본 `GITHUB_TOKEN`으로 하지 않는다(`REPAIR_PAT` 또는 Claude App 토큰).
- (5장 5단계) 끄기는 "`Disable-ScheduledTask` → `Stop-ScheduledTask`", 켜기는 "`Enable-` → `Start-`". medic이 어떤 길로 끝나도 `my-planner` 작업이 꺼진 채 남지 않는다.
- (6장) 장애 하나에 결과 알림 한 번. 문구는 6장 표의 틀 그대로. 하루 `max_notices_per_day`(5).
- (8장) 비밀값은 `.env`와 저장소 시크릿에만. 로그·이슈·커밋 어디에도 토큰이 없다.
- 시간대 `Asia/Seoul`, 논리적 날짜 경계 04:00(`config.toml`). medic의 "오늘"(알림 상한, 하루 한 번)은 논리적 날짜다. Actions의 "오늘"(머지 한도, 하트비트 알림)은 Asia/Seoul 달력 날짜다(스펙 4.3, 3.5 문장 그대로).
- BE 쪽 Global Constraints(SP1·SP3-4 계획)는 그대로다: 로그에 본문·토큰 없음, 접근 로그는 경로 틀만.

## Actions 예산 (GitHub Free private 월 2,000분 기준, S7로 확인)

| 항목 | 횟수 | 분(올림, Windows ×2) | 월 |
|---|---|---|---|
| `watch.yml`(하트비트 확인 + sweep을 한 작업으로, 60분 cron) | 720/월 | 1 | 720 |
| `ci` PR(ubuntu ~4분 + 웹 바뀐 경우 ~3분) | 60 PR × 2 푸시 | ~6 | 720 |
| `ci` main 푸시(ubuntu 4 + windows 6×2) | 60 | ~16 | 960 |
| `repair`(Claude 단계 ~15분 + 머지 대기) | 10 | ~25 | 250 |

합 약 2,650분. 2,000분을 넘으므로 S7에서 플랜을 확인하고, Free면 Dahun에게 고르게 한다: Pro(월 3,000분) 또는 `watch` 120분 주기 + main 푸시 Windows를 `src/`·`requirements.lock` 바뀐 커밋만. 계획은 `watch.yml` 하나(티켓 10)로 짠다.

## 작업 방식

- TDD 주기는 SP1·SP3-4 계획과 같다: 시험 하나 → `python -m pytest <노드 id> -v` FAIL → 구현 → PASS.
- 티켓 끝 검증: `python -m pytest -q` → `0 failed`, `ruff check src tests` → `All checks passed!`(티켓 10부터 `ruff check src tests .github/scripts`), 웹을 고친 티켓은 `cd web/app && npm test && npm run typecheck && npm run build` 성공. 그다음 `code-reviewer`, 커밋.
- medic 시험은 `tests/medic/`, 워크플로 시험은 `tests/workflows/`. 가짜는 `tests/medic/fakes.py`(티켓 04)에 모은다.
- 시험 날짜는 요일을 박는다: 2026-10-26(월) 평일 일정(아침 09:00, 저녁 17:30), 2026-10-31(토) 주말(10:00, 18:00).

## Review Focus

스펙이 암시하지만 스펙 12장 절차가 다루지 않고, 실제로 먼저 부딪힐 다섯 가지. 시험은 맡은 티켓에 있다.

1. **로그 파일 회전 경계**: 자정에 `my-planner.jsonl`이 `.YYYY-MM-DD`로 이름이 바뀌고 새 파일이 생긴다. 읽던 위치가 새 파일 크기보다 크면 처음부터, 회전된 파일의 남은 줄도 한 번만 읽어야 한다. → 05 `test_rotation_reads_tail_of_rotated_then_new_once`
2. **반쯤 쓰인 마지막 줄·깨진 JSON 줄**: BE가 쓰는 도중 읽으면 줄 끝 `\n`이 없다. 그 줄은 다음 회차로 미루고, 깨진 줄은 건너뛰고 셈만 한다(medic이 죽지 않는다). → 05 `test_partial_last_line_deferred`, `test_bad_json_line_skipped`
3. **GitHub가 안 될 때**(네트워크 끊김, 5xx, 401 만료 토큰, 403 rate limit): 감시자는 계속 돌고, 못 올린 이슈는 `medic.db`에 남았다가 다음 회차에 올린다. 같은 지문으로 이슈가 두 번 생기지 않는다. 배포는 CI 결과를 확인 못 하면 하지 않는다. → 06 `test_github_down_keeps_incident_pending_then_files_once`, 07 `test_ci_unknown_does_not_deploy`
4. **작업 폴더가 더럽거나 로컬 커밋이 앞서 있음**(Dahun이 노트북에서 직접 고친 경우): `merge --ff-only`가 실패한다. 배포하지 않고 하루 한 번 알리며, 손으로 고친 파일을 지우거나 덮지 않는다. → 07 `test_dirty_tree_never_resets`, `test_ff_only_failure_is_not_rollback`
5. **노트북이 배포·확인 도중 잠들거나 꺼짐**: 깨어난 뒤 `deploy_in_progress`가 남아 있다. 확인 창은 잠든 시간을 세지 않고, 깨어난 뒤 절전 직후 10분 유예를 지나 다시 확인한다(잠들었다는 이유로 롤백하지 않는다). → 07 `test_sleep_during_verify_restarts_window`, `test_startup_with_deploy_in_progress_completes_rollback_and_enables_task`

---

### 티켓 00: 착수 전 검증 (S1~S6)

**목표:** 스펙 10장 S1~S6의 답을 `docs/spikes/2026-10-sp6.md`에 적는다. S2·S6은 클라우드에서, S1·S4는 시험 저장소 브랜치에서, S3·S5는 노트북(Remote Control 세션, SP1 분담 규칙)에서.
**막는 티켓:** 없음. 결과에 따라 01(S2), 07(S3·S5), 09(S1·S4·S6)를 대안대로 고친다.

- [ ] S2: `windows-latest` 러너에서 `pip install -r requirements.lock && pip install -e . --no-deps && python -m pytest -q` (01의 `ci.yml` 초안을 임시 브랜치로 돌린다) → `0 failed` 또는 실패 목록.
- [ ] S6: `GET /repos/dahun428-fx/my-planner/branches/main/protection` → `200`/`404`면 쓸 수 있음, `403 "Upgrade to GitHub Pro"`면 없음.
- [ ] S1: 임시 워크플로에서 `claude-code-action`(입력 `claude_code_oauth_token`)이 브랜치를 푸시하고 PR을 열고, 그 PR에서 `ci.yml`이 `pull_request` 이벤트로 도는가. 안 돌면 `REPAIR_PAT`으로 PR을 여는 대안을 적는다.
- [ ] S4: Vercel 프로젝트(운영 앱)의 `main` 배포가 `status` 이벤트(`context` 접두 `Vercel`)로 워크플로를 깨우는가.
- [ ] S3: 노트북에서 시험용 작업 `my-planner-s3`(같은 사용자, `pythonw -c "import time;time.sleep(600)"`)를 등록하고, 일반 권한 `pythonw`에서 `subprocess`로 Disable·Stop·Enable·Start 네 명령을 차례로 → 모두 반환 코드 `0`, Stop 뒤 State `Ready`. 실제 `my-planner`는 건드리지 않는다.
- [ ] S5: **두뇌 호출 도중에** 07의 끄기 순서(Disable → Stop → `Get-ScheduledTask` State가 `Ready`가 될 때까지 폴링 → 남은 `claude` 자식 프로세스 트리 `taskkill /T /F`)를 한 뒤 `git merge --ff-only`와 `pip install -r requirements.lock`(판 하나 올린 브랜치)이 잠금 오류 없이 되는가.
- [ ] S7: 저장소 플랜과 이번 달 Actions 사용량(Dahun 계정 설정 화면, Dahun 확인). GitHub Free private은 월 2,000분이고 Windows는 2배로 센다. 아래 **Actions 예산**을 넘으면 Dahun에게 플랜 결정을 묻는다.
- [ ] **Commit** `docs(spikes): SP6 S1-S6 results`

---

### 티켓 01: CI 워크플로와 medic 패키지 뼈대

**목표:** 모든 PR과 `main` 푸시에서 BE(Windows 필수 + Ubuntu)와 바뀐 웹 앱을 검사한다(스펙 4.5). medic 패키지가 표준 라이브러리만 쓰는지 시험으로 지킨다.
**막는 티켓:** 00(S2 결과)

**Files:**
- Create: `.github/workflows/ci.yml`, `src/my_planner_medic/__init__.py`, `tests/medic/__init__.py`, `tests/medic/test_stdlib_only.py`
- Modify: `pyproject.toml`(`my_planner_medic`는 `find`가 잡는다. `.github/scripts`는 아직 없으므로 ruff 경로에 넣지 않는다. 티켓 10이 더한다)

**Interfaces**
- Produces: CI 작업 이름 `be (windows-latest)`, `be (ubuntu-latest)`, `web-app`. 워크플로 이름 `ci`(티켓 07·09가 `GET /actions/runs?head_sha=…`에서 `name == "ci"`로 찾는다).

- [ ] `test_medic_imports_only_stdlib`: `src/my_planner_medic/**/*.py`와 `scripts/medic_boot.py`(있으면)를 `ast`로 읽어 모든 `import`의 첫 이름이 `sys.stdlib_module_names` 또는 `my_planner_medic`이다. `my_planner`는 실패.
- [ ] `ci.yml`: `on: pull_request, push: branches [main]`. `be` 행렬은 `ubuntu-latest`는 항상, `windows-latest`는 `push`(main)와 `auto-repair/*` 브랜치 PR에서만(분량, 위 Actions 예산). 업데이터는 `main` 푸시 실행을 보므로 Windows 검사는 배포 전에 늘 돈다. Python 3.12, `pip install -r requirements.lock && pip install -e ".[dev]" --no-deps` → `ruff check src tests`(티켓 10이 `.github/scripts`를 더함) → `python -m pytest -q`. `web-app`(작업 환경 변수 `NEXT_PUBLIC_CONNECT_SRC: https://*.example.ts.net`, `next.config.mjs`가 빌드에서 이 값을 요구한다): `dorny/paths-filter@v3`로 `web/app/**`가 바뀐 경우만 `npm ci && npm test && npm run typecheck && npm run build`(바뀌지 않으면 성공으로 끝나는 빈 단계. 필수 검사가 "대기"로 남지 않게).
- [ ] 이 PR에서 세 작업이 모두 초록. S2 실패 시험이 있었으면 이 티켓에서 고친다(건너뛰기·skip 표시 금지).
- [ ] S6 결과가 "쓸 수 있음"이면 PR 설명에 `main` 보호 규칙(필수 검사 `be (windows-latest)`)을 Dahun이 켜는 절차를 적는다(설정 변경은 저장소 밖 조작이라 Dahun 확인).
- [ ] **Review + Commit** `ci: BE (windows+ubuntu) and web app checks; medic package skeleton`

---

### 티켓 02: BE 계약 — `/health` 필드, `POST /client-errors`, `POST /internal/notify`

**목표:** 스펙 3.3, 3.4, 6장의 BE 쪽. 할 일·대화·회차 표에 쓰지 않는다(`/internal/notify`의 푸시 결과는 기존 `deliver_notice`가 `push_subscriptions`에 남긴다. SP3-4의 고정 안내와 같다).
**막는 티켓:** 01

**Files:**
- Create: `src/my_planner/api/recovery.py`
- Modify: `api/health.py`(필드), `api/server.py`(`WRITE_ROUTES`에 둘), `api/models.py`(모델, `schema_bundle`), `harness/dispatcher.py`(기존 `_send_notice(text) -> bool`을 공개 `send_notice(text) -> Channel | None`으로 바꾸고 기존 호출처는 `is not None`으로. 원문 기록 `[-]` 동작은 그대로), `web/app/src/api/schema.json`·`types.gen.ts`(`npm run gen:types`)
- Test: `tests/test_api_recovery.py`, `tests/test_api_health.py`

**Interfaces**
- Produces:
  - `/health`의 `inbound_pending_oldest_at: str | None` = `SELECT MIN(received_at) FROM inbound_pending WHERE brain_done = 0`를 `api_time`으로. 안전 모드 응답에는 없다.
  - `POST /api/v1/client-errors` 본문 `ClientErrorBody(app: Literal["app","dashboard"], version: str ≤40, route: str ≤120 정규식 `^/[A-Za-z0-9_\-/\[\]]*$`, name: str ≤80 정규식 `^[A-Za-z][A-Za-z0-9_.]*$`, frames: list[str] ≤10개 각 ≤160, at: datetime)`, 모르는 키 거부. 성공 `204`, 검증 실패 `422 {"error": {"code": "invalid_request", …}}`(스펙 3.3이 422를 정했다. 다른 본문 검증의 `400`과 다르다, "계획의 결정" 7). 로그 `log.warning("client_error", extra={app, version, route, name, frames})`.
  - `POST /api/v1/internal/notify` 본문 `RecoveryNoticeBody(text: str 1..500, kind: Literal["recovery"])`. `await deps.dispatcher.send_notice(text)` → `200 {"channel": "app" | "telegram"}`, 못 보내면 `503 {"error": {"code": "unavailable", …}}`. 로그 `recovery_notice_sent {channel}`(본문 없음). 두뇌·`proactive_messages`를 건드리지 않는다.
  - 두 경로 모두 기존 인증·본문 제한 미들웨어를 탄다. 안전 모드에서는 기존 규칙대로 `503`.

- [ ] `test_health_inbound_pending_oldest_at`: 비었으면 `null`. `brain_done=0` 두 행(10:00, 10:05 KST) + `brain_done=1` 한 행(09:00) → `"…T01:00:00Z"`.
- [ ] `test_client_error_logged_without_message`: 본문에 `"message": "할 일 제목"`을 넣으면 `422`(모르는 키). 올바른 본문 → `204`, 로그 줄에 `client_error`와 `route`가 있고, 시험이 넣은 어떤 다른 문자열도 없다.
- [ ] `test_client_error_rejects_bad_route_and_long_frames`(매개변수: `route="/today?x=1"`, `frames` 11개, `name="a b"`) → `422`.
- [ ] `test_client_error_writes_nothing`: 요청 전후 `planner.db`의 모든 표 행 수가 같다.
- [ ] `test_send_notice_existing_callers_unchanged`(`tests/test_dispatcher_*` 중 안내를 쓰는 시험이 그대로 통과).
- [ ] `test_internal_notify_uses_effective_channel`: 푸시 구독 없음 → `FakeSender`가 글 하나 받음, 응답 `{"channel": "telegram"}`. `usage_state.proactive_messages` 그대로.
- [ ] `test_internal_notify_requires_token` → 토큰 없이 `401`.
- [ ] `test_recovery_routes_in_schema_bundle`: `/schema`에 `ClientErrorBody`, `RecoveryNoticeBody`.
- [ ] 스펙 SP3-4 6장 표에 두 경로 한 줄씩(이 티켓에서 문서도 고친다).
- [ ] **Review + Commit** `feat(api): client error reports, recovery notices, inbound_pending_oldest_at`

---

### 티켓 03: 운영 앱 에러 보고

**목표:** 운영 앱이 잡히지 않은 에러와 렌더 에러를 3.3 규칙대로 BE에 보낸다.
**막는 티켓:** 02

**Files:**
- Create: `web/app/src/lib/errorReport.ts`, `web/app/src/lib/errorReport.test.ts`
- Modify: `web/app/next.config.mjs`(`env.NEXT_PUBLIC_APP_VERSION = (process.env.VERCEL_GIT_COMMIT_SHA ?? "dev").slice(0, 7)` → 본문 `version`)
- Modify: `web/app/src/pages/_app.tsx`(`window` `error`·`unhandledrejection` 듣기, 기존 에러 경계가 있으면 거기서도 `report`), `web/app/src/api/client.ts`(요청 함수 재사용)

**Interfaces**
- Produces: `normalizeRoute(pathname: string): string`(호출처는 `router.pathname`을 넘겨 이미 `[id]` 틀이다. 함수는 그래도 남은 숫자·UUID 조각 → `[id]`, 쿼리·해시 제거), `stripHash(frame: string): string | null`(Next 15 Pages Router 청크 이름: `/_next/static/chunks/pages/today-3f9a1c2b.js:1:2345` → `pages/today.js:1:2345`, `/_next/static/chunks/281-a1b2c3d4.js:1:9` → `281.js:1:9`, 자체 번들이 아니면 `null`. 시험 자료는 `npm run build` 뒤 `out/_next/static/chunks`의 실제 이름에서 고른다), `class ErrorReporter { constructor(send: (body) => Promise<void>, now: () => number); report(err: unknown, pathname: string): void }`.
- 규칙(3.3): 같은 `name + route`는 페이지가 열린 동안 한 번, 분당 5개, `navigator.onLine === false`면 버림, 보내기 실패는 조용히 버림(재귀 보고 금지). 개발용 "에러 던지기" 버튼은 `NEXT_PUBLIC_MEDIC_PROBE === "1"` 빌드에서만 설정 화면에 보인다(12장 조건 7).

- [ ] `normalizeRoute`: `/checkin/42` → `/checkin/[id]`, `/today?x=1#a` → `/today`.
- [ ] `stripHash`: 위 예, `https://cdn.example/x.js:1:1` → `null`.
- [ ] `report never sends message`: `new Error("할 일 제목")` 보고 → 보낸 본문 JSON에 `할 일 제목` 없음, 키는 정확히 `app, version, route, name, frames, at`.
- [ ] `dedupe and rate limit`: 같은 에러 3번 → 1번 보냄. 다른 에러 7개를 1분 안에 → 5번.
- [ ] `offline drops`, `send failure does not throw or re-report`.
- [ ] `npm test && npm run typecheck && npm run build && npm run check:csp` 성공.
- [ ] **Review + Commit** `feat(app): report browser errors to BE without messages`

---

### 티켓 04: medic 설정·저장소·가짜

**목표:** medic이 읽는 설정과 자기 DB, 시험용 가짜를 만든다.
**막는 티켓:** 01

**Files:**
- Create: `config.medic.toml`, `src/my_planner_medic/{config,store,clock,shell}.py`, `tests/medic/{fakes,test_config,test_store}.py`

**Interfaces**
- Produces:
  - `config.py`: `@dataclass(frozen=True) MedicConfig(root: Path, enabled: bool, watch_interval_s=120, deploy_interval_s=300, heartbeat_minutes=30, late_run_grace_minutes=15, no_reply_minutes=10, health_fail_streak=3, verify_minutes=10, web_verify_minutes=60, max_notices_per_day=5, keep_pre_deploy=5, keep_failed=3, repo="dahun428-fx/my-planner", api_base: str, api_enabled: bool, api_token: str | None, github_token: str | None, telegram_token: str | None, owner_telegram_id: str | None, timezone: str, day_boundary: time, schedule: dict[str, Any])`(`config.toml`의 `[schedule]` 그대로, `review.week`는 3단 중첩). `load_config(root: Path) -> MedicConfig`: `config.medic.toml` + `config.toml`의 `timezone`, `day_boundary`, `[schedule]`, `[api]`(`api_base = f"http://{host}:{port}/api/v1"`) + `.env`(`API_TOKEN`, `MEDIC_GITHUB_TOKEN`, `TELEGRAM_BOT_TOKEN`, `OWNER_TELEGRAM_ID`). `.env`는 `KEY=VALUE` 줄, `#` 주석, 따옴표 벗김만 지원(표준 라이브러리). `api_enabled = [api].enabled and len(API_TOKEN) >= 43`(BE와 같은 기준).
  - `MedicConfig.__repr__`은 토큰 필드를 `***`로.
  - `store.py`: `MedicStore(path: Path)`. 표 `incidents(fingerprint TEXT PK, part TEXT, state TEXT, issue_number INT, first_seen TEXT, last_seen TEXT, count INT, synced_count INT, last_synced_at TEXT, failures INT DEFAULT 0, resolved_at TEXT, detail_json TEXT)`, `kv(key TEXT PK, value TEXT)`, `notices(id INTEGER PK, logical_date TEXT, text TEXT, sent_at TEXT)`. 메서드 `upsert_signal(sig: Signal, now) -> Incident`, `get(fp) -> Incident | None`, `by_state(*states) -> list[Incident]`, `set_state(fp, state, **fields)`, `kv_get(key) -> str | None`, `kv_set(key, value)`, `kv_json_get/kv_json_set`. 상태 값은 스펙 4.4: `open, repairing, merged, deploying, resolved, gave_up`.
  - `kv` 키 표(모든 티켓과 `medic_boot.py`가 이 이름만 쓴다):

    | 키 | 형식 | 쓰는 곳 → 읽는 곳 |
    |---|---|---|
    | `log_cursor` | `{"file": str, "offset": int}` | 06 |
    | `deployed_sha` | 40자 sha | 06이 시작 시 없으면 `git rev-parse HEAD`로 채움, 07이 배포 성공·롤백마다 → 06(하트비트, 이슈 본문) |
    | `deploy_in_progress` | 07 표 | 07 |
    | `bad_shas` | `["sha", …]` | 07, `medic_boot.py` → 07 |
    | `medic_pinned` | sha | `medic_boot.py` → 07(깨끗함 검사 예외, 다음 배포 전 정리) |
    | `last_tick_at`, `last_heartbeat_at`, `health_streak` | ISO, ISO, int | 06 |
    | `daily:<key>` | 논리적 날짜 | 08 |
  - `shell.py`: `Shell` 프로토콜 `run(args: list[str], *, cwd: Path, timeout: int = 600, env: dict[str, str] | None = None) -> tuple[int, str]`, `SubprocessShell`(Windows에서 `CREATE_NO_WINDOW`). `FakeShell`도 여기 맞춘다.
  - `clock.py`: `Clock` 프로토콜 `now() -> datetime`(aware UTC), `SystemClock`.
  - `tests/medic/fakes.py`: `FakeClock(start)`(`.advance(minutes=)`), `FakeHttp`(경로·메서드별 응답 큐, 받은 요청 기록), `FakeShell`(명령 → `(returncode, stdout)` 규칙, 실행 기록), `FakeFs`는 두지 않는다(`tmp_path` 사용).

- [ ] `test_load_config_merges_three_files`: 임시 루트에 세 파일 → 값 확인, `api_base == "http://127.0.0.1:8787/api/v1"`.
- [ ] `test_short_api_token_disables_api_checks` → `api_enabled is False`.
- [ ] `test_repr_hides_tokens`: `repr(cfg)`에 토큰 문자열 없음.
- [ ] `test_store_upsert_counts_and_keeps_first_seen`, `test_kv_json_roundtrip`, `test_schema_created_once`(두 번 열어도 같음).
- [ ] **Review + Commit** `feat(medic): config, state store and test fakes`

---

### 티켓 05: 감지 순수 로직 — 로그 읽기, 가리기, 지문, 헬스 규칙, 다음 회차

**목표:** 스펙 3.1, 3.2(첫 문장), 3.5의 `next_run`, 7장을 입출력 없는 함수로.
**막는 티켓:** 04

**Files:**
- Create: `src/my_planner_medic/{logs,redact,signals,schedule}.py`, `tests/medic/test_{logs,redaction,signals,schedule}.py`

**Interfaces**
- Produces:
  - `logs.py`: `LogCursor(file: str, offset: int)`. `read_new_lines(log_dir: Path, cursor: LogCursor | None) -> tuple[list[dict], LogCursor, int]`(새 레코드, 새 커서, 깨진 줄 수). 회전 규칙은 Review Focus 1·2.
  - `redact.py`: `relpath(frame: str, root: Path) -> str`(스펙 3.1 경로 가리기: 저장소 안 → `src/my_planner/x.py:12 fn`, `site-packages` → `site-packages/aiohttp/x.py:3 fn`, 그 밖 → `<외부>:3 fn`). `allowed_log_row(rec: dict, root) -> dict`(키 `ts, level, logger, msg, exc_type, exc_where`만, `exc_where`는 `relpath`). `allowed_health(h: dict) -> dict`(4.1 목록만). `issue_body(incident: Incident, rows: list[dict], health: dict | None, sha: str) -> str`(4.1 틀, 마크다운).
  - 정상 지연 억제: `outside_reasons`에 `plan_open`(`/health`의 `plan_open == true`)과 `proactive_cap`(`proactive.sent_today >= proactive.cap`)을 더한다. 둘 다 SP1 따라잡기가 일부러 회차를 `pending`으로 두는 경우다(`loop/catchup.py`).
  - 행 없는 지연: `runs` 행은 `runner.tick`이 만들 때만 생기므로, `next_run`(이 티켓 `schedule.py`) + 15분이 지났고 `/health`의 `last_tick_at`이 그보다 이르면(tick이 멈춤) `late_run:tick_stalled`.
  - `signals.py`: `@dataclass(frozen=True) Signal(fingerprint: str, part: Literal["be","app","dashboard","vercel","ci"], kind: Literal["exception","warn_burst","client_error","health","late_run","no_reply","record"], at: datetime)`. `log_signals(records, root, *, now, warn_window: dict[str, list[datetime]]) -> list[Signal]`(3.1 표 1~3행, 경고 폭주에서 `third_party_log`와 `client_error`는 뺀다, 경고 1시간 20번). `outside_reasons(health: dict, now) -> list[str]`(`polling_down`, `auth`, `limited`, `paused`). `HealthProbe(status: int | None, body: dict | None)`(`None` = 연결 안 됨·10초 초과). `health_signals(probe, now, *, streak: int, suppress: bool, cfg) -> tuple[list[Signal], int]`(새 연속 실패 수 반환. 3번째부터 `health:*`, `safe_mode`는 `kind="record"`, 코드 밖 사유가 있으면 헬스·`late_run`·`no_reply` 모두 없음, `suppress`(절전 유예·배포 중)면 없음).
  - 지문 문자열은 스펙 3.1 그대로: `be:<Exc> <relpath>:<func>`, `be-warn:<event>`, `<app>:<name> <route>`, `health:unreachable|auth|bind|safe_mode`, `late_run:<loop>`, `no_reply`, `vercel:<context>`, `ci:main`.
  - `schedule.py`: `next_run(cfg: MedicConfig, now: datetime) -> datetime`(`[schedule]`의 아침·저녁·주간 회고, 주말 판정은 Asia/Seoul 요일, 오늘 남은 것이 없으면 다음 날).

- [ ] `test_rotation_reads_tail_of_rotated_then_new_once`, `test_partial_last_line_deferred`, `test_bad_json_line_skipped`(Review Focus 1·2).
- [ ] `test_relpath_rules`(매개변수 3: 저장소, `site-packages`, `C:\Users\dahun\AppData\x.py` → `<외부>`). Windows 경로는 `PureWindowsPath`로 나누고 대소문자를 무시해 비교한다(ubuntu CI에서도 같은 결과). 로그 파일은 tick마다 열고 닫는다(핸들을 쥐면 Windows 회전 rename이 실패한다).
- [ ] `test_issue_body_contains_no_personal_strings`(스펙 완료 조건 8): 가짜 레코드에 `text="치과 예약"`, `title`, `memo`, `args`, `C:\Users\dahun\…` 경로, health에 `runs_today[].skip_reason="개인 사유"`·`brain.calls_today` → 본문에 그 문자열 없음, 지문과 `KeyError`는 있음.
- [ ] `test_exception_fingerprint_uses_deepest_own_frame`, `test_fingerprint_falls_back_to_last_frame`, `test_third_party_and_client_error_never_burst`, `test_warn_burst_at_20_in_hour`.
- [ ] `test_health_streak_three_then_signal`, `test_401_is_health_auth`, `test_outside_reasons_suppress_late_run_and_no_reply`(매개변수 4), `test_safe_mode_is_record_kind`.
- [ ] `test_plan_open_and_proactive_cap_suppress_late_run`, `test_tick_stalled_without_run_row`(월 17:46, `runs_today`에 저녁 행 없음, `last_tick_at` 16:00 → `late_run:tick_stalled`).
- [ ] `test_late_run_after_15_minutes`(월 17:30 `pending`, 17:44 없음, 17:46 `late_run:evening_checkin`), `test_no_reply_after_10_minutes`.
- [ ] `test_next_run`(매개변수: 월 08:00 → 월 09:00, 월 18:00 → 화 09:00, 금 18:00 → 토 10:00, 일 17:00 → 일 18:00 주간 회고).
- [ ] **Review + Commit** `feat(medic): log reading, redaction, fingerprints and health rules`

---

### 티켓 06: GitHub 이음매, 감시자, 하트비트

**목표:** 스펙 3.2, 3.5(하트비트 쓰기), 4.1. 2분마다 `Watcher.tick`이 신호를 모아 이슈를 열고·고치고·다시 연다.
**막는 티켓:** 05

**Files:**
- Create: `src/my_planner_medic/{http,github,watcher}.py`, `tests/medic/test_{github,watcher}.py`

**Interfaces**
- Consumes: 04·05 전부.
- Produces:
  - `http.py`: `Http` 프로토콜 `request(method, url, *, headers=None, json=None, timeout=10) -> tuple[int, dict | list | None, dict[str, str]]`(마지막은 응답 헤더). `UrllibHttp`(예외 → `(0, None, {})`, 본문·헤더를 로그에 남기지 않는다).
  - `github.py`: `GitHub(http, token, repo)`. `find_incident(fp) -> dict | None`(검색 API가 아니라 `GET /issues?labels=incident&state=all&per_page=100`과 `labels=record`에서 제목 `[incident] <fp>`를 맞춘다. 색인 지연이 없다), `pr_for_issue(n) -> tuple[str, str] | None`(본문에 `Repairs #n`인 머지된 PR의 제목·URL), `open_incident(fp, part, body) -> int`(라벨 `incident` + part 라벨, `record`면 `record`만), `update_body(n, body)`, `reopen(n, labels)`, `add_labels(n, labels)`, `remove_label(n, label)`, `close(n)`, `comment(n, body)`, `heartbeat(body)`(라벨 `heartbeat` 열린 이슈 하나, 없으면 만든다), `ci_conclusion(sha) -> Literal["success","failure","pending","unknown"]`(`GET /actions/runs?head_sha=&event=push`에서 `name == "ci"`), `commit_state(sha, context_prefix) -> str`, `repairs_in_range(base, head) -> list[int]`(`GET /compare/base...head` 커밋 메시지의 `Repairs #N`). 실패는 `GitHubUnavailable(kind: Literal["network","rate_limit","auth","server"])` 예외(403은 `x-ratelimit-remaining: 0`이면 `rate_limit`, 아니면 `auth`). `ci_conclusion`의 `"unknown"`은 "그런 실행이 없음"만 뜻하고, 조회 실패는 예외다.
  - `watcher.py`: `Watcher(cfg, store, gh: GitHub, http: Http, clock)`. `tick() -> None`: 로그 읽기 → 헬스 → 절전 유예(직전 tick과 10분 이상 → 10분 `suppress`) → 신호를 `store.upsert_signal` → 이슈 동기화(새 지문: 열기, 열린 것: 10분에 한 번 본문 고침, `resolved` 24시간 안: `reopen(["recurred"])`, `resolved` 24시간 뒤: 새 이슈) → 30분마다 `heartbeat("last_seen: …, sha: …, next_run: …")`. GitHub 실패는 그 회차만 건너뛴다. `suppressed: bool` 속성은 업데이터가 켠다(배포 중).
  - Actions가 연 이슈 가져오기: 30분마다 `GET /issues?labels=incident&state=open`에서 `medic.db`에 없는 지문(`vercel:`, `ci:main`)을 `open`으로 넣는다.
  - `ci:main` 해결: `main` 머리 커밋의 `ci`가 `success`가 되면 `ci:main` 장애를 `resolved`(닫고 "고쳤어요").
  - `stale-YYYY-MM-DD` 라벨은 오늘 것은 그대로 두고 지난 날짜 것만 뗀다(같은 날 두 번째 알림을 막는다, 스펙 3.5).

- [ ] `test_new_signal_opens_one_issue_then_updates_count`(스펙 완료 조건 1): 같은 지문 2번(4분 간격) → `POST /issues` 1번, 10분 뒤 본문 `PATCH` 1번에 발생 수 2.
- [ ] `test_github_down_keeps_incident_pending_then_files_once`(Review Focus 3): 첫 tick `FakeHttp` 503 → 다음 tick 성공 → 이슈 생성 정확히 1번.
- [ ] `test_lost_create_response_does_not_duplicate`: `POST /issues`가 서버에서는 만들어졌는데 응답이 끊김(`(0, None, {})`) → 다음 tick `find_incident`가 찾아 잇고, `POST`는 다시 없음.
- [ ] `test_recurrence_within_24h_reopens_with_label`, `test_recurrence_after_24h_opens_new`.
- [ ] `test_wake_grace_suppresses_late_run_for_10_minutes`: tick 간격 3시간 → 다음 10분 안 `late_run` 없음, 그 뒤 있음.
- [ ] `test_api_disabled_watches_logs_only`: `api_enabled=False` → 헬스 요청 0번, 로그 예외는 이슈.
- [ ] `test_heartbeat_every_30_minutes_keeps_todays_stale_label`, `test_imports_actions_opened_incidents`, `test_ci_main_resolves_on_green_main`.
- [ ] `test_safe_mode_opens_record_issue_without_incident_label`.
- [ ] **Review + Commit** `feat(medic): watcher files incidents and writes heartbeat`

---

### 티켓 07: 업데이터 — 배포, 확인, 배포 롤백, 시작 시 복구

**목표:** 스펙 5장 1~8단계, 시작 시 복구, 보관. 웹 확인(5.1)과 medic 자신의 갱신은 08·09.
**막는 티켓:** 06, 00(S3·S5)

**Files:**
- Create: `src/my_planner_medic/{tasks,dbfile,gitops,updater}.py`, `src/my_planner_medic/notify.py`(프로토콜만, 08이 구현), `tests/medic/test_{updater,dbfile}.py`

**Interfaces**
- Consumes: `GitHub.ci_conclusion`, `GitHub.repairs_in_range`, `Watcher.suppressed`, `MedicStore`.
- Produces:
  - `notify.py`(이 티켓은 프로토콜만): `NotifierLike` 프로토콜 `fixed(pr_title: str, pr_url: str)`, `gave_up(fingerprint: str, rolled_back: bool, issue_url: str, *, direct: bool = False)`, `daily(text: str, key: str)`. 시험은 `tests/medic/fakes.py`의 `FakeNotifier`(호출 기록)를 쓴다.
  - `gitops.py`: `GitOps(shell, root, token)`: `fetch_main()`, `head() -> str`, `changed_paths(a, b) -> list[str]`, `is_clean(ignore: list[str]) -> bool`, `merge_ff(sha) -> bool`, `reset_hard(sha)`, `checkout_paths(sha, paths)`. 인증은 argv가 아니라 환경 변수 `GIT_CONFIG_COUNT=1`, `GIT_CONFIG_KEY_0=http.https://github.com/.extraheader`, `GIT_CONFIG_VALUE_0=AUTHORIZATION: basic <base64(x-access-token:TOKEN)>`, 그리고 `GIT_TERMINAL_PROMPT=0`, `GCM_INTERACTIVE=never`(pythonw에는 콘솔이 없어 자격 증명 창이 뜨면 멈춘다).
  - `tasks.py`: `TaskControl(shell)`: `disable_stop(name="my-planner")`(Disable → Stop → State가 `Ready`가 될 때까지 30초 폴링 → 그 작업의 `pythonw`와 자식 트리 `taskkill /T /F`, S5), `enable_start(name="my-planner")`, `is_enabled(name) -> bool`. PowerShell 한 줄씩(`powershell -NoProfile -NonInteractive -Command "Disable-ScheduledTask -TaskName my-planner | Out-Null; Stop-ScheduledTask -TaskName my-planner"`).
  - `dbfile.py`: `schema_version(db: Path) -> int`(`mode=ro` URI), `backup_to(db: Path, dest: Path) -> None`(SQLite 백업 API, 임시 이름 → `os.replace`), `move_with_wal(db: Path, dest_dir: Path) -> None`(`db`, `-wal`, `-shm` 있는 것 모두), `restore(src: Path, db: Path) -> None`(`-wal`·`-shm` 지우고 복사), `prune(dir, pattern, keep: int)`.
  - `updater.py`: `Updater(cfg, store, gh, http: Http, tasks: TaskControl, git: GitOps, shell: Shell, watcher: Watcher, notifier: NotifierLike, clock)`. `tick() -> None`(5분마다, 스펙 5장 1~7단계, 확인은 상태 기계로 여러 tick에 걸침: `kv["deploy_in_progress"] = {prev_sha, new_sha, schema_before, started_at, phase: "verify"|"rollback_verify", verify_started_at, verify_elapsed_s}`), `recover_on_start() -> None`. 재시작 판단 경로 목록 `RESTART_PATHS = ("src/", "requirements.lock", "pyproject.toml", "config.toml", "scripts/")`. 확인 시간은 tick 간 실제 경과가 `2 × deploy_interval_s`보다 크면(잠듦) 그 구간을 `verify_elapsed_s`에 더하지 않는다.
  - 상태 동기화: 모든 `main` 전진(재시작 배포든 ff만이든)에서 `gh.repairs_in_range(prev, new)`의 이슈를 `merged`로 바꾼다. 재시작 배포는 확인 시작 때 `deploying`으로. ff만이면 웹 장애는 `merged`로 남아 08 `WebVerifier`가 맡고, BE 장애가 ff만 커밋으로 들어오면 바로 `resolved`.
  - 배포 성공 시 `deployed_sha`의 새 값과 `state/medic-last-good.json`(`{"sha": …}`)을 쓴다(09의 `medic_boot.py`가 읽는다).

- [ ] `test_git_token_never_in_argv`: `FakeShell` 기록의 모든 argv에 토큰 문자열 없음, `env`에 `GIT_TERMINAL_PROMPT=0`.
- [ ] `test_no_new_commit_noop`, `test_ci_pending_waits`, `test_ci_failure_skips_commit`, `test_ci_unknown_does_not_deploy`(Review Focus 3), `test_bad_sha_skipped`.
- [ ] `test_docs_only_change_fast_forwards_without_restart`: `FakeShell` 기록에 `Disable-ScheduledTask` 없음.
- [ ] `test_ff_only_marks_web_incident_merged`: `Repairs #21`(app 장애) 웹만 바뀐 커밋 → 21이 `merged`.
- [ ] `test_defers_while_run_running_up_to_30_minutes`.
- [ ] `test_deploy_order`(스펙 5단계): 기록 순서가 `schema_version` → `kv deploy_in_progress` → disable/stop → 백업 → `git merge --ff-only` → (`requirements.lock` 바뀜) `pip install -r` → `pip install -e . --no-deps` → enable/start.
- [ ] `test_verify_success_resolves_repaired_incidents_and_notifies_once`(완료 조건 3): `repairs_in_range` → `[17]`, 13분 동안 깨끗 → 이슈 17 닫힘, `notifier.fixed` 1번, `kv deploy_in_progress` 없음.
- [ ] `test_verify_fails_on_same_repaired_fingerprint`(스펙 5장 6단계).
- [ ] `test_rollback_code_only_when_schema_unchanged`(완료 조건 4): `git reset --hard prev`, `restore` 호출 없음, `bad_shas`에 `new`, 이슈에서 `merged`를 떼고 `rolled-back`과 `failed-<GitHub 라벨의 최대 N + 1>`(로컬 `failures`가 아니라 라벨에서 읽는다. Actions도 올리기 때문).
- [ ] `test_rollback_restores_db_when_schema_changed`: `failed-<sha>/`에 `planner.db`와 `-wal` 둘 다, `planner.db` 내용이 백업과 같음.
- [ ] `test_rollback_of_human_commit_opens_new_issue_with_range`(4.4 마지막 행).
- [ ] `test_rollback_verify_failure_gives_up_and_keeps_task_enabled`(5장 8단계): `needs-dahun`, 텔레그램 직접 알림 1번, 마지막 기록이 `Enable-`·`Start-`.
- [ ] `test_startup_with_deploy_in_progress_completes_rollback_and_enables_task`, `test_sleep_during_verify_restarts_window`(Review Focus 5).
- [ ] `test_dirty_tree_never_resets`, `test_ff_only_failure_is_not_rollback`(Review Focus 4): `git reset`·`git checkout` 기록 없음, 하루 한 번 알림.
- [ ] `test_prune_keeps_5_pre_deploy_and_3_failed`.
- [ ] `test_watcher_suppressed_during_deploy_and_3_minutes_after`.
- [ ] **Review + Commit** `feat(medic): updater with verify, deploy rollback and startup recovery`

---

### 티켓 08: 알림과 웹 확인

**목표:** 스펙 6장(결과 알림, 하루 상한, 넘친 알림 묶음)과 5.1(웹 장애의 해결).
**막는 티켓:** 07

**Files:**
- Create: `src/my_planner_medic/webverify.py`, `tests/medic/test_{notify,webverify}.py`
- Modify: `notify.py`(07의 프로토콜 옆에 구현), `watcher.py`(tick 끝에 `WebVerifier.tick`)

**Interfaces**
- Produces:
  - `notify.py`: `Notifier(cfg, store, http, clock)`(`NotifierLike` 구현). `fixed(pr_title: str, pr_url: str)`, `gave_up(fingerprint: str, rolled_back: bool, issue_url: str, *, direct: bool = False)`, `daily(text: str, key: str)`(하루 한 번 알림: 더러운 작업 폴더, API 꺼짐), `flush_spill()`. 문구는 스펙 6장 틀 그대로(`"🔧 자동으로 고쳤어요: {title}. {url}"`, `"⚠️ 자동으로 못 고쳤어요: {fp}. 지금은 {이전 버전으로 돌려 둠|그대로}. {url}"`). 보내는 길: `POST {api_base}/internal/notify`, 실패하거나 `direct`면 `https://api.telegram.org/bot<token>/sendMessage`(`chat_id=OWNER_TELEGRAM_ID`). 오늘(논리적 날짜) 보낸 수가 5면 `notices`에 쌓고, `flush_spill`이 다음 아침 회차 시각(`schedule.next_run`이 아침인 때) 이후 첫 tick에 `"자동 복구 알림 {n}개: …"` 한 줄 묶음으로 보낸다.
  - `webverify.py`: `WebVerifier(cfg, store, gh, notifier, clock)`. `tick()`: `merged` 상태의 `app`/`dashboard`/`vercel` 장애마다 스펙 5.1 1~4단계. Vercel 상태 컨텍스트 접두 `Vercel`.

- [ ] 스펙 6장 "다음 아침 브리핑 앞에 한 줄 묶음"을 "계획의 결정" 1대로 고친다(구현과 스펙을 이 티켓에서 함께). `fixed`의 제목·링크는 `gh.pr_for_issue(n)`에서.
- [ ] `test_fixed_goes_through_be_once`(`FakeHttp`에 `/internal/notify` 요청 1개, 본문 `kind: "recovery"`).
- [ ] `test_be_down_falls_back_to_telegram`, `test_direct_skips_be`.
- [ ] `test_sixth_notice_spills_and_flushes_after_morning_run`: 월 5개 보냄, 6번째 → 쌓임, 화 09:00 이후 첫 `flush_spill` → 묶음 1개.
- [ ] `test_daily_key_once_per_logical_date`(03:59와 04:01은 다른 날).
- [ ] `test_web_incident_resolves_after_vercel_success_and_quiet_hour`(완료 조건 7), `test_vercel_fingerprint_resolves_on_success_only`, `test_recurrence_during_web_verify_counts_failure`, `test_no_vercel_success_in_3h_counts_failure`.
- [ ] **Review + Commit** `feat(medic): result notices with daily cap, web fix verification`

---

### 티켓 09: medic 실행과 작업 등록 (`medic_boot.py`, 작업 XML, README)

**목표:** `my-planner-medic` 작업이 medic을 띄우고, medic 자신의 갱신과 되돌림(스펙 5장 "medic 자신의 갱신")을 한다.
**막는 티켓:** 08

**Files:**
- Create: `src/my_planner_medic/__main__.py`(`python -m my_planner_medic` → `main()`), `src/my_planner_medic/main.py`, `scripts/medic_boot.py`, `scripts/task_my-planner-medic.xml.tmpl`, `tests/medic/test_main.py`, `tests/medic/test_boot.py`
- Modify: `scripts/register_task.ps1`(`-Medic` 기본 켬, `-NoMedic` 끔), `scripts/check_tasks.ps1`(medic 작업 검사 줄, `-NoMedic`), `README.md`("자동 복구" 절: 시크릿 4개·`.env` 1개 넣기, `AUTO_REPAIR=off`로 끄기, `failed-<sha>/`에서 손으로 되살리기, PAT 만료), `.env.example`(`MEDIC_GITHUB_TOKEN=`), `.gitignore`(`state/medic.db`는 이미 `state/`로 덮임, 확인만)

**Interfaces**
- Consumes: `Watcher`, `Updater`, `Notifier`, `WebVerifier`, `load_config`.
- Produces:
  - `main.py`: `run(cfg, *, clock, sleep, stop: Callable[[], bool]) -> int`: 시작 시 `updater.recover_on_start()`, 그다음 루프(`watch_interval_s`마다 `watcher.tick`, `deploy_interval_s`마다 `updater.tick`). `cfg.enabled == False`면 하트비트만. 단일 실행 잠금 `state/medic.lock`(`msvcrt.locking`, Linux 시험은 `fcntl`). 배포 성공에 `src/my_planner_medic/`이 들어 있으면 `run`이 `3`을 돌려 끝난다(작업이 다시 띄운다).
  - `scripts/medic_boot.py`(표준 라이브러리 30줄 안팎): `state/medic-crashes.json`에 최근 시작 시각을 적고, `<root>\.venv\Scripts\python.exe -m my_planner_medic`을 환경 변수 `PYTHONPATH=<root>\src`로 자식 실행(editable 설치가 깨져도 돈다). 자식이 `3`(자기 갱신)으로 끝나면 바로 다시 띄운다. 다른 코드면 boot도 그 코드로 끝나고 작업의 5분 감시 트리거가 다시 띄운다. 자식이 60초 안에 죽은 것이 연속 3번이면 `state/medic-last-good.json`의 `sha`로 `git checkout <sha> -- src/my_planner_medic`, 그 배포의 `new_sha`를 `medic.db`의 `bad_shas`에 넣는다(`sqlite3`로 직접). 작업 폴더 깨끗함 검사에서 `src/my_planner_medic/` 차이를 빼는 표시 `kv["medic_pinned"] = sha`도 쓴다(07의 깨끗함 검사가 읽고, 다음 배포 전 `git checkout HEAD -- src/my_planner_medic`).
  - 작업 XML: `my-planner`와 같은 사용자, 로그온 + 5분 감시 트리거, `pythonw.exe scripts\medic_boot.py`, 시간 제한 없음, `IgnoreNew`.

- [ ] `test_run_calls_recover_first_then_ticks_on_intervals`(가짜 시계 0초 시작, `0 ≤ t < 600`초 → watcher t=0,120,240,360,480 5번, updater t=0,300 2번).
- [ ] `test_run_exits_3_after_medic_self_update`.
- [ ] `test_disabled_only_heartbeats`.
- [ ] `test_boot_reverts_medic_after_three_fast_crashes`(임시 git 저장소, 깨진 `my_planner_medic`) → `git checkout` 실행, `bad_shas`에 기록, `medic_pinned` 기록.
- [ ] `test_updater_ignores_pinned_medic_diff_and_cleans_before_merge`(07 시험 파일에 추가).
- [ ] 노트북(Remote Control 세션): `powershell -ExecutionPolicy Bypass -File scripts\register_task.ps1` → `check_tasks.ps1` 출력에 `my-planner-medic OK` 줄.
- [ ] **Review + Commit** `feat(medic): boot runner, scheduled task, README`

---

### 티켓 10: Actions 수리 — `repair`, `watch`, `signal`

**목표:** 스펙 3.5(Actions 쪽), 4.2, 4.3, 4.4의 Actions 쪽. 판단은 `.github/scripts/*.py`, YAML은 얇게.
**막는 티켓:** 01, 06(라벨·제목 형식), 00(S1·S4·S6)

**Files:**
- Create: `.github/workflows/{repair,watch,signal}.yml`(`watch` = 60분 cron 하나에 하트비트 확인 + sweep, `signal` = Vercel `status`와 `ci` 실패 `workflow_run`. 스펙의 `repair-sweep`·`heartbeat`·`vercel-failure` 셋을 Actions 예산 때문에 둘로 묶는다), `.github/repair-prompt.md`, `.github/scripts/{gh,repair_gate,repair_merge,sweep,heartbeat_check,signal_issue,telegram}.py`, `tests/workflows/test_{repair_gate,repair_merge,sweep,heartbeat_check,signal_issue}.py`
- Modify: `pyproject.toml`(`[tool.pytest.ini_options] pythonpath`에 `.github/scripts`), `ci.yml`(ruff 경로에 `.github/scripts`, actionlint 단계), 스펙("계획의 결정" 중 아직 안 옮긴 것과 워크플로 이름)

**Interfaces**
- Produces:
  - `gh.py`: `Api(token, repo, http=None)`(티켓 06 `Http`와 같은 모양을 `.github/scripts` 안에 따로 둔다. `src/`를 가져오지 않는다).
  - `repair_gate.py`: `gate(api, issue: int, *, now, auto_repair: str, max_failures: int, max_merges: int) -> Literal["go","stop_off","gave_up"]`. `gave_up`이면 `needs-dahun` 달고 `telegram.send("⚠️ 자동으로 못 고쳤어요: …")`. `go`면 `repairing` 단다. 실패 수는 `failed-N` 라벨의 가장 큰 N. 오늘 머지 수는 `auto-repair` 라벨 PR 중 `merged_at`이 Asia/Seoul 오늘.
  - `repair_merge.py`: `merge(api, pr: int, issue: int, *, wait_s=1800) -> Literal["merged","ci_failed","timeout"]`: PR 머리 커밋의 `ci` 실행이 끝날 때까지 기다리고 `success`면 `PUT /pulls/{pr}/merge`(`merge_method=squash`, `commit_message="Repairs #<issue>"`), 이슈 `repairing` → `merged`.
  - `sweep.py`: `sweep(api, *, now) -> list[Action]`(스펙 4.3 `repair-sweep` 규칙: 다시 부르기, 죽은 시도 정리, 머지만 다시). `Action = tuple[Literal["dispatch","merge_only","abandon"], int]`.
  - `heartbeat_check.py`: `check(api, *, now, pat_expires: str | None) -> list[str]`(보낼 텔레그램 글. 스펙 3.5 조건과 `stale-YYYY-MM-DD` 라벨, PAT 만료 30일 전부터 하루 한 번).
  - `signal_issue.py`: `from_status(event) -> str | None`(지문 `vercel:<context>`), `from_workflow_run(event) -> str | None`(`ci:main`), `ensure_issue(api, fp, part)`(열린 같은 지문 있으면 댓글).
  - `watch.yml`: `schedule: cron '7 * * * *'`(60분), 단계 `heartbeat_check.py` → `sweep.py`. `signal.yml`: `on: status`, `workflow_run: workflows [ci], types [completed]`(브랜치 `main`, `failure`만).
  - `repair.yml`: `on: issues: types [labeled]`(조건 `incident|rolled-back|recurred`) + `workflow_dispatch: inputs: issue, mode(full|merge_only)`. 작업 `gate` → `fix`(`anthropics/claude-code-action@v1`, `claude_code_oauth_token: ${{ secrets.CLAUDE_CODE_OAUTH_TOKEN }}`, 프롬프트 `.github/repair-prompt.md` + 이슈 번호, `claude_args: --max-turns 60`) → `merge`(`concurrency: repair-merge`, `repair_merge.py`, 실패 시 `fix`를 한 번 더 부르는 `workflow_dispatch`가 아니라 같은 실행 안에서 두 번째 `fix` 단계). 이슈 단위 `concurrency: repair-${{ github.event.issue.number || inputs.issue }}`, `cancel-in-progress: false`. 쓰기 토큰은 `secrets.REPAIR_PAT`.
  - `repair-prompt.md`: 스펙 4.3 Claude 단계 1~5 그대로 + "웹 빌드는 `NEXT_PUBLIC_CONNECT_SRC=https://*.example.ts.net npm run build`" + "PR 본문 첫 줄 `Repairs #<이슈>`", "브랜치 `auto-repair/<이슈>-<실패 수 + 1>`", "`.claude/agents/code-reviewer.md`로 리뷰", "머지하지 않는다(다음 단계가 한다)".

- [ ] `test_gate_off`, `test_gate_failures_at_limit_gives_up_and_notifies`, `test_gate_merges_today_at_limit`(Asia/Seoul 00:30과 전날 23:30 PR 구분), `test_gate_go_adds_repairing`.
- [ ] `test_merge_waits_for_ci_then_squashes_with_repairs_body`, `test_merge_ci_failure_returns_ci_failed`, `test_merge_does_not_use_required_checks`(요청 기록에 `/check-suites` 없음, `/actions/runs` 있음).
- [ ] `test_sweep_skips_merged_and_needs_dahun`, `test_sweep_abandons_dead_repairing_without_green_pr`, `test_sweep_merge_only_for_dead_repairing_with_green_pr`.
- [ ] `test_heartbeat_alert_only_after_next_run_passed`, `test_heartbeat_once_per_day`, `test_pat_expiry_reminder_30_days`.
- [ ] `test_status_event_to_fingerprint`(컨텍스트 `Vercel – my-planner-app`), `test_workflow_run_failure_on_main_to_ci_main`, `test_existing_open_issue_gets_comment`.
- [ ] `python -m pytest tests/workflows -q` → `0 failed`. actionlint는 공식 다운로드 스크립트(`bash <(curl -sSL https://raw.githubusercontent.com/rhysd/actionlint/v1.7.7/scripts/download-actionlint.bash) 1.7.7`) 뒤 `./actionlint` → 오류 없음.
- [ ] 스펙에 남은 "계획의 결정"과 워크플로 이름 옮기기.
- [ ] **Review + Commit** `feat(actions): auto repair, sweep, heartbeat and signal workflows`

---

### 티켓 11: 노트북 수용 확인 (스펙 12장)

**목표:** 스펙 완료 조건 1~8을 실제 노트북과 저장소에서 확인한다. 결과를 `docs/acceptance/2026-10-sp6.md`에 적는다.
**막는 티켓:** 02~10 모두. Dahun이 8장 비밀값(저장소 시크릿 4개, 변수, 노트북 `.env` 1개)을 넣은 뒤.
**라벨:** `needs-dahun`(시크릿 넣기, 노트북 끄기 확인)

- [ ] 스펙 12장 표의 1~8을 차례로. 조건 1·4·7의 개발용 탐침은 이 티켓의 PR에서 넣는다. BE 탐침은 `.env`의 `MEDIC_PROBE=1`, `MEDIC_PROBE_HEALTH=1`(BE가 시작 때 읽으므로 작업 프로세스에 들어간다, `Settings`에 선택 필드로 더함), 앱 탐침은 Vercel 미리보기 환경 변수 `NEXT_PUBLIC_MEDIC_PROBE=1`. 탐침은 확인이 끝나면 같은 수리 흐름 또는 사람 PR로 지운다.
- [ ] 결과 표(조건, 날짜, 걸린 시간, 이슈·PR 링크, 통과 여부).
- [ ] **Commit** `docs(acceptance): SP6 auto recovery results`

---

## 계획의 결정 (스펙 빈 곳)

1은 티켓 08이, 나머지는 티켓 10이 스펙에 옮긴다.

1. 넘친 알림 묶음은 BE 아침 브리핑에 붙이지 않고, medic이 다음 아침 회차 시각 이후 첫 tick에 `/internal/notify`로 한 줄 묶음을 따로 보낸다(BE를 바꾸지 않으려고). 스펙 6장 "다음 아침 브리핑 앞에 한 줄 묶음"을 이렇게 고친다.
2. `/internal/notify`는 `Dispatcher.send_notice` → 기존 `Delivery.deliver_notice`(D8 고정 안내 경로)를 쓴다.
3. `ClientErrorBody`의 필드 길이·정규식(티켓 02)은 계획이 정했다.
4. CI 실패 뒤 같은 시도 안 두 번째 Claude 단계는 같은 실행의 두 번째 `fix` 단계다(새 `workflow_dispatch`가 아니다).
5. medic의 "오늘"은 논리적 날짜(04:00 경계), Actions의 "오늘"은 Asia/Seoul 달력 날짜다.
6. `actionlint`를 `ci.yml`에 더한다.
7. `POST /client-errors` 검증 실패는 스펙대로 `422`다(다른 본문 검증의 `400`과 다름).
8. 정상 지연 억제에 `plan_open`·`proactive_cap`을 더하고, 행 없는 지연은 `late_run:tick_stalled`로 잡는다.
9. 워크플로는 `repair`, `watch`(60분), `signal` 셋이다. CI의 Windows 검사는 main 푸시와 수리 PR에서만 돈다(Actions 예산).
10. 웹만 바뀐 `main` 전진에서도 `Repairs #N` 장애를 `merged`로 바꾼다. Actions가 연 `vercel:`·`ci:main` 이슈는 감시자가 가져오고, `ci:main`은 `main` CI 초록에서 닫는다.
