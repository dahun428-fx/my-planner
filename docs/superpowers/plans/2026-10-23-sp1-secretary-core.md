# SP1 비서 코어 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 텔레그램으로 먼저 말을 걸고, 사용자와 할 일을 함께 정리하는 단일 사용자 비서(하네스 + 루프)를 Windows 노트북에서 상시 실행되게 만든다.

**Architecture:** 상시 실행 Python 프로세스 하나(asyncio)가 텔레그램 롱폴링, 1분 tick 루프, 직렬 디스패처를 돌린다. 판단은 Claude Agent SDK 세션(두뇌)이 하고, 두뇌는 in-process MCP 서버 `planner`의 도구로만 데이터를 바꾼다. 원본 데이터는 SQLite(`state/planner.db`)와 md(`data/`)에 있고, 순수 함수(schedule, catchup, conversations, context, redact)에 규칙을 모아 가짜 시계로 테스트한다.

**Tech Stack:** Python 3.12, `python-telegram-bot` (v21 이상, 비동기), `claude-agent-sdk`, `pydantic` v2, `pydantic-settings`, 표준 `sqlite3`, `zoneinfo`, `pytest`, `pytest-asyncio`. Windows: `msvcrt`, `ctypes`(SetThreadExecutionState), PowerShell, 작업 스케줄러.

**Spec:** [`docs/superpowers/specs/2026-10-23-sp1-secretary-core-design.md`](../specs/2026-10-23-sp1-secretary-core-design.md) (상위: [마스터 설계](../specs/2026-10-23-my-planner-master-design.md), 용어: [`docs/glossary.md`](../../glossary.md))

## Global Constraints

- Python 3.12, 저장소 루트의 `.venv`. 배포판은 Task 0의 S0 결과로 정한다(Store판 또는 python.org판).
- 패키지 이름 `my_planner`, 소스 루트 `src/my_planner/`, 실행 `python -m my_planner`.
- 시간대 `Asia/Seoul`, 저장은 UTC ISO 8601 문자열(`2026-10-23T05:30:00+00:00`), 날짜는 논리적 날짜 `YYYY-MM-DD`, 하루 경계 04:00.
- 주기 `period` 형식: 일 `2026-10-23`, 주 `2026-W43`(ISO), 월 `2026-10`, 분기 `2026-Q4`, 년 `2026`.
- 영역 6개 고정: `career`, `finance`, `health`, `relationships`, `learning`, `quality_of_life`.
- 회차 기본 시각: 평일 `morning_brief` 09:00, `evening_checkin` 17:30 / 주말(토·일) 10:00, 18:00 / `review(week)` 일요일 18:00.
- 루프별 한계: `morning_brief` 당일 12:00, `evening_checkin` 다음 날 04:00, `review(week)` +3일. 공백 ≥ 24시간이면 R1.
- 비서가 먼저 보내는 메시지 하루 최대 3회. 하루 두뇌 호출 상한 60회. 호출당 `max_turns=10`.
- 우선순위는 주기당 최대 3개, `open` 할 일만.
- 초안(`draft`) 만료 3일. 계획 모드 유휴 만료 2시간. `chat` 대화 이어가기 30분.
- 두뇌 실행 설정은 스펙 5.3의 `ClaudeAgentOptions` 블록 그대로(Task 0에서 바뀌면 스펙을 먼저 고친다).
- 사용자에게 보이는 문구에 "놓쳤어요", "밀렸어요", "늦었지만", "실패"를 쓰지 않는다.
- 로그(`state/logs/my-planner.jsonl`)에 메시지 본문과 도구 인자를 남기지 않는다.
- `data/`, `state/`, `.env`는 `.gitignore`. 백업은 로컬 디스크만.
- 모든 사용자 노출 문구는 한국어 존댓말.

## Review Focus

1. **텍스트가 아닌 메시지**(사진, 스티커, 음성, 편집된 메시지)가 오면 죽지 않고 "지금은 글로만 이야기할 수 있어요."로 답한다. → Task 15 `test_non_text_message_gets_polite_reply`, `test_edited_message_ignored`.
2. **오래된 버튼 누름**: 이미 만료·확정·내려놓은 초안의 버튼, 다른 날 체크인의 컨디션 버튼을 누르면 상태를 바꾸지 않거나(초안) 원래 날짜에 기록하고(컨디션), 짧게 안내한다. → Task 15 `test_stale_draft_button`, `test_condition_button_records_original_date`.
3. **아주 긴 입력·출력**: 4096자를 넘는 두뇌 답변은 문단 경계로 나눠 순서대로 보내고, 사용자 입력이 8000자를 넘으면 앞 8000자만 두뇌에 넘기고 그렇게 했다고 알린다. → Task 15 `test_split_long_reply`, Task 14 `test_truncate_huge_input`.
4. **시스템 시각이 뒤로 가거나 크게 앞서는 경우**(수동 변경, 배터리 방전 후 RTC 초기화): 공백을 0으로 보고 경고 로그, 회차를 한꺼번에 쏟아내지 않는다. → Task 10 `test_clock_went_backwards`, `test_clock_jumped_far_ahead_is_capped_at_7_days`.
5. **같은 메시지를 빠르게 여러 번 보냄**(연타, 네트워크 재전송): `update_id` 중복은 무시하고, 서로 다른 메시지 여러 개는 직렬 큐에서 하나의 두뇌 호출로 이어 붙인다. → Task 14 `test_queued_messages_coalesce`, Task 15 `test_duplicate_update_id_ignored`.

---

## File Structure

```
pyproject.toml                       # 패키지, 의존성, pytest 설정
config.toml                          # 개인값 없는 기본 설정 (Git 포함)
.env.example                         # TELEGRAM_BOT_TOKEN=, OWNER_TELEGRAM_ID=
.gitignore                           # .venv/ data/ state/ .env
README.md                            # 설치, 실행, 안내 문서 (Task 18)
docs/spikes/2026-10-sp1.md           # Task 0 결과
docs/acceptance/sp1-checklist.md     # Task 18
scripts/register_task.ps1            # 작업 스케줄러 등록 (Task 17)
scripts/task_my-planner.xml.tmpl     # 상시 작업 XML 템플릿
scripts/task_my-planner-wake.xml.tmpl
scripts/check_tasks.ps1              # 등록 결과 점검
src/my_planner/
  __main__.py                        # app.main() 호출
  app.py                             # 조립, 시작 순서, 종료 (Task 16)
  config.py                          # Settings (Task 1)
  clock.py                           # Clock, 논리적 날짜, period (Task 2)
  logging_setup.py                   # JSON 로그, pythonw 대응 (Task 16)
  domain.py                          # 공용 타입: Area, Cadence, TaskStatus, RunStatus, SkipReason, ToolEvent, RunContext (Task 2)
  platform/windows.py                # 잠금, 절전 방지 (Task 16)
  store/db.py                        # 연결, 마이그레이션, 무결성 (Task 3)
  store/migrations/001_init.sql      # 전체 스키마 (Task 3)
  store/repos/tasks.py               # 할 일, 영역, 이벤트, 우선순위 (Task 4)
  store/repos/state.py               # app_state, usage_state, telegram_updates (Task 5)
  store/repos/runs.py                # runs (Task 5)
  store/repos/conversations.py       # conversations (Task 5)
  store/repos/conditions.py          # conditions (Task 5)
  store/transcripts.py               # 원문 기록 md (Task 6)
  store/exports.py                   # tasks.md (Task 6)
  store/backup.py                    # SQLite 백업 (Task 6)
  harness/redact.py                  # 가리기 (Task 6)
  tools/core.py                      # 도구 함수 12개 (Task 7)
  tools/confirmations.py             # ToolEvent → 확인 문구 (Task 7)
  tools/mcp_adapter.py               # SDK MCP 서버 `planner` (Task 8)
  loop/schedule.py                   # 예정 시각 계산 (Task 9)
  loop/catchup.py                    # 따라잡기 결정 (Task 10)
  harness/conversations.py           # 대화 규칙 (Task 11)
  harness/context.py                 # 앞머리 컨텍스트 (Task 12)
  harness/prompts/*.md               # system, morning_brief, evening_checkin, review_week, return, plan (Task 12)
  harness/brain.py                   # Brain, BrainResult, ClaudeBrain, FakeBrain (Task 13)
  harness/dispatcher.py              # 직렬 큐, 회차 실행 2단계 (Task 14)
  bot/telegram_io.py                 # 수신 필터, 전송, 분할, 버튼 (Task 15)
  bot/commands.py                    # /today /week /pause /unpause /plan /done /help (Task 15)
  loop/runner.py                     # tick, 하트비트, 일일 작업 (Task 16)
tests/                               # 모듈별 test_*.py, tests/integration/
```

---

### Task 0: 착수 전 검증 (스파이크 S0~S5)

노트북에서 사람이(또는 원격 세션이) 직접 수행한다. 코드는 `spikes/` 폴더에 두고 커밋하지 않는다. 결과만 문서로 남긴다.

**Files:**
- Create: `docs/spikes/2026-10-sp1.md`

- [ ] **Step 1: S0** Store판 Python에서 `python -c "import sqlite3;c=sqlite3.connect(':memory:');c.enable_load_extension(True);print('ok')"`와 `pip install sqlite-vec` 후 `sqlite_vec.load(c)` 실행. venv를 `E:\my-planner\.venv`에 만들고 `pythonw.exe` 경로가 실제 파일인지 확인. 하나라도 안 되면 python.org 3.12를 설치해 같은 확인을 반복한다.
- [ ] **Step 2: S1** `spikes/s1_sdk.py`: 스펙 5.3 설정으로 `query("안녕이라고만 답해")` 한 번 호출, 결과를 파일에 기록. 작업 스케줄러에 임시 작업("로그온할 때", `pythonw.exe spikes\s1_sdk.py`)으로 등록해 로그오프/로그온 후 결과 파일과 콘솔 창 여부 확인. `claude`가 PATH에 없을 때도 되는지(SDK 번들 CLI 또는 `cli_path`) 확인. 일부러 로그아웃(`claude logout`) 상태에서 호출해 나오는 예외 타입과 메시지를 기록(→ `auth_error` 판별 근거).
- [ ] **Step 3: S2** in-process MCP 서버에 더미 도구 12개를 등록하고 "사용 가능한 도구 이름을 전부 나열해"와 "Read 도구로 C:\Windows\win.ini를 읽어" 두 프롬프트 실행. 기대: 나열에 `mcp__planner__*`만, Read 시도는 불가. 12개 각각 호출되는지 확인.
- [ ] **Step 4: S3** 사용자 `~/.claude/CLAUDE.md`에 "모든 답 끝에 🍌를 붙여라"를 임시로 넣고 호출해 🍌가 없는지 확인(확인 후 원복). claude.ai 커넥터 도구 이름과 auto memory 내용이 나타나지 않는지 확인. 동작한 `claude-agent-sdk` 버전을 기록.
- [ ] **Step 5: S4** `powercfg /a` 출력 기록. 깨우기 작업을 3분 뒤로 등록하고 AC/배터리/덮개 닫힘 각각에서 절전 → 깨어나는지 확인.
- [ ] **Step 6: S5** python-telegram-bot 롱폴링 스크립트를 돌린 채 10분 절전 → 복귀 후 메시지가 들어오는지 확인.
- [ ] **Step 7: 결과 기록**: 각 S마다 성공/실패, 명령, 출력 요약, 정해진 값(Python 경로, SDK 최소 버전, CLI 경로 방식, auth 오류 판별 규칙)을 `docs/spikes/2026-10-sp1.md`에 쓴다. 실패한 항목이 있으면 스펙의 해당 절을 고치고 이 계획의 Global Constraints를 갱신한 뒤 Task 1로 간다.
- [ ] **Step 8: Commit** `git add docs/spikes/2026-10-sp1.md && git commit -m "docs: record SP1 spike results"`

---

### Task 1: 프로젝트 골격과 설정

**Files:**
- Create: `pyproject.toml`, `config.toml`, `.env.example`, `.gitignore`, `src/my_planner/__init__.py`, `src/my_planner/__main__.py`, `src/my_planner/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `Settings` (pydantic-settings). 필드: `telegram_bot_token: SecretStr`, `owner_telegram_id: int`, `timezone: str = "Asia/Seoul"`, `day_boundary: time = 04:00`, `schedule: ScheduleConfig`(루프별 평일/주말 시각, `review_week` 요일·시각), `limits: LimitsConfig`(`daily_brain_calls=60`, `max_turns=10`, `daily_proactive_messages=3`, `chat_resume_minutes=30`, `plan_idle_hours=2`, `draft_ttl_days=3`, `stale_message_hours=6`, `input_max_chars=8000`), `paths: PathsConfig`(`root`, `data_dir`, `state_dir`), `retention: RetentionConfig`(`log_days=30`, `backup_count=14`). `load_settings(root: Path) -> Settings`는 `root/config.toml`과 `root/.env`를 읽는다.

- [ ] **Step 1: 실패하는 테스트**
  - `test_defaults_match_spec`: 빈 `config.toml` + `.env`로 로드 → 평일 09:00/17:30, 주말 10:00/18:00, 일요일 18:00, 한계값들이 Global Constraints 값과 같다.
  - `test_missing_owner_id_raises`: `.env`에 `OWNER_TELEGRAM_ID` 없으면 `ValidationError`.
  - `test_token_not_in_repr`: `repr(settings)`에 토큰 문자열이 없다.
  - `test_invalid_time_rejected`: `morning_brief.weekday = "25:00"` → `ValidationError`.
- [ ] **Step 2: 실행해서 실패 확인** `pytest tests/test_config.py -v` → FAIL (모듈 없음)
- [ ] **Step 3: 구현** `pyproject.toml`(setuptools, `src` 레이아웃, 의존성은 버전 하한만: `python-telegram-bot>=21`, `claude-agent-sdk>=<S3에서 정한 버전>`, `pydantic>=2`, `pydantic-settings>=2`; dev: `pytest`, `pytest-asyncio`; `asyncio_mode = "auto"`), `.gitignore`, `.env.example`, 기본값이 든 `config.toml`, `config.py`.
- [ ] **Step 4: 통과 확인** `pip install -e .[dev] && pytest tests/test_config.py -v` → PASS
- [ ] **Step 5: Commit** `git commit -m "feat: project skeleton and settings"`

---

### Task 2: 시계, 논리적 날짜, 공용 타입

**Files:**
- Create: `src/my_planner/clock.py`, `src/my_planner/domain.py`
- Test: `tests/test_clock.py`

**Interfaces:**
- Produces:
  - `class Clock(Protocol): def now(self) -> datetime` (tz-aware UTC). `SystemClock`, `FakeClock(start: datetime)` with `advance(timedelta)`, `set(datetime)`.
  - `local(dt: datetime, tz: ZoneInfo) -> datetime`
  - `logical_date(dt: datetime, tz: ZoneInfo, boundary: time) -> date`
  - `period_of(cadence: Cadence, d: date) -> str` (Global Constraints 형식)
  - `is_weekend(d: date) -> bool` (토, 일)
  - `domain.py`: `Area`, `Cadence`(`day|week|month|quarter|year`), `TaskStatus`(`draft|open|done|dropped`), `RunStatus`(`pending|running|done|failed|skipped|interrupted`), `SkipReason`(`late|merged_into_return|paused|auth|rate_limit|daily_cap`), `LoopKey`(`morning_brief|evening_checkin|review_week|return`), `ConversationKind`(`run|chat|plan`), `@dataclass ToolEvent(kind: str, task_id: int|None, data: dict)`, `@dataclass RunContext(conversation_id: int, run_id: int|None, events: list[ToolEvent])`.

- [ ] **Step 1: 실패하는 테스트**
  - `test_logical_date_before_boundary`: KST 2026-10-24 03:59 → `2026-10-23`.
  - `test_logical_date_at_boundary`: KST 2026-10-24 04:00 → `2026-10-24`.
  - `test_period_formats`: 2026-10-23 → day `2026-10-23`, week `2026-W43`, month `2026-10`, quarter `2026-Q4`, year `2026`; 2027-01-01 → week `2026-W53`.
  - `test_is_weekend`: 2026-10-24(토) True, 2026-10-26(월) False.
  - `test_fake_clock_advance`.
- [ ] **Step 2: 실패 확인** `pytest tests/test_clock.py -v`
- [ ] **Step 3: 구현** (`isocalendar()`로 ISO 주)
- [ ] **Step 4: 통과 확인**
- [ ] **Step 5: Commit** `git commit -m "feat: clock, logical date, domain types"`

---

### Task 3: DB 연결, 마이그레이션, 스키마

**Files:**
- Create: `src/my_planner/store/__init__.py`, `store/db.py`, `store/migrations/001_init.sql`
- Test: `tests/store/test_db.py`

**Interfaces:**
- Produces: `open_db(path: Path) -> sqlite3.Connection` (WAL, `foreign_keys=ON`, `row_factory=sqlite3.Row`), `migrate(conn) -> int` (적용 후 `user_version`), `integrity_ok(conn) -> bool`.
- 스키마(001): 스펙 5.5의 `tasks`, `task_areas`, `task_events`, `priorities`, `conditions` 그대로, 그리고:
  - `runs(id PK, loop TEXT, scheduled_for TEXT, status TEXT, skip_reason TEXT NULL, attempt INT DEFAULT 0, started_at, finished_at, outbound_text TEXT NULL, error TEXT NULL, conversation_id INT NULL, merged_run_ids TEXT DEFAULT '[]', created_at)`, UNIQUE `(loop, scheduled_for)`, CHECK status/skip_reason 값.
  - `conversations(id PK, kind TEXT, run_id INT NULL, session_id TEXT NULL, logical_date TEXT, opened_at, last_message_at, closed_at NULL)`.
  - `app_state(key TEXT PK, value TEXT)` — 키: `installed_at`, `last_seen_at`, `pause_until`, `last_auth_notice_date`, `last_backup_date`.
  - `usage_state(date TEXT PK, brain_calls INT, proactive_messages INT, limited_until TEXT NULL)`.
  - `telegram_updates(update_id INT PK, received_at TEXT)`.
  - `tool_events_log(id PK, run_id INT NULL, conversation_id INT, kind TEXT, at TEXT)` — 재실행 판정(5.4-3)용.

- [ ] **Step 1: 실패하는 테스트**
  - `test_migrate_fresh_db_sets_version_1`
  - `test_migrate_is_idempotent` (두 번 실행해도 1, 오류 없음)
  - `test_wal_and_foreign_keys_on`
  - `test_runs_unique_loop_scheduled_for` (같은 키 두 번 INSERT → `IntegrityError`)
  - `test_priority_rank_check` (rank 4 → `IntegrityError`)
  - `test_completed_at_only_when_done` (status `open` + completed_at → `IntegrityError`)
  - `test_task_area_check` (`area='sports'` → `IntegrityError`)
  - `test_integrity_ok_true_on_fresh_db`
- [ ] **Step 2: 실패 확인**
- [ ] **Step 3: 구현** 마이그레이션은 `migrations/NNN_*.sql`을 번호순으로, `user_version`보다 큰 것만 트랜잭션으로 적용.
- [ ] **Step 4: 통과 확인**
- [ ] **Step 5: Commit** `git commit -m "feat: sqlite schema and migrations"`

---

### Task 4: 할 일 저장소 (영역, 이벤트, 우선순위, 초안)

**Files:**
- Create: `src/my_planner/store/repos/__init__.py`, `store/repos/tasks.py`
- Test: `tests/store/test_tasks_repo.py`

**Interfaces:**
- Consumes: `open_db`, `migrate` (Task 3), `Clock`, 도메인 타입 (Task 2)
- Produces: `class TasksRepo(conn, clock)`:
  - `create(title, areas: list[Area], status: TaskStatus, planned_for: date|None, scheduled_at: datetime|None, parent_id: int|None, note: str|None) -> Task`
  - `get(id) -> Task|None`, `update(id, **fields) -> Task`, `set_status(id, status) -> Task`
  - `list(status: set[TaskStatus]|None, from_: date|None, to: date|None, area: Area|None, limit: int) -> list[Task]` (`deleted_at IS NULL`만)
  - `set_priorities(cadence, period, task_ids: list[int]) -> None`
  - `priorities(cadence, period) -> list[Task]`
  - `expire_drafts(older_than: timedelta) -> list[int]`
  - `Task` dataclass: 표의 열 + `areas: list[Area]`.
  - 모든 상태 변경은 같은 트랜잭션에서 `task_events`에 기록(kind: `proposed|confirmed|created|updated|completed|moved|dropped|reopened`).

- [ ] **Step 1: 실패하는 테스트**
  - `test_create_open_records_created_event`
  - `test_create_draft_records_proposed_event`
  - `test_create_requires_at_least_one_area` (`ValueError`)
  - `test_title_length_limits` (빈 문자열, 201자 → `ValueError`)
  - `test_complete_sets_completed_at_and_reopen_clears_it`
  - `test_drop_removes_from_priorities`
  - `test_set_priorities_replaces_whole_period`
  - `test_set_priorities_rejects_more_than_3` (`ValueError`)
  - `test_set_priorities_rejects_draft_and_done` (`ValueError`, open만)
  - `test_expire_drafts_after_3_days` (FakeClock: 2일 23시간 → 유지, 3일 → `dropped`, 이벤트 `dropped`)
  - `test_list_excludes_soft_deleted`
  - `test_parent_must_exist`
- [ ] **Step 2: 실패 확인**
- [ ] **Step 3: 구현**
- [ ] **Step 4: 통과 확인**
- [ ] **Step 5: Commit** `git commit -m "feat: tasks repository with events and priorities"`

---

### Task 5: 나머지 저장소 (runs, 대화, 컨디션, 상태)

**Files:**
- Create: `store/repos/runs.py`, `store/repos/conversations.py`, `store/repos/conditions.py`, `store/repos/state.py`
- Test: `tests/store/test_runs_repo.py`, `test_conversations_repo.py`, `test_conditions_repo.py`, `test_state_repo.py`

**Interfaces:**
- Produces:
  - `RunsRepo`: `ensure(loop: LoopKey, scheduled_for: datetime) -> Run` (없으면 `pending`으로 생성, 있으면 기존 반환), `mark_running(id)`, `save_outbound(id, text)`, `mark_done(id)`, `mark_failed(id, error)`, `mark_skipped(id, reason: SkipReason)`, `add_merged(id, merged_ids: list[int])`, `interrupt_running() -> list[int]`, `pending() -> list[Run]`, `between(start, end) -> list[Run]`, `has_tool_events(run_id) -> bool`.
  - `ConversationsRepo`: `open(kind, logical_date, run_id=None) -> Conversation`, `touch(id)`, `set_session(id, session_id)`, `close(id)`, `latest_open(kind) -> Conversation|None`, `open_run_conversations() -> list[Conversation]`.
  - `ConditionsRepo`: `upsert(date, score: int, note: str|None)`, `get(date) -> Condition|None`.
  - `StateRepo`: `get(key) -> str|None`, `set(key, value)`, `incr_usage(date, field: Literal["brain_calls","proactive_messages"]) -> int`, `usage(date) -> Usage`, `set_limited_until(date, dt)`, `seen_update(update_id) -> bool` (처음이면 기록하고 False, 이미 있으면 True), `prune_updates(older_than)`.

- [ ] **Step 1: 실패하는 테스트**
  - `test_ensure_is_idempotent`
  - `test_interrupt_running_marks_only_running`
  - `test_skip_requires_reason`
  - `test_condition_upsert_overwrites_same_date`
  - `test_condition_score_out_of_range` (0, 6 → `ValueError`)
  - `test_seen_update_dedupes`
  - `test_usage_counters_persist_across_connections` (DB 닫았다 다시 열어도 유지)
  - `test_latest_open_ignores_closed`
- [ ] **Step 2~4: 실패 확인 → 구현 → 통과 확인**
- [ ] **Step 5: Commit** `git commit -m "feat: runs, conversations, conditions, state repositories"`

---

### Task 6: 원문 기록, 가리기, 내보내기, 백업

**Files:**
- Create: `store/transcripts.py`, `store/exports.py`, `store/backup.py`, `harness/__init__.py`, `harness/redact.py`
- Test: `tests/store/test_transcripts.py`, `tests/store/test_exports.py`, `tests/store/test_backup.py`, `tests/harness/test_redact.py`

**Interfaces:**
- Produces:
  - `redact(text: str) -> tuple[str, bool]` (가린 결과, 가린 일이 있었는지). 치환 문자열 `[가림]`.
  - `TranscriptStore(data_dir, tz, boundary)`: `append(at: datetime, speaker: Literal["사용자","비서"], conversation_id: int, run_key: str|None, text: str, tools: list[str] = [])`, `read(from_: date, to: date) -> str` (최대 7일, 넘으면 `ValueError`).
  - `export_tasks(repo: TasksRepo, path: Path) -> None` (오늘, 이번 주, 열린 할 일, 이번 주 완료. 초안 제외).
  - `daily_backup(conn, backups_dir, today: date, keep: int) -> Path|None` (오늘 이미 있으면 None).

- [ ] **Step 1: 실패하는 테스트**
  - `test_redact_rrn`: `"제 번호는 900101-1234567"` → `[가림]` 포함, True.
  - `test_redact_account_number`: 10~14자리 숫자열(하이픈 허용) 가림.
  - `test_redact_password_context`: `"비번은 hunter2야"`, `"password: abc"`, `"PIN 1234"` → 값만 가림.
  - `test_redact_keeps_phone_and_dates`: `"010-1234-5678"`, `"2026-10-23"`, `"14:00"`은 그대로, False.
  - `test_transcript_path_uses_logical_date`: KST 01:00 메시지 → 전날 파일.
  - `test_transcript_header_format`: `### 09:00 비서 [3] (morning_brief)` 와 `> 도구: add_task`.
  - `test_transcript_append_only` (두 번 쓰면 두 블록).
  - `test_read_more_than_7_days_raises`.
  - `test_export_excludes_drafts`.
  - `test_backup_keeps_14` (15일 연속 → 파일 14개).
- [ ] **Step 2~4: 실패 확인 → 구현 → 통과 확인**
- [ ] **Step 5: Commit** `git commit -m "feat: transcripts, redaction, exports, backup"`

---

### Task 7: 도구 함수와 확인 문구

**Files:**
- Create: `src/my_planner/tools/__init__.py`, `tools/core.py`, `tools/confirmations.py`
- Test: `tests/tools/test_core.py`, `tests/tools/test_confirmations.py`

**Interfaces:**
- Consumes: `TasksRepo`, `ConditionsRepo`, `TranscriptStore`, `export_tasks`, `RunContext`, `ToolEvent`
- Produces: `class Tools(tasks, conditions, transcripts, export_path, clock, tz, boundary)`. 메서드 12개는 스펙 5.5 표의 이름·입력 그대로이며 각각 `(ctx: RunContext, **inputs) -> dict` (두뇌에 돌려줄 JSON 직렬화 가능한 결과). 변경 메서드는 `ctx.events`에 `ToolEvent`를 추가하고 `tasks.md`를 다시 만든다. 잘못된 입력은 예외 대신 `{"error": "<한국어 이유>"}`를 돌려준다(두뇌가 읽고 사용자에게 설명).
  - `ToolEvent.kind` 값: `task_added`, `tasks_proposed`, `tasks_confirmed`, `task_updated`, `task_moved`, `task_completed`, `task_reopened`, `task_dropped`, `priorities_set`.
- Produces: `render_confirmations(events: list[ToolEvent], today: date) -> str` (이벤트 없으면 `""`). 문구 고정:
  - `✓ 추가: {title}` (+ ` ({M/D} {HH:MM})` 일정, ` → {오늘|내일|M/D}` 날짜)
  - `✓ 옮김: {title} → {오늘|내일|M/D|날짜 없음}`
  - `✓ 완료: {title}` / `✓ 되돌림: {title}` / `✓ 내려놓음: {title}` / `✓ 바꿈: {title}`
  - `✓ 우선순위({오늘|이번 주|…}): 1. … 2. … 3. …`
  - `✓ 확정: {title}` (확정마다 한 줄)
  - `tasks_proposed`는 문구를 만들지 않는다(버튼이 붙는다, Task 15).

- [ ] **Step 1: 실패하는 테스트**
  - `test_add_task_emits_event_and_exports`
  - `test_add_task_bad_area_returns_error_dict`
  - `test_propose_tasks_creates_drafts`
  - `test_confirm_tasks_only_drafts` (open/done id는 무시하고 결과에 `skipped_ids`)
  - `test_set_priorities_four_returns_error`
  - `test_record_condition_defaults_to_logical_today`
  - `test_record_condition_explicit_date`
  - `test_read_transcript_range_limit_error`
  - `test_list_tasks_limit_capped_at_50`
  - `test_render_add_with_schedule`: 내일 14:00 치과 → `✓ 추가: 치과 (10/25 14:00)`
  - `test_render_move_to_tomorrow`: `✓ 옮김: 운동 → 내일`
  - `test_render_empty_events_is_empty_string`
  - `test_render_has_no_banned_words` (모든 이벤트 종류 문구에 "놓쳤", "밀렸", "늦었", "실패" 없음)
- [ ] **Step 2~4: 실패 확인 → 구현 → 통과 확인**
- [ ] **Step 5: Commit** `git commit -m "feat: planner tools and confirmation messages"`

---

### Task 8: MCP 어댑터

**Files:**
- Create: `tools/mcp_adapter.py`
- Test: `tests/tools/test_mcp_adapter.py`

**Interfaces:**
- Consumes: `Tools` (Task 7), `claude_agent_sdk.tool`, `create_sdk_mcp_server`
- Produces: `build_planner_server(tools: Tools, ctx_provider: Callable[[], RunContext]) -> McpSdkServerConfig` (서버 이름 `planner`, 버전 `1.0.0`). `TOOL_NAMES: list[str]` (12개, 스펙 순서). `allowed_tool_patterns() -> list[str]` = `["mcp__planner__*"]`. 각 도구의 입력 스키마는 스펙 5.5 입력 열을 따른다(선택 인자는 optional). 핸들러는 `ctx_provider()`로 현재 호출의 `RunContext`를 얻어 `Tools` 메서드를 부르고, 결과 dict를 SDK 형식 `{"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}]}`로 감싼다.

- [ ] **Step 1: 실패하는 테스트**
  - `test_server_exposes_exactly_12_tools_in_order`
  - `test_handler_routes_to_tools_and_records_event` (핸들러 함수를 직접 await, 실제 SDK 호출 없음)
  - `test_handler_wraps_error_dict_as_text`
- [ ] **Step 2~4: 실패 확인 → 구현 → 통과 확인**
- [ ] **Step 5: Commit** `git commit -m "feat: expose planner tools as in-process MCP server"`

---

### Task 9: 예정 시각 계산

**Files:**
- Create: `src/my_planner/loop/__init__.py`, `loop/schedule.py`
- Test: `tests/loop/test_schedule.py`

**Interfaces:**
- Consumes: `ScheduleConfig` (Task 1), `is_weekend`, `logical_date` (Task 2)
- Produces:
  - `@dataclass(frozen=True) Due(loop: LoopKey, scheduled_for: datetime)` (UTC)
  - `due_between(start: datetime, end: datetime, cfg: ScheduleConfig, tz) -> list[Due]` — `(start, end]` 구간, 시간순. `review_week`는 일요일 18:00.
  - `window_start(now, last_seen_at, installed_at) -> datetime` = `max(last_seen_at, installed_at, now - 7일)`
  - `limit_for(due: Due, cfg, tz, boundary) -> datetime` (루프별 한계)
  - `reply_window_end(due: Due, tz, boundary) -> datetime` (아침 당일 12:00, 저녁 다음 날 04:00, 회고 +24시간)

- [ ] **Step 1: 실패하는 테스트**
  - `test_weekday_times`: 2026-10-26(월) 하루 → 09:00, 17:30 KST.
  - `test_weekend_times`: 2026-10-24(토) → 10:00, 18:00.
  - `test_sunday_has_review_at_1800`: 2026-10-25 → morning 10:00, evening 18:00, review_week 18:00.
  - `test_half_open_interval`: start가 정확히 09:00이면 그 회차는 제외, end가 09:00이면 포함.
  - `test_window_start_capped_7_days`
  - `test_limits`: 아침 → 당일 12:00, 저녁(월 17:30) → 화 04:00, 회고 → +3일.
  - `test_reply_windows`.
- [ ] **Step 2~4: 실패 확인 → 구현 → 통과 확인**
- [ ] **Step 5: Commit** `git commit -m "feat: run schedule computation"`

---

### Task 10: 따라잡기 결정

**Files:**
- Create: `loop/catchup.py`
- Test: `tests/loop/test_catchup.py`

**Interfaces:**
- Consumes: `Due`, `limit_for` (Task 9)
- Produces:
  - `@dataclass Decision(execute: list[Due], primary: Due|None, merged: list[Due], skipped: list[tuple[Due, SkipReason]], create_return: bool, carry_review: Due|None)`
  - `decide(now, last_seen_at, pending: list[Due], *, paused_until: datetime|None, brain_calls_today: int, proactive_today: int, plan_open: bool, cfg, tz, boundary) -> Decision`
  - 규칙 순서는 스펙 5.4 표 R1~R5 그대로. 같은 tick의 실행 대상이 여럿이면 `primary` 하나와 `merged`로 나눈다(우선순위 `return > evening_checkin > morning_brief > review_week`). `proactive_today >= 3`이면 `execute`를 비우고 skipped 없이 다음 tick으로 넘긴다(다음 정규 연락에 합쳐짐). `plan_open`이면 한계 안의 회차는 그대로 대기(결정에 넣지 않음), 한계 밖은 `late`. 시계 역행(`now < last_seen_at`)이면 공백 0으로 본다.

- [ ] **Step 1: 실패하는 테스트** (표 기반 `pytest.mark.parametrize`, 스펙 8장 표 7행 전부 + 아래)
  - `test_spec_table_row_1` … `test_spec_table_row_7` (스펙 8장의 마지막 tick·깨어난 시각·기대 결과 그대로)
  - `test_paused_skips_with_reason`
  - `test_daily_cap_skips_with_reason` (brain_calls_today=60)
  - `test_fourth_proactive_message_waits`
  - `test_plan_open_defers_within_limit`
  - `test_plan_open_past_limit_is_late`
  - `test_clock_went_backwards` (Review Focus 4: 공백 0, R1 아님)
  - `test_clock_jumped_far_ahead_is_capped_at_7_days` (Review Focus 4: 30일 앞 → `return` 하나, pending은 최근 7일치만 들어온다는 전제의 입력으로 확인)
  - `test_r1_review_carried_when_within_3_days`
- [ ] **Step 2~4: 실패 확인 → 구현 → 통과 확인**
- [ ] **Step 5: Commit** `git commit -m "feat: catch-up decision rules"`

---

### Task 11: 대화 규칙

**Files:**
- Create: `harness/conversations.py`
- Test: `tests/harness/test_conversations.py`

**Interfaces:**
- Consumes: `ConversationsRepo`, `RunsRepo` (Task 5), `reply_window_end` (Task 9)
- Produces: `class ConversationRouter(convs, runs, clock, cfg, tz, boundary)`:
  - `for_run(run: Run) -> Conversation` (항상 새 `run` 대화)
  - `for_user_message(at: datetime) -> Conversation` (규칙 순서: 열린 `plan` 대화(2시간 이내) → 답장 창 안의 `run` 대화(가장 최근) → 30분 이내 `chat` → 새 `chat`)
  - `start_plan() -> Conversation` (열린 다른 `plan`은 닫음), `end_plan() -> bool`
  - `close_expired() -> None` (만료 대화 `closed_at` 기록)
  - `plan_open() -> bool`

- [ ] **Step 1: 실패하는 테스트**
  - `test_reply_to_evening_checkin_after_midnight_continues` (17:30 체크인, 00:10 답장 → 같은 대화)
  - `test_reply_after_window_opens_new_chat` (다음 날 04:01)
  - `test_reply_window_beats_30_minutes` (체크인 후 2시간, 그 사이 chat 없음 → run 대화)
  - `test_chat_resumes_within_30_minutes`, `test_chat_new_after_31_minutes`
  - `test_plan_takes_precedence_and_expires_after_2h`
  - `test_end_plan_without_open_returns_false`
- [ ] **Step 2~4: 실패 확인 → 구현 → 통과 확인**
- [ ] **Step 5: Commit** `git commit -m "feat: conversation routing rules"`

---

### Task 12: 앞머리 컨텍스트와 프롬프트

**Files:**
- Create: `harness/context.py`, `harness/prompts/system.md`, `morning_brief.md`, `evening_checkin.md`, `review_week.md`, `return.md`, `plan.md`
- Test: `tests/harness/test_context.py`, `tests/harness/test_prompts.py`

**Interfaces:**
- Consumes: `TasksRepo`, `ConditionsRepo`, `StateRepo`, 시계 함수
- Produces:
  - `build_preamble(*, now, tz, boundary, tasks: TasksRepo, conditions: ConditionsRepo, paused_until, merged: list[LoopKey], redacted: bool, stale_hours: float|None) -> str` — 스펙 5.3 "새 세션의 앞머리 컨텍스트" 항목 순서대로 섹션 머리글 `## 지금`, `## 우선순위`, `## 열린 할 일`, `## 오늘 일정`, `## 어제 컨디션`, `## 함께 처리할 회차`, `## 멈춤`, `## 알림`(가림, 오래된 메시지). 비어 있는 섹션은 생략(어제 컨디션은 "기록 없음").
  - `load_prompt(name: str) -> str` (`prompts/<name>.md`)
  - `system.md`는 스펙 6장 원칙 8개를 담는다. `plan.md`는 스펙 5.7 계획 모드 1~3을, `return.md`는 "다시 이어서 해 볼까요" + 오늘 할 것만.

- [ ] **Step 1: 실패하는 테스트**
  - `test_preamble_lists_at_most_30_open_tasks_in_order` (오늘 → 이번 주 → 나머지)
  - `test_preamble_excludes_drafts`
  - `test_preamble_yesterday_condition_missing` → "기록 없음"
  - `test_preamble_mentions_redaction_when_flagged`
  - `test_preamble_marks_stale_message` (stale_hours=7 → "약 7시간 전에 보낸 메시지")
  - `test_all_prompt_files_exist_and_nonempty`
  - `test_prompts_have_no_banned_words` (Global Constraints 금지어)
  - `test_system_prompt_contains_max_three_and_tools_rule` ("최대 3개", "도구" 문구 포함)
- [ ] **Step 2~4: 실패 확인 → 구현 → 통과 확인**
- [ ] **Step 5: Commit** `git commit -m "feat: session preamble and prompts"`

---

### Task 13: 두뇌 (Brain, ClaudeBrain, FakeBrain)

**Files:**
- Create: `harness/brain.py`, `tests/fakes.py` (`FakeBrain`)
- Test: `tests/harness/test_brain.py`

**Interfaces:**
- Consumes: `build_planner_server`, `allowed_tool_patterns` (Task 8), `load_prompt` (Task 12)
- Produces:
  - `Brain` 프로토콜 (스펙 4장 시그니처 그대로), `BrainStatus = Literal["ok","max_turns","auth_error","rate_limited","error"]`, `@dataclass BrainResult(text: str, session_id: str|None, turns: int, tool_events: list[ToolEvent], status: BrainStatus, error: str|None = None, resume_failed: bool = False)`.
  - `build_options(*, server, session_id: str|None, workdir: Path, max_turns: int, system_prompt: str, cli_path: str|None) -> ClaudeAgentOptions` — 스펙 5.3 블록과 같은 값.
  - `ClaudeBrain(server_factory, workdir, max_turns, cli_path)`: `run()`은 SDK `query()`의 메시지 스트림에서 마지막 텍스트, 세션 ID, 턴 수, `ResultMessage` 하위 유형을 모은다. 예외·결과를 `BrainStatus`로 바꾸는 규칙은 Task 0 S1 기록을 따른다(기록 전에는 `error`). resume 대상 세션이 없다는 오류면 `resume_failed=True`, `status="error"`.
  - `FakeBrain(script: list[FakeTurn])`: `FakeTurn(tool_calls: list[tuple[str, dict]], text: str, status="ok")`. `run()`은 `tool_calls`를 실제 `Tools` 메서드로 실행해 `run_ctx.events`를 채우고 `text`를 돌려준다. 호출된 프롬프트를 `prompts`에 기록.

- [ ] **Step 1: 실패하는 테스트**
  - `test_build_options_locks_down_tools`: `tools == []`, `allowed_tools == ["mcp__planner__*"]`, `permission_mode == "dontAsk"`, `strict_mcp_config is True`, `setting_sources == []`, env 두 키, `max_turns == 10`.
  - `test_build_options_resume_passthrough`
  - `test_fake_brain_executes_tool_calls_and_records_events`
  - `test_claude_brain_maps_max_turns_result` (SDK `query`를 몽키패치한 가짜 스트림 → `status="max_turns"`)
  - `test_claude_brain_maps_unknown_exception_to_error`
- [ ] **Step 2~4: 실패 확인 → 구현 → 통과 확인**
- [ ] **Step 5: Commit** `git commit -m "feat: brain protocol, Claude Agent SDK brain, fake brain"`

---

### Task 14: 디스패처 (직렬 큐, 회차 2단계 실행)

**Files:**
- Create: `harness/dispatcher.py`
- Test: `tests/harness/test_dispatcher.py`

**Interfaces:**
- Consumes: `Brain`, `ConversationRouter`, `build_preamble`, `load_prompt`, `redact`, `TranscriptStore`, `RunsRepo`, `StateRepo`, `render_confirmations`, `Tools`
- Produces:
  - `@dataclass Inbound(text: str, at: datetime, sent_at: datetime, telegram_message_id: int)`
  - `@dataclass Outbound(text: str, draft_task_ids: list[int], ask_condition_for: date|None)` — 버튼 정보는 봇이 그린다(Task 15).
  - `class Sender(Protocol): async def send(self, out: Outbound) -> None; async def typing(self) -> None`
  - `class Dispatcher(...)`: `async def submit_message(m: Inbound) -> None`, `async def submit_run(run: Run, merged: list[Run]) -> None`, `async def start() / stop(timeout=30)`. 내부 `asyncio.Queue` 하나, 작업자 하나.
  - 메시지 처리: 큐에서 꺼낼 때 이미 쌓인 다른 메시지를 모두 꺼내 `\n\n`로 이어 붙임(Review Focus 5) → 사용자 메시지가 회차보다 먼저(큐 우선순위) → 8000자 초과면 자르고 알림 플래그(Review Focus 3) → `redact` → 원문 기록(사용자) → 대화 결정 → 새 세션이면 preamble + 프롬프트 → `StateRepo.incr_usage("brain_calls")` 상한 확인 → `Brain.run` → 상태별 처리(스펙 5.3 표, 문구 고정) → resume 실패면 새 세션 + 원문 기록 최근 20개로 1회 재시도 → `Outbound` 조립(답 + 확인 문구, `tasks_proposed` 이벤트의 id는 `draft_task_ids`) → 전송 → 원문 기록(비서, 도구 이름 목록).
  - 회차 처리(스펙 5.4 재시도): `mark_running` → 두뇌 → `save_outbound` → 전송 → `mark_done`, `incr_usage("proactive_messages")`. 전송 실패 → `mark_failed`, 5분 뒤 전송만 1회 재시도(`asyncio` 타이머, `outbound_text` 사용). 두뇌 단계 실패 → `has_tool_events`가 False이고 한계 안이면 1회 재실행, 아니면 `failed`. `auth_error`/`rate_limited`는 `skipped(auth|rate_limit)`.
  - 저녁 체크인 회차의 `Outbound.ask_condition_for` = 그 회차의 논리적 날짜.
  - 두뇌 호출과 전송 동안 `keep_awake()` 컨텍스트(Task 16에서 주입, 테스트는 no-op).

- [ ] **Step 1: 실패하는 테스트** (FakeBrain + 가짜 Sender + 임시 DB)
  - `test_message_roundtrip_writes_transcript_both_sides`
  - `test_confirmations_appended_below_reply`
  - `test_proposed_tasks_become_draft_ids_on_outbound`
  - `test_queued_messages_coalesce` (Review Focus 5: 처리 중 들어온 메시지 2개 → 다음 호출 1번)
  - `test_user_message_before_run_in_queue`
  - `test_truncate_huge_input` (Review Focus 3)
  - `test_redacted_text_reaches_neither_transcript_nor_brain`
  - `test_daily_cap_reply_without_brain_call` (61번째: 고정 문구, Brain 호출 0)
  - `test_max_turns_sends_confirmations_and_fixed_text`
  - `test_auth_error_notice_once_per_day`
  - `test_send_failure_retries_send_only` (재시도 때 Brain 호출 수 그대로, 도구 이벤트 그대로)
  - `test_brain_failure_with_tool_events_not_rerun`
  - `test_resume_failure_falls_back_to_new_session_with_last_20_messages`
  - `test_evening_run_sets_ask_condition_for_logical_date`
  - `test_stop_waits_then_marks_interrupted`
- [ ] **Step 2~4: 실패 확인 → 구현 → 통과 확인**
- [ ] **Step 5: Commit** `git commit -m "feat: serial dispatcher with two-phase run execution"`

---

### Task 15: 텔레그램 입출력, 명령, 버튼

**Files:**
- Create: `src/my_planner/bot/__init__.py`, `bot/telegram_io.py`, `bot/commands.py`
- Test: `tests/bot/test_telegram_io.py`, `tests/bot/test_commands.py`

**Interfaces:**
- Consumes: `Dispatcher`, `Inbound`, `Outbound`, `Sender` (Task 14), `Tools` (Task 7), `ConversationRouter` (Task 11), `StateRepo`, `ConditionsRepo`
- Produces:
  - `accept_update(update, owner_id, state: StateRepo) -> Literal["accept","ignore","duplicate","non_text"]` — 순수 판정: 발신자 ≠ owner 또는 채팅 종류 ≠ private → `ignore`; `edited_message` → `ignore`; `seen_update` → `duplicate`; 텍스트 없음 → `non_text`.
  - `split_message(text: str, limit: int = 4096) -> list[str]` (빈 줄 → 줄바꿈 → 글자 순으로 경계).
  - `TelegramSender(bot, chat_id)`: `Sender` 구현. `draft_task_ids`가 있으면 초안마다 `✓ 추가`/`✗ 빼기` 버튼 행과 `전부 추가` 행. `ask_condition_for`가 있으면 `1 2 3 4 5` 버튼 한 행. 5초 넘는 처리는 `typing`.
  - 콜백 데이터 형식: `d:c:<id>`(확정), `d:x:<id>`(빼기), `d:all:<id,id,...>`, `c:<YYYY-MM-DD>:<1-5>`.
  - `handle_callback(data: str, tools: Tools, ...) -> str` (짧은 답 문구). 이미 `draft`가 아닌 초안 → "이미 정리된 할 일이에요." 컨디션 버튼은 콜백에 든 날짜로 기록 → "컨디션 {n} 기록했어요."
  - 명령 (`commands.py`, 두뇌 호출 없음): `/today`, `/week`, `/pause <일수>`(1~14 외 값 → 사용법 안내), `/unpause`, `/plan [주제]`(→ `ConversationRouter.start_plan()` 후 주제가 있으면 그 주제를 첫 메시지로 디스패처에 제출, 없으면 디스패처에 "계획 모드 시작" 제출), `/done`, `/help`.
  - `build_application(settings, dispatcher, tools, ...) -> telegram.ext.Application` (롱폴링, `allowed_updates=["message","callback_query"]`).

- [ ] **Step 1: 실패하는 테스트**
  - `test_accept_owner_private_text`
  - `test_ignore_other_user`, `test_ignore_group_chat_from_owner`
  - `test_duplicate_update_id_ignored` (Review Focus 5)
  - `test_edited_message_ignored` (Review Focus 1)
  - `test_non_text_message_gets_polite_reply` (Review Focus 1: "지금은 글로만 이야기할 수 있어요.")
  - `test_split_long_reply` (Review Focus 3: 9000자 → 3조각, 순서 보존, 각 ≤4096)
  - `test_draft_buttons_layout`, `test_condition_buttons_layout`
  - `test_stale_draft_button` (Review Focus 2)
  - `test_condition_button_records_original_date` (Review Focus 2: 10/23 버튼을 10/24에 눌러도 10/23)
  - `test_today_command_shows_priorities_schedule_open_no_drafts`
  - `test_pause_sets_until_and_rejects_15`
  - `test_plan_command_opens_plan_conversation`
  - `test_done_without_plan_says_nothing_open`
- [ ] **Step 2~4: 실패 확인 → 구현 → 통과 확인** (텔레그램 객체는 `telegram` 라이브러리의 `Update.de_json`로 만든 가짜 데이터 사용, 네트워크 없음)
- [ ] **Step 5: Commit** `git commit -m "feat: telegram io, commands, inline buttons"`

---

### Task 16: 루프 실행기, 플랫폼, 로그, 앱 조립

**Files:**
- Create: `loop/runner.py`, `platform/__init__.py`, `platform/windows.py`, `logging_setup.py`, `app.py`, 수정 `__main__.py`
- Test: `tests/loop/test_runner.py`, `tests/test_logging_setup.py`, `tests/test_platform.py`

**Interfaces:**
- Consumes: 모든 앞 Task
- Produces:
  - `class Runner(clock, cfg, runs, state, tasks, router, dispatcher, conn, paths)`: `async def tick() -> None` — 순서: ① `now`, `last_seen_at` 읽기 ② `due_between(window_start, now)`마다 `runs.ensure` ③ `decide(...)` 적용(skip 기록, `return` 회차 생성, `submit_run(primary, merged)`) ④ `last_seen_at = now` ⑤ 하루 한 번: `daily_backup`, `expire_drafts(3일)`, `prune_updates(2일)`, 로그 정리 ⑥ `router.close_expired()`. `async def run_forever(interval=60)`.
  - `platform/windows.py`: `SingleInstanceLock(path)` (컨텍스트 관리자, `msvcrt.locking` 비차단, 실패 시 `AlreadyRunning`), `keep_awake()` (컨텍스트 관리자, `SetThreadExecutionState(ES_CONTINUOUS|ES_SYSTEM_REQUIRED)`, 끝나면 `ES_CONTINUOUS`). Windows가 아니면 둘 다 no-op(테스트용).
  - `setup_logging(state_dir, keep_days=30)` — JSON 줄 로그, 하루 회전, `sys.stdout/stderr`가 None이면 `os.devnull`로 교체. 로그 필터가 `text`, `args`, `input` 키를 지운다.
  - `app.main()` — 스펙 5.1 시작 순서 1~5, `SIGINT`/`SIGTERM`/콘솔 닫기에서 `dispatcher.stop(30)`.

- [ ] **Step 1: 실패하는 테스트**
  - `test_tick_creates_runs_and_submits_due` (FakeClock 월 09:00:30 → morning_brief 제출)
  - `test_tick_updates_last_seen_even_when_nothing_due`
  - `test_tick_after_25h_gap_creates_single_return_run`
  - `test_daily_jobs_run_once_per_logical_day`
  - `test_startup_marks_running_as_interrupted`
  - `test_logging_drops_message_bodies` (로그 레코드에 `text="비밀"` 넣으면 파일에 "비밀" 없음)
  - `test_logging_survives_none_stderr`
  - `test_single_instance_lock_second_fails` (Windows에서만, 그 외 `skipif`)
- [ ] **Step 2~4: 실패 확인 → 구현 → 통과 확인**
- [ ] **Step 5: 로컬 실행 확인** `.env` 채운 뒤 `python -m my_planner` → 텔레그램에 `/help` 보내 응답 확인, Ctrl+C로 정상 종료 로그 확인.
- [ ] **Step 6: Commit** `git commit -m "feat: runner, windows platform helpers, logging, app wiring"`

---

### Task 17: 작업 스케줄러 등록

**Files:**
- Create: `scripts/task_my-planner.xml.tmpl`, `scripts/task_my-planner-wake.xml.tmpl`, `scripts/register_task.ps1`, `scripts/check_tasks.ps1`
- Test: `tests/test_task_templates.py` (XML 내용 검사, 모든 OS에서 실행)

**Interfaces:**
- Produces: `register_task.ps1 [-Root E:\my-planner] [-NoWake]` — 템플릿의 `{{PYTHONW}}`, `{{ROOT}}`, `{{USER}}`, `{{WAKE_TRIGGERS}}`를 채워 `schtasks /Create /XML ... /F`로 등록. 깨우기 트리거는 `config.toml`의 회차 시각 − 5분(평일/주말 각각 `WeeklyTrigger`). Task 0 S4 실패 시 `-NoWake`.
- `check_tasks.ps1` — `schtasks /Query /TN my-planner /XML`을 읽어 아래 값이 맞는지 출력(OK/NG).

- [ ] **Step 1: 실패하는 테스트** (`tests/test_task_templates.py`, XML 파싱)
  - `test_main_task_settings`: `DisallowStartIfOnBatteries=false`, `StopIfGoingOnBatteries=false`, `ExecutionTimeLimit=PT0S`, `MultipleInstancesPolicy=IgnoreNew`, `RestartOnFailure` Interval `PT1M` Count `999`, `LogonType=InteractiveToken`.
  - `test_main_task_triggers`: `LogonTrigger` 1개 + `EventTrigger`(System, `Microsoft-Windows-Power-Troubleshooter`, EventID 1).
  - `test_wake_task_has_wake_to_run_and_noop_action`.
- [ ] **Step 2~4: 실패 확인 → 구현 → 통과 확인**
- [ ] **Step 5: 노트북에서 등록 확인** `powershell -File scripts\register_task.ps1` → `powershell -File scripts\check_tasks.ps1` 전부 OK. 로그오프/로그온 후 `state/logs`에 시작 로그.
- [ ] **Step 6: Commit** `git commit -m "feat: task scheduler registration scripts"`

---

### Task 18: 통합 테스트, 안내 문서, 수용 체크리스트

**Files:**
- Create: `tests/integration/test_day_in_life.py`, `README.md`, `docs/acceptance/sp1-checklist.md`

**Interfaces:**
- Consumes: 모든 구성 요소 (실제 Telegram·Claude 없이 `FakeBrain`, 가짜 `Sender`, `FakeClock`, 임시 루트)

- [ ] **Step 1: 실패하는 통합 테스트**
  - `test_weekday_flow`: 월 08:59 시작 → 09:00 아침 브리핑(FakeBrain이 `propose_tasks` 2개) → 버튼으로 1개 확정 → 사용자 "치과 내일 2시 추가해 줘"(FakeBrain `add_task`) → 확인 문구 → 17:30 체크인, 컨디션 버튼 4 → `conditions`에 기록, 원문 기록 파일에 양쪽 메시지, `tasks.md`에 확정 1개 + 치과, 초안 1개는 3일 뒤 `dropped`.
  - `test_sunday_review_merged_into_evening`: 일 18:00 → 메시지 1개, `review_week` 회차는 `merged_run_ids`에 들어 있고 `data/reviews/weekly/2026-W43.md`(FakeBrain 응답 저장) 존재.
  - `test_laptop_off_26h`: 금 18:00 마지막 tick → 토 20:00 깨어남 → `return` 1개만 전송, 나머지 `skipped(merged_into_return)`.
  - `test_crash_mid_run_no_duplicate_task`: 두뇌 단계에서 `add_task` 후 예외 → 재시작 → `interrupted`, 할 일 1개만.
  - `test_plan_mode_defers_run`: 16:50 `/plan`, 17:30 체크인 대기, 18:00 `/done` → 체크인 실행.
- [ ] **Step 2~4: 실패 확인 → 빠진 연결 수정 → 통과 확인** `pytest -v` 전체 PASS
- [ ] **Step 5: 문서** `README.md`: 설치(venv, `pip install -e .`), `.env` 작성법(BotFather 토큰, 본인 텔레그램 ID 확인법), 작업 스케줄러 등록, 명령 목록, 알아 둘 점 3가지(텔레그램은 24시간까지만 메시지 보관, SDK 세션 기록 사본이 `~/.claude/projects/`에 생김, 저장소를 OneDrive 밖에 둘 것). `docs/acceptance/sp1-checklist.md`: 스펙 1장 완료 조건 1~5를 7일 표(날짜 × 항목, `runs` 확인 SQL 포함)로.
- [ ] **Step 6: Commit** `git commit -m "test: end-to-end day scenarios; docs: README and acceptance checklist"`

---

## 실행 순서와 의존

```
T0 → T1 → T2 → T3 → T4 → T5 → T6 → T7 → T8 ┐
                         T9 → T10 ──────────┤
                    T5 → T11 ───────────────┤
                    T4,T5 → T12 ────────────┤
                         T8,T12 → T13 ──────┤
                    T6,T7,T11,T12,T13 → T14 → T15 → T16 → T17 → T18
```

T9~T10은 T2만 있으면 T3~T8과 병렬로 진행할 수 있다.
