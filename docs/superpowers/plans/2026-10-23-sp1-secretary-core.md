# SP1 비서 코어 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan ticket-by-ticket. Steps use checkbox (`- [ ]`) syntax for tracking. 티켓 하나를 끝낼 때마다 `.claude/agents/code-reviewer.md`로 리뷰한다. 지적을 반영한 뒤에 다음 티켓으로 간다.

**Goal:** 단일 사용자 비서(하네스 + 루프)를 만든다. 비서는 텔레그램으로 먼저 말을 걸고, 사용자와 할 일을 함께 정리한다. Windows 노트북에서 늘 실행되게 한다.

**Architecture:**
- 늘 실행되는 Python 프로세스 하나(asyncio)가 세 가지를 돌린다: 텔레그램 롱폴링, 1분 tick 루프, 직렬 디스패처.
- 판단은 Claude Agent SDK 세션(두뇌)이 한다. 두뇌는 in-process MCP 서버 `planner`의 도구로만 데이터를 바꾼다([ADR 0005](../../adr/0005-brain-only-reaches-planner-tools.md)).
- 원본 데이터는 SQLite `state/planner.db`와 md `data/`에 있다([ADR 0003](../../adr/0003-sqlite-source-of-truth-md-for-humans.md)).
- 계획은 **세로 티켓**(Matt Pocock `to-tickets`)으로 나눈다. 티켓마다 끝에서 끝까지 확인할 수 있는 결과를 낸다. 텔레그램에서 직접 보거나, 가짜 두뇌와 가짜 시계로 자동 확인한다.

**Tech Stack:**
- Python 3.12
- `python-telegram-bot` 21.6 이상, 23 미만
- `claude-agent-sdk>=0.2.173,<0.3` (S3, 번들 CLI 사용)
- `pydantic` v2, `pydantic-settings`
- 표준 라이브러리 `sqlite3`, `zoneinfo`
- `pytest`, `pytest-asyncio`
- Windows: `msvcrt`, `ctypes`, PowerShell, 작업 스케줄러

**Spec:** [`docs/superpowers/specs/2026-10-23-sp1-secretary-core-design.md`](../specs/2026-10-23-sp1-secretary-core-design.md) v3
- 상위: [마스터 설계](../specs/2026-10-23-my-planner-master-design.md)
- 용어: [`GLOSSARY.md`](../../../GLOSSARY.md)
- 결정: [`docs/adr/`](../../adr/)

## Global Constraints

**환경과 이름**
- Python 3.12, 저장소 루트의 `.venv`를 쓴다. 배포판은 티켓 00의 S0 결과로 정한다.
- 패키지는 `my_planner`, 소스는 `src/my_planner/`, 실행은 `python -m my_planner`.
- 회고 루프 이름은 `review`이고, 주기는 따로 둔다: `runs.loop='review'`, `runs.cadence='week'`. 다른 루프의 `cadence`는 `'day'`.
- 파이썬 `LoopKey`의 복귀 인사 멤버 이름은 `return_`이다(값은 `"return"`). `return`이 예약어라서다.

**시간과 형식**
- 시간대는 `Asia/Seoul`이다. 시각은 UTC ISO 8601 문자열로 저장한다.
- 날짜는 논리적 날짜 `YYYY-MM-DD`이고, 하루 경계는 04:00이다. 하루 단위 카운터(`usage_state`)와 하루 한 번 작업도 논리적 날짜를 따른다.
- `period` 형식: 일 `2026-10-23`, 주 `2026-W43`(ISO 주), 월 `2026-10`, 분기 `2026-Q4`, 년 `2026`.
- 영역은 6개다: `career`, `finance`, `health`, `relationships`, `learning`, `quality_of_life`.

**회차 시각과 한계**
- 기본 시각
  - 평일: `morning_brief` 09:00, `evening_checkin` 17:30
  - 주말(토·일): `morning_brief` 10:00, `evening_checkin` 18:00
  - `review`(`week`): 일요일 18:00
- 루프별 한계(이 시각이 지나면 보내지 않는다): 아침은 당일 12:00, 저녁은 다음 날 04:00, 회고는 +3일.
- 답장 창(이 시각까지 답하면 같은 대화로 잇는다): 아침은 당일 12:00, 저녁은 다음 날 04:00, 회고는 24시간.
- 공백이 24시간 이상이면 R1을 적용한다.

**상한**
- 비서가 먼저 보내는 메시지는 하루 최대 3회다. 고정 안내는 세지 않는다.
- 두뇌 호출은 하루 60회, 회차당 최대 2회, 호출당 `max_turns=10`.
- 우선순위는 주기당 최대 3개이고, `open` 할 일만 올린다.
- 초안 만료 3일, 계획 모드 유휴 만료 2시간, `chat` 대화 이어가기 30분.
- 입력은 최대 8000자다. 6시간보다 오래된 메시지는 "몇 시간 전" 알림을 붙여 넘긴다.

**두뇌 설정**
- 스펙 5.3 블록을 그대로 쓴다. 티켓 00 결과로 바뀌면 스펙을 먼저 고친다.

**문구, 로그, 데이터**
- 사용자에게 보이는 문구에 "놓쳤어요", "밀렸어요", "늦었지만", "실패"를 쓰지 않는다. 사용자에게 보이는 문구는 모두 한국어 존댓말이다.
- 로그 `state/logs/my-planner.jsonl`에 메시지 본문과 도구 인자를 남기지 않는다.
- 모든 경로는 `paths.root` 기준 절대경로로 만든다.
- `data/`, `state/`, `.env`는 `.gitignore`에 넣는다. 백업은 로컬 디스크에만 한다.

**테스트 경계** (2026-10-23 Dahun 합의)
- 테스트는 아래 경계에서만 쓴다.
  - **디스패처**: 가짜 두뇌, 가짜 전송, 임시 DB를 쓴다. 메시지를 넣고, 보낸 메시지와 원문 기록과 DB를 확인한다.
  - **따라잡기 판정** `decide()`: 순수 함수, 표 기반.
  - **예정 시각**: `due_between()`, `limit_for()`, `reply_window_end()`, `window_start()`.
  - **러너 tick**: 가짜 시계와 가짜 디스패처.
  - **도구**: MCP 핸들러를 두뇌처럼 직접 await한다.
  - **텔레그램 어댑터**: `Update.de_json`으로 만든 가짜 업데이트. 네트워크는 쓰지 않는다.
  - **가리기**: `redact()`.
  - **두뇌 설정**: `build_options()`.
  - **작업 스케줄러 XML 템플릿**.
  - **앱 시작과 운영 산출물**: `app.main()` 시작 경로(가짜 Bot, 임시 루트), 로그 파일, `python -m` CLI 출력, 프롬프트 파일. 2026-10-23 리뷰에서 추가.
- 저장소(`*Repo`)는 따로 테스트하지 않는다. 위 경계를 거쳐 확인한다. 예외는 마이그레이션 테스트다.

**TDD 주기** (Matt `tdd`: 한 번에 하나씩)
- 각 "슬라이스"는 아래 네 단계를 순서대로 밟는다.
  1. 테스트 하나를 쓴다.
  2. `pytest <파일>::<테스트> -v`로 실행해 FAIL을 확인한다. 새 이름이면 `ImportError`/`AttributeError`, 새 동작이면 `AssertionError`가 기대 결과다(슬라이스에 따로 적힌 경우는 그것).
  3. 통과할 만큼만 구현한다.
  4. 같은 명령으로 PASS를 확인한다.
- 테스트를 몰아서 먼저 쓰지 않는다.
- 티켓이 끝나면 `pytest -q`로 전체를 돌린다. 기대 결과는 0 failed다(Linux에서는 Windows 전용 테스트가 skipped로 나온다). 그다음 `code-reviewer`로 리뷰하고 커밋한다.
- 리팩터링은 이 주기에 넣지 않는다. 리뷰 단계에서 한다.
- 시간에 기대는 테스트(typing 5초, 백오프 2·4·8초, 재전송 5분)는 실제로 기다리지 않는다. `Dispatcher`와 `Runner`는 `sleep=asyncio.sleep`을 주입받고, 테스트는 가짜 sleep과 `FakeClock`을 쓴다.
- 생성자는 키워드 전용(`*`)이고, 티켓마다 인자가 늘어난다. `Dispatcher`: 02 `router`, 03 `tools`, 05 `runs`, 07 `conditions`, 08 `data_dir`. `build_application`: 04 `tools`, 06 `callbacks`. 가변 기본값은 `field(default_factory=list)`나 `None`으로 둔다.

## Review Focus

1. **텍스트가 아닌 메시지**: 사진, 스티커, 음성, 캡션만 있는 사진이 오면 "지금은 글로만 이야기할 수 있어요."라고 답한다. 편집된 메시지는 무시한다. → 티켓 01
2. **오래된 버튼 누름**: 이미 정리된 초안의 버튼은 상태를 바꾸지 않고 짧게 안내한다. 지난 날짜의 컨디션 버튼은 그 날짜에 기록한다. → 티켓 06, 07
3. **아주 긴 입력·출력**: 4096자를 넘는 답은 문단 경계에서 나눠 보내고, 버튼은 마지막 조각에만 붙인다. 8000자를 넘는 입력은 앞부분만 두뇌에 넘기고 그렇게 했다고 알린다. → 티켓 01, 02
4. **시스템 시각 이상**:
   - 시계가 뒤로 가면 공백을 0으로 보고 경고 로그를 남긴다.
   - 시계가 크게 앞서면 창을 7일로 자르고 R1을 적용해 복귀 인사 하나만 보낸다.
   - 어느 쪽이든 회차를 한꺼번에 쏟아내지 않는다. → 티켓 09
5. **같은 메시지를 빠르게 여러 번**: `update_id`가 같으면 무시한다. 서로 다른 메시지가 여러 개 오면 두뇌 호출 한 번으로 이어 붙이고, 그 ID를 모두 처리 완료로 기록한다. → 티켓 01, 02

---

## File Structure

```
pyproject.toml, requirements.lock, config.toml, .env.example, .gitignore, README.md
GLOSSARY.md, docs/adr/, docs/spikes/2026-10-sp1.md (00), docs/acceptance/sp1-checklist.md (14)
scripts/register_task.ps1, check_tasks.ps1, task_my-planner.xml.tmpl, task_my-planner-wake.xml.tmpl (13)
src/my_planner/
  __main__.py, app.py, config.py, clock.py, domain.py, logging_setup.py, wake_times.py
  platform/windows.py                 # SingleInstanceLock, keep_awake
  store/db.py, store/migrations/00N_*.sql
  store/repos/{state,conversations,tasks,runs,conditions}.py
  store/{transcripts,exports,backup,reviews}.py
  harness/{redact,brain,context,conversations,dispatcher}.py, harness/prompts/*.md
  tools/{core,confirmations,mcp_adapter}.py
  loop/{schedule,catchup,runner}.py
  bot/{telegram_io,commands,callbacks}.py
tests/  (경계별: test_dispatcher_*.py, test_catchup.py, test_schedule.py, test_runner.py,
         test_tools_*.py, test_telegram_*.py, test_redact.py, test_brain_options.py,
         test_migrations.py, test_task_templates.py, fakes.py)
```

## 티켓 지도

| # | 티켓 | 막는 티켓 |
|---|---|---|
| 00 | 착수 전 검증 (S0~S6) | 없음 |
| 01 | 걸어 다니는 뼈대: 말 걸면 답한다 | 00 |
| 02 | 대화 이어가기 | 01 |
| 03 | 할 일을 말로 추가·변경 | 02 |
| 04 | 우선순위와 `/today` `/week` `/help` | 03 |
| 05 | 아침 브리핑이 제시간에 온다 | 04 |
| 06 | 비서 제안은 초안, 버튼으로 확정 | 05 |
| 07 | 저녁 체크인과 컨디션 버튼 | 06 |
| 08 | 일요일 주간 회고 | 07 |
| 09 | 꺼졌다 켜져도 알맞게 따라잡는다 | 08 |
| 10 | 멈춤, 상한, 로그인·한도 오류 | 09 |
| 11 | 계획 모드 | 06 |
| 12 | 오래 돌아가도 안전하다 | 05 |
| 13 | 로그온·절전·전원과 상관없이 늘 돈다 | 12 |
| 14 | 7일 수용 테스트 | 10, 11, 13 |

초안과 달라진 점: 03은 02를 기다린다(새 세션 판단과 `context.py`를 함께 쓴다). 07은 06을 기다린다(콜백과 버튼 장치). 08은 07을 거쳐 06의 초안을 쓴다. 10은 09의 R1을 고친다. 그래서 00→01→…→10은 한 줄로 이어지고, 11(06 뒤), 12(05 뒤), 13(12 뒤)이 옆길이다.

---

### 티켓 00: 착수 전 검증 (S0~S6)

**What to build:** 노트북에서 스펙 3장의 가정을 확인하고, 뒤 티켓들이 쓸 값을 확정한다. 시험용 코드는 `spikes/`에 두고 커밋하지 않는다.
**Blocked by:** 없음. 노트북이 필요하다(Remote Control).

**Files:** Create `docs/spikes/2026-10-sp1.md`

- [ ] **S0 Python 배포판**
  - Store판 Python에서 `sqlite3` 확장 로드와 `sqlite_vec.load()`가 되는지 확인한다.
  - `E:\my-planner\.venv\Scripts\pythonw.exe`가 실제 파일인지 확인한다.
  - 하나라도 안 되면 python.org 3.12를 설치해 같은 확인을 반복한다.
- [ ] **S1 작업 스케줄러에서 SDK 호출**
  1. `~/.claude/CLAUDE.md`를 먼저 백업한다.
  2. 임시 작업("로그온할 때", `pythonw.exe spikes\s1_sdk.py`)을 만들어 SDK `query("안녕이라고만 답해")`를 부른다. 결과 파일과 콘솔 창이 떴는지 확인한다.
  3. `claude`가 PATH에 없을 때 쓸 CLI 경로 방식을 정한다.
  4. `claude logout` 상태에서 호출해 예외 종류와 메시지를 기록한다. 끝나면 `claude login`으로 되돌린다.
  5. 사용 한도 오류가 어떤 모양인지 문서나 SDK 소스에서 확인해 기록한다.
- [ ] **S2 도구 잠금**: 더미 도구 12개를 등록한 in-process MCP 서버로 두 가지를 시험한다.
  - "사용 가능한 도구를 전부 나열해": `mcp__planner__*`만 나와야 한다.
  - "Read 도구로 `C:\Windows\win.ini`를 읽어": 읽을 수 없어야 한다.
  - 함께 정할 것: (a) 문자열 `prompt`로 동작하는지, 스트리밍 입력(`ClaudeSDKClient` 또는 async iterable)이 필요한지. (b) `strict_mcp_config`를 필드로 넘기는지, `extra_args={"strict-mcp-config": None}`로 넘기는지.
- [ ] **S3 설정 격리**
  - `~/.claude/CLAUDE.md`에 "모든 답 끝에 🍌"를 넣고 호출한다. 답에 🍌가 없어야 한다. 확인 뒤 원래대로 돌린다.
  - claude.ai 커넥터 도구와 auto memory가 보이지 않는지 확인한다.
  - SDK 버전을 기록한다.
- [ ] **S4 깨우기**: `powercfg /a` 결과를 기록한다. 3분 뒤로 깨우기 작업을 걸고, AC 전원, 배터리, 덮개 닫힘 각각에서 깨어나는지 확인한다.
- [ ] **S5 절전 복귀**: python-telegram-bot 폴링 스크립트를 띄운 채 10분 절전한다. 깨어난 뒤 메시지가 들어오는지 확인한다.
- [ ] **S6 재시작**: 상시 작업 프로세스를 `Stop-Process`로 죽이고 `RestartOnFailure`가 다시 띄우는지 확인한다. 안 되면 5분 반복 트리거가 대신 띄우는지 확인한다.
- [ ] **기록**
  - 항목마다 성공 여부, 명령, 출력 요약, 정한 값을 쓴다.
  - 정할 값: Python 경로, SDK 버전 범위, CLI 경로, 오류 판별 규칙, 호출 형식.
  - 실패한 항목이 있으면 스펙의 해당 절과 이 계획의 Global Constraints를 먼저 고친다.
- [ ] **Commit** `docs: record SP1 spike results`

---

### 티켓 01: 걸어 다니는 뼈대 — 말 걸면 답한다

**What to build:**
- Dahun이 텔레그램 개인 채팅에 쓰면 비서가 답한다.
- 다른 사람, 그룹, 중복 업데이트, 편집된 메시지는 무시한다. 텍스트가 아닌 메시지에는 정중히 안내한다.
- 사용자와 비서의 메시지는 가리기를 거쳐 원문 기록에 남는다.
- 아직 대화는 이어지지 않는다. 메시지마다 새 `chat` 대화를 열고 새 세션을 쓴다.
- 아직 도구도 없다. `planner` 서버는 빈 채로 둔다.
**Blocked by:** 00

**Acceptance criteria**
- [ ] 노트북에서 `python -m my_planner`를 실행하고 "안녕"이라고 보내면 답이 온다. 다른 계정에서 보내면 반응이 없다.
- [ ] `data/transcripts/2026/10/2026-10-23.md`에 양쪽 메시지가 있다. "비번은 hunter2"는 `[가림]`으로 바뀌어 있다.
- [ ] 같은 프로세스를 하나 더 띄우면 바로 종료된다.

**Files:**
- 프로젝트: `pyproject.toml`, `requirements.lock`, `config.toml`, `.env.example`, `.gitignore`, `README.md`(설치, `.env`, 실행)
- `src/my_planner/`: `__main__.py`, `app.py`, `config.py`, `clock.py`, `domain.py`, `logging_setup.py`, `platform/windows.py`
- 저장소: `store/db.py`, `store/migrations/001_core.sql`, `store/repos/{state,conversations}.py`, `store/transcripts.py`
- 하네스: `harness/{redact,brain,dispatcher}.py`, `harness/prompts/{system,chat}.md`
- 기타: `tools/mcp_adapter.py`, `bot/telegram_io.py`, `tests/fakes.py`

**Interfaces (Produces)**

`config.py`
- `resolve_root() -> Path`: 환경변수 `MY_PLANNER_ROOT`가 있으면 그 값, 없으면 패키지 위치에서 두 단계 위다. 항상 `resolve()`한 절대경로를 돌려준다.
- `load_settings(root: Path) -> Settings`: `root/config.toml`과 `root/.env`를 읽는다.
- `Settings` 필드:
  - `telegram_bot_token: SecretStr`, `owner_telegram_id: int`, `timezone="Asia/Seoul"`, `day_boundary=time(4)`
  - `schedule: ScheduleConfig`: 루프별 평일·주말 시각, `review.week`의 요일과 시각
  - `limits: LimitsConfig`: `daily_brain_calls=60`, `max_turns=10`, `daily_proactive_messages=3`, `chat_resume_minutes=30`, `plan_idle_hours=2`, `draft_ttl_days=3`, `stale_message_hours=6`, `input_max_chars=8000`, `reply_window`, `catchup_limit` (값은 Global Constraints)
  - `paths: PathsConfig`: `root`, `data_dir`, `state_dir`, 모두 절대경로
  - `retention: RetentionConfig`: `log_days=30`, `backup_count=14`

`clock.py`
- `Clock` 프로토콜: `now() -> datetime` (UTC aware). 구현은 `SystemClock`과 `FakeClock(start)`(`advance`, `set`).
- `local(dt, tz)`
- `logical_date(dt, tz, boundary) -> date`
- `period_of(cadence, d) -> str`
- `is_weekend(d) -> bool`

`domain.py`
- `Area`, `Cadence`(`day|week|month|quarter|year`), `TaskStatus`(`draft|open|done|dropped`)
- `RunStatus`(`pending|queued|running|done|failed|skipped|interrupted`)
- `SkipReason`(`late|merged_into_return|paused|auth|rate_limit|daily_cap`)
- `LoopKey`(`morning_brief|evening_checkin|review|return_="return"`)
- `ConversationKind`(`run|chat|plan`). `plan`은 용어집의 계획 모드다.
- `@dataclass ToolEvent(kind: str, task_id: int|None, data: dict)`
- `@dataclass RunContext(conversation_id: int|None, run_id: int|None, events: list[ToolEvent])`. 버튼과 명령은 `conversation_id=None`으로 만든다.

`store/db.py`
- `open_db(path) -> Connection`: WAL, `foreign_keys=ON`, `Row` 팩토리.
- `migrate(conn) -> int`: `user_version`보다 번호가 큰 `NNN_*.sql`만 번호순으로, 트랜잭션 안에서 적용한다.
- `integrity_ok(conn) -> bool`

`001_core.sql`
- `conversations(id, kind, run_id NULL, session_id NULL, logical_date, opened_at, last_message_at, closed_at NULL)`
- `app_state(key PK, value)`
- `usage_state(date PK, brain_calls INT, proactive_messages INT)`
- `telegram_updates(update_id PK, received_at)`

저장소
- `StateRepo(conn)`: `get`, `set`, `incr_usage(date, field) -> int`, `usage(date) -> Usage(brain_calls, proactive_messages)`, `is_seen_update(id) -> bool`, `mark_updates_done(ids: list[int])`, `prune_updates(older_than)`.
- `ConversationsRepo(conn, clock)`: `open(kind, logical_date, run_id=None) -> Conversation`, `get(id)`, `touch(id)`, `set_session(id, session_id)`, `close(id)`, `latest_open(kind) -> Conversation|None`.
- `@dataclass Conversation(id, kind, run_id, session_id, logical_date, opened_at, last_message_at, closed_at)`

가리기와 원문 기록
- `redact(text) -> tuple[str, bool]`: 가린 자리는 `[가림]`으로 바꾼다. 휴대전화 번호 `01[016-9]-?\d{3,4}-?\d{4}`는 먼저 제외한다.
- `TranscriptStore(data_dir, tz, boundary)`: `append(at, speaker: "사용자"|"비서", conversation_id: int|None, run_key: str|None, text, tools: list[str] | None = None)`.
  - 머리글 형식: `### HH:MM 비서 [3] (morning_brief)`. 대화가 없으면 `[-]`.
  - 도구 호출은 `> 도구: add_task` 한 줄.

`harness/brain.py`
- `Brain` 프로토콜: `async run(prompt, *, session_id, run_ctx) -> BrainResult`
- `BrainResult(text, session_id, turns, tool_events, status, error=None, resume_failed=False, retry_at: datetime|None = None)`. `status`는 `"ok"|"max_turns"|"auth_error"|"rate_limited"|"error"`.
- `build_options(*, server, session_id, workdir: Path, max_turns, system_prompt, cli_path=None) -> ClaudeAgentOptions`: 스펙 5.3 값을 쓴다. S2 결과: 문자열 `prompt`로 `query()`를 부르고, `strict_mcp_config=True`는 필드로 넘긴다. `cli_path`는 기본 None(번들 CLI)이다.
- `ClaudeBrain(tools_factory, workdir, max_turns, cli_path=None)` (`cli_path`는 번들 CLI가 망가졌을 때를 위한 비상용 설정값 `brain.cli_path`): 호출마다 `build_planner_server(tools, run_ctx)`로 서버를 새로 만든다. 오류 판별은 스펙 5.3 "오류 판별 규칙"(S1 결과)을 따른다. 판별 함수 `classify(messages, exc, now: datetime) -> (status, error, retry_at)`은 가짜 SDK 메시지로 `test_classify_*`에서 확인한다(두뇌 설정 경계에 포함).
- `tests/fakes.py`의 `FakeBrain(script: list[FakeTurn], tools=None)`
  - `FakeTurn(tool_calls, text, status="ok", session_id="s1")`
  - 받은 프롬프트와 `session_id`를 기록해 둔다.

`tools/mcp_adapter.py`
- `build_planner_server(tools, ctx) -> McpSdkServerConfig`: 서버 이름은 `planner`. ctx는 클로저로 넘긴다.
- `TOOL_NAMES: list[str]`: 이 티켓에서는 빈 목록이다. 티켓마다 늘어난다.
- `allowed_tool_patterns() == ["mcp__planner__*"]`

`harness/dispatcher.py`
- `@dataclass Inbound(text, at, sent_at, update_ids: list[int])`
- `@dataclass Outbound(text, draft_conversation_id: int|None = None, draft_task_ids: list[int] = field(default_factory=list), ask_condition_for: date|None = None)`
- `Sender` 프로토콜: `async send(out) -> None`, `async typing() -> None`
- `Dispatcher(*, brain, sender, convs, state, transcripts, clock, settings, keep_awake=nullcontext)`: `submit_message(m)`, `start()`, `stop(timeout=30)`. 작업자는 하나, 큐는 `asyncio.PriorityQueue`.
- 메시지 처리 순서:
  1. `redact`
  2. 원문 기록(사용자)
  3. `chat.md`와 메시지로 두뇌 호출. 호출하는 동안 5초마다 `sender.typing()`.
  4. 원문 기록(비서)
  5. 전송
  6. `mark_updates_done(m.update_ids)`

`bot/telegram_io.py`
- `accept_update(update, owner_id, state) -> "accept"|"ignore"|"duplicate"|"non_text"`: 판정만 하고 DB에 쓰지 않는다. `ignore`와 `non_text`는 핸들러가 응답한 뒤 `mark_updates_done`을 부른다.
- `split_message(text, limit=4096) -> list[str]`: 빈 줄, 줄바꿈, 글자 순서로 자를 곳을 찾는다.
- `TelegramSender(bot: telegram.Bot, chat_id)`: 앱보다 먼저 `telegram.Bot(token)`으로 만든다. 그래서 디스패처와 앱이 서로를 기다리지 않는다.
- `build_application(settings, dispatcher, state, transcripts) -> Application`

`app.main()`
0. `hide_console()`
1. 단일 실행 잠금
2. 로그 설정
3. DB 열기, 마이그레이션
4. Sender, Brain, Dispatcher 만들기
5. 폴링 시작: `async with app: await app.start(); await app.updater.start_polling(allowed_updates=["message","callback_query"], drop_pending_updates=False)`
- 종료 순서: `updater.stop()` → `app.stop()` → `dispatcher.stop(30)`. 콘솔의 Ctrl+C만 처리한다(스펙 5.1 종료).

`platform/windows.py`
- `SingleInstanceLock(path)`: `msvcrt.locking`을 비차단으로 건다. 실패하면 `AlreadyRunning`.
- `keep_awake()`: 참조 카운트를 둔다. 0→1에서 `ES_CONTINUOUS|ES_SYSTEM_REQUIRED`, 1→0에서 `ES_CONTINUOUS`.
- `hide_console() -> str`: `GetConsoleWindow()`가 0일 때만 `kernel32.AllocConsoleWithOptions`를 `mode=2`(NO_WINDOW)로 한 번 부른다. 결과 `"created"|"has_console"|"unavailable"|"not_windows"`를 돌려주고, `app.main()`은 로그 설정 뒤 `unavailable`이면 경고 로그를 남긴다. `app.main()` 맨 처음, 잠금보다 먼저 부른다(스펙 5.1 시작 순서 0).
- Windows가 아니면 셋 다 아무것도 하지 않는다.

`setup_logging(state_dir, keep_days)`
- JSON 한 줄씩, 하루 단위 회전.
- `text`, `args`, `input` 키는 지운다.
- `sys.stdout`이나 `sys.stderr`가 None이면 devnull로 바꾼다.

**Slices** (경계별, 위에서부터 차례로)

마이그레이션
- [ ] `test_migrate_fresh_then_again` (FAIL: ImportError): 새 DB에 적용하면 최신 버전(마이그레이션 파일 수), 다시 실행해도 같다. WAL과 foreign_keys가 켜져 있다. 이 테스트는 티켓마다 마이그레이션이 늘어도 그대로 통과해야 한다.

가리기
- [ ] `test_redact_rrn`: `"900101-1234567"` → `[가림]`, True
- [ ] `test_redact_account_number`: `"110-123-456789"` → 가림
- [ ] `test_redact_password_context`: `"비번은 hunter2야"`, `"password: abc"`, `"PIN 1234"` → 값만 가림
- [ ] `test_redact_keeps_phone_and_dates`: `"010-1234-5678"`, `"2026-10-23"`, `"14:00"`은 그대로, False

두뇌 설정
- [ ] `test_build_options_locks_down_tools`
  - `tools == []`, `allowed_tools == ["mcp__planner__*"]`, `permission_mode == "dontAsk"`
  - strict MCP 설정은 S2에서 정한 형식
  - `setting_sources == []`, env 두 키, `max_turns == 10`
  - `cwd`는 절대경로이고 `state_dir/brain-workdir`로 끝난다
- [ ] `test_build_options_resume_passthrough`
- [ ] `test_classify_auth_error`: `AssistantMessage(error="authentication_failed")` 뒤 `ResultError` → `auth_error`. `billing_error`도 `auth_error`
- [ ] `test_classify_rate_limited`: `RateLimitEvent(status="rejected", resets_at=1792780200)` → `rate_limited`, `retry_at`은 그 시각(UTC). `resets_at`이 없으면 지금+1시간. `allowed_warning`은 `ok`. `billing_error`는 `(auth_error, "billing")`
- [ ] `test_classify_max_turns_and_error`: `ResultMessage(subtype="error_max_turns")` → `max_turns`, 다른 예외 → `error`

텔레그램 어댑터
- [ ] `test_accept_owner_private_text`
- [ ] `test_ignore_other_user`, `test_ignore_group_chat_from_owner`, `test_edited_message_ignored`
- [ ] `test_ignored_update_logs_sender_id_only`: 로그 줄에 `from_id`만 있고 본문은 없다
- [ ] `test_duplicate_update_id_ignored`: `mark_updates_done([7])` 뒤 같은 ID는 `duplicate`, 그 전에는 `accept`
- [ ] `test_non_text_message_gets_polite_reply`: 사진, 캡션만 있는 사진 → `non_text`. 핸들러가 "지금은 글로만 이야기할 수 있어요."를 보낸다
- [ ] `test_split_long_reply`: 9000자 → 3조각, 각각 4096자 이하, 이어 붙이면 원문

디스패처
- [ ] `test_message_roundtrip_writes_transcript_both_sides`: Sender가 FakeBrain의 답을 받는다. 원문 기록 파일에 `사용자`, `비서` 블록이 있다. KST 01:00 메시지는 전날 파일에 들어간다.
- [ ] `test_logical_date_boundary_in_transcript`: KST 03:59 메시지는 전날 파일, 04:00은 당일 파일
- [ ] `test_redacted_text_reaches_neither_transcript_nor_brain`
- [ ] `test_update_ids_marked_after_send`: 전송 전에 크래시하면(Sender 예외) 기록하지 않고, 전송에 성공하면 기록한다
- [ ] `test_typing_every_5_seconds_during_brain_call`: FakeBrain이 12초 걸리면 `typing` 3회
- [ ] `test_logging_drops_message_bodies`: 처리 뒤 로그 파일에 본문 문자열이 없고, `duration_ms`, `turns`, `status`는 있다

앱 시작
- [ ] `test_second_instance_exits` (Windows 전용, 그 밖에서는 skip): `app.main()`을 두 번 띄우면 두 번째가 `AlreadyRunning`으로 바로 끝난다
- [ ] `test_main_hides_console_first`: 가짜 `hide_console`과 가짜 잠금으로 호출 순서가 `hide_console` → 잠금 → 로그이고, `unavailable`이면 로그 파일에 경고 한 줄이 남는다
- [ ] `test_logging_survives_none_stderr`: `sys.stderr=None`으로 `app.main()` 시작 경로를 지나도 예외가 없다

마무리
- [ ] **수동 확인**: 노트북에서 실행해 Acceptance criteria 3개를 확인한다.
- [ ] **README**: 아래 내용을 적는다.
  - 설치 방법, BotFather 토큰 받는 법, 본인 텔레그램 ID 확인법, 실행법
  - 텔레그램은 받아 가지 않은 메시지를 24시간까지만 보관한다
  - `~/.claude/projects/`에 세션 기록 사본이 생긴다
  - 저장소 폴더는 OneDrive 밖에 둔다
- [ ] **Review + Commit** `feat: walking skeleton — owner chats with the secretary over Telegram`

---

### 티켓 02: 대화 이어가기

**What to build:**
- 30분 안에 이어서 말하면 같은 대화, 같은 두뇌 세션으로 이어진다.
- resume이 실패하면 새 세션을 열고, 그 대화의 최근 원문 20개를 붙여 다시 시작한다.
- 처리하는 동안 연달아 온 메시지는 다음 호출 한 번으로 이어 붙인다.
- 너무 긴 입력, 오래된 메시지, 가린 정보는 매 호출 맨 앞의 알림으로 두뇌에 전한다.
**Blocked by:** 01

**Files:** `harness/conversations.py`, `harness/context.py`(알림 부분), `store/transcripts.py`(`recent`), `harness/dispatcher.py`

**Interfaces**
- Consumes: `ConversationsRepo`, `TranscriptStore`, `Dispatcher`, `Inbound` (티켓 01)
- Produces:
  - `ConversationRouter(convs, runs=None, clock, settings)`
    - `for_user_message(at) -> Conversation`: 이 티켓의 규칙은 하나다. 30분 이내의 `chat` 대화가 있으면 잇고, 없으면 새 `chat`을 연다. 회차 대화 규칙은 티켓 05에서, 계획 대화 규칙은 티켓 11에서 이 규칙 앞에 넣는다.
    - `close_expired() -> None`
  - `TranscriptStore.recent(conversation_id, n=20) -> str`: 최근 n개를 시간순으로 돌려준다.
  - `build_notices(*, redacted: bool, stale_hours: float|None, truncated: bool) -> str`: `## 알림` 섹션을 만든다. 해당하는 것이 없으면 `""`.
    - 문구: "인증·식별 정보를 가렸어요", "약 {h}시간 전에 보낸 메시지예요", "메시지가 길어 앞 8000자만 넘겼어요"
  - 디스패처 변경:
    1. 큐에서 메시지를 꺼낼 때 쌓여 있는 메시지를 모두 함께 꺼낸다. 본문은 `\n\n`로 잇고, `update_ids`도 합친다.
    2. 새 세션이면 `chat.md`를 앞에 붙인다. 이어지는 세션이면 메시지만 넘긴다.
    3. 매 호출 맨 앞에 `build_notices` 결과를 붙인다.
    4. 호출이 끝나면 `set_session`과 `touch`를 부른다.
    5. `resume_failed`이면 새 세션과 `recent(conv, 20)`으로 한 번 다시 부른다.

**Slices** (디스패처 경계)
- [ ] `test_chat_resumes_within_30_minutes`: 두 번째 호출의 `session_id == "s1"`
- [ ] `test_chat_new_after_31_minutes`: 두 번째 호출의 `session_id is None`, 대화 id도 다르다
- [ ] `test_queued_messages_coalesce`: 첫 메시지를 처리하는 동안 메시지 2개가 더 오면, 두뇌 호출은 모두 2회다. 두 번째 프롬프트에 두 문장이 다 있고, 세 ID가 모두 기록된다
- [ ] `test_truncate_huge_input`: 9000자 입력 → 프롬프트 본문 8000자와 "앞 8000자만" 알림
- [ ] `test_stale_message_notice`: `sent_at`이 7시간 전이면 "약 7시간 전"
- [ ] `test_redaction_notice_on_resumed_session`: resume한 두 번째 호출에도 `## 알림`이 붙는다
- [ ] `test_resume_failure_falls_back_to_new_session_with_last_20_messages`: 원문 25개 중 최근 20개만 새 세션 프롬프트에 들어간다
- [ ] **Review + Commit** `feat: continue conversations and sessions`

---

### 티켓 03: 할 일을 말로 추가·변경

**What to build:**
- 사용자가 "치과 내일 2시 추가해 줘"처럼 직접 말하면 두뇌가 `add_task`를 부른다. 답 아래에 하네스가 만든 확인 문구 `✓ 추가: 치과 (10/25 14:00)`가 붙는다.
- 바꾸기, 옮기기(날짜 없음 포함), 완료, 되돌리기, 내려놓기, 조회, 원문 기록 읽기도 도구로 할 수 있다.
- 바꿀 때마다 `data/exports/tasks.md`를 다시 만든다.
- 새 세션의 앞머리 컨텍스트에 지금 시각, 열린 할 일, 오늘 일정이 들어간다.
**Blocked by:** 02

**Files:** `store/migrations/002_tasks.sql`, `store/repos/tasks.py`, `store/exports.py`, `tools/core.py`, `tools/confirmations.py`, `tools/mcp_adapter.py`, `harness/context.py`(앞머리), `harness/dispatcher.py`

**Interfaces**
- Consumes: `RunContext`, `ToolEvent`, `build_planner_server`, `TranscriptStore`, `Dispatcher`
- Produces:

`002_tasks.sql`
- 스펙 5.5의 `tasks`, `task_areas`, `task_events`, `priorities`를 그대로 만든다.
- 추가로 `tool_events_log(id, run_id NULL, conversation_id NULL, task_id NULL, kind, at)`.

`TasksRepo(conn, clock)`
- `create(title, areas, status, planned_for, scheduled_at, parent_id, note) -> Task`
- `get`, `update(id, **fields)`, `set_status(id, status)`
- `list(status, from_, to, area, limit)`: 소프트 삭제한 것은 빼고 돌려준다.
- `set_priorities(cadence, period, ids)`, `priorities(cadence, period)`
- `expire_drafts(older_than) -> list[int]`
- 상태가 바뀔 때마다 같은 트랜잭션에서 `task_events`에 기록한다.
- `@dataclass Task(..., areas: list[Area])`

`Tools(*, tasks, transcripts, export_path, clock, tz, boundary, conditions=None)`
- 메서드 형식은 `(ctx, **inputs) -> dict`이다. 이름과 입력은 스펙 5.5 표 그대로다.
- 이 티켓에서 만드는 메서드: `add_task`, `update_task`, `move_task`, `complete_task`, `reopen_task`, `drop_task`, `list_tasks`, `read_transcript`.
- 잘못된 입력은 예외 대신 `{"error": "<한국어 이유>"}`를 돌려준다.
- 바꾸는 메서드는 세 가지를 한다.
  1. 같은 트랜잭션에서 `tool_events_log(ctx.run_id, ctx.conversation_id, task_id, kind)`를 쓴다.
  2. `ctx.events`에 이벤트를 추가한다.
  3. `export_tasks`로 `tasks.md`를 다시 만든다.
- `TOOL_NAMES`에 위 8개를 스펙 표 순서대로 추가한다.

`render_confirmations(events, today) -> str`
- 추가: `✓ 추가: {title}`. 일정이 있으면 뒤에 ` ({M/D} {HH:MM})`를 붙인다. 일정 없이 날짜만 있으면 ` → {오늘|내일|M/D}`를 붙인다.
- 옮김: `✓ 옮김: {title} → {오늘|내일|M/D|날짜 없음}`
- 나머지: `✓ 완료: {title}`, `✓ 되돌림: {title}`, `✓ 내려놓음: {title}`, `✓ 바꿈: {title}`
- 이벤트가 없으면 `""`

`export_tasks(repo, path, today)`
- 오늘, 이번 주, 열린 할 일, 이번 주 완료를 쓴다. 초안은 뺀다.

`build_preamble(*, now, tz, boundary, tasks, conditions=None, paused_until=None, merged=None) -> str`
- 섹션 순서: `## 지금`, `## 우선순위`, `## 열린 할 일`(최대 30개, 오늘 → 이번 주 → 나머지), `## 오늘 일정`, `## 어제 컨디션`, `## 함께 처리할 회차`, `## 멈춤`.
- 빈 섹션은 뺀다. 우선순위는 티켓 04, 컨디션은 티켓 07, 멈춤은 티켓 10에서 채운다.

디스패처 변경
- 새 세션이면 preamble을 붙인다.
- 보내는 본문은 두뇌 답, 빈 줄, 확인 문구 순서다.

**Slices**

마이그레이션
- [ ] `test_migrate_to_2_with_constraints`: 아래 세 경우가 모두 `IntegrityError`다.
  - rank 4
  - `area='sports'`
  - `open`인데 `completed_at`이 있음

도구
- [ ] `test_add_task_creates_open_task_and_exports`: 결과에 id가 있고, `tasks.md`에 제목이 있고, `tool_events_log`에 행이 있다
- [ ] `test_add_task_bad_area_returns_error_dict`, `test_add_task_requires_area`, `test_title_length_limits` (빈 문자열, 201자)
- [ ] `test_complete_then_reopen_clears_completed_at`: `list_tasks(status=done)` 결과로 확인한다
- [ ] `test_move_task_to_no_date`: `planned_for=None` → 결과의 `planned_for`가 null
- [ ] `test_list_tasks_limit_capped_at_50`, `test_list_excludes_soft_deleted`, `test_parent_must_exist`
- [ ] `test_read_transcript_more_than_7_days_returns_error`
- [ ] `test_two_servers_keep_separate_contexts`

확인 문구 (디스패처 경계, FakeClock 2026-10-24, Sender가 받은 본문으로 확인)
- [ ] `test_confirmation_add_with_schedule`: FakeBrain이 10/25 14:00 치과를 `add_task` → `✓ 추가: 치과 (10/25 14:00)`
- [ ] `test_confirmation_move_to_tomorrow`: `✓ 옮김: 운동 → 내일`
- [ ] `test_confirmation_move_to_no_date`: `✓ 옮김: 운동 → 날짜 없음`
- [ ] `test_no_tool_calls_no_confirmation_block`: 도구 호출이 없으면 답 뒤에 빈 줄도 붙지 않는다
- [ ] `test_confirmations_have_no_banned_words`: 이벤트 종류마다 하나씩 부르고 본문에 금지어가 없다

디스패처
- [ ] `test_confirmations_appended_below_reply`: FakeBrain이 `add_task`를 부르면, Sender가 받은 본문에서 답 다음 줄에 `✓ 추가`가 있다. 원문 기록에는 `> 도구: add_task`가 있다
- [ ] `test_preamble_lists_at_most_30_open_tasks_in_order`, `test_preamble_today_schedule`
- [ ] `test_max_turns_sends_confirmations_and_fixed_text`: `status="max_turns"`이면 확인 문구와 "정리하다가 길어졌어요. 이어서 말씀해 주시면 계속할게요."
- [ ] `test_brain_call_log_has_tool_names`: 로그 줄에 `tool_names: ["add_task"]`, 인자는 없다

마무리
- [ ] **수동 확인**: 텔레그램에서 "치과 내일 2시 추가해 줘"를 보내고, 확인 문구와 `tasks.md`를 확인한다.
- [ ] **Review + Commit** `feat: add and change tasks by chat with confirmations`

---

### 티켓 04: 우선순위와 `/today` `/week` `/help`

**What to build:**
- "이번 주 우선순위는 A, B, C"라고 말하면 두뇌가 `set_priorities`를 부른다. 답 아래에 `✓ 우선순위(이번 주): 1. A 2. B 3. C`가 붙는다.
- `/today`, `/week`, `/help`는 두뇌를 거치지 않고 바로 답한다.
- 명령과 그 응답도 원문 기록에 남는다.
**Blocked by:** 03

**Files:** `tools/core.py`, `tools/confirmations.py`, `harness/context.py`, `bot/commands.py`, `bot/telegram_io.py`

**Interfaces**
- Consumes: `Tools`, `TasksRepo`, `TranscriptStore`, `build_preamble`
- Produces:
  - `Tools.set_priorities(ctx, cadence, period, task_ids)`: 4개 이상이거나 `open`이 아닌 할 일이 있으면 error dict를 돌려준다. ToolEvent는 `priorities_set`.
  - 확인 문구: `✓ 우선순위({오늘|이번 주|이번 달|이번 분기|올해}): 1. … 2. … 3. …`
  - preamble의 `## 우선순위`에 오늘과 이번 주 우선순위를 넣는다.
  - `commands.py`
    - `today_text(tasks, now, tz, boundary) -> str`: 우선순위, 일정, 열린 할 일을 보여 준다. 초안은 뺀다.
    - `week_text(...)`
    - `HELP_TEXT`
    - 핸들러는 응답을 보낸 뒤 `[-]` 원문 기록을 남긴다.

**Slices**

도구
- [ ] `test_set_priorities_replaces_whole_period`, `test_set_priorities_four_returns_error`, `test_set_priorities_rejects_draft_and_done`
- [ ] `test_priority_unique_task_per_period`: 같은 할 일을 두 순위에 올리면 error
- [ ] `test_drop_removes_from_priorities`

텔레그램 어댑터
- [ ] `test_today_command_shows_priorities_schedule_open_no_drafts`
- [ ] `test_week_and_help_commands`
- [ ] `test_command_logged_to_transcript`
- [ ] `test_command_from_other_user_ignored`

마무리
- [ ] **Review + Commit** `feat: priorities and quick commands`

---

### 티켓 05: 아침 브리핑이 제시간에 온다

**What to build:**
- 평일 09:00, 주말 10:00에 비서가 먼저 아침 브리핑을 보낸다. 내용은 오늘 우선순위 1~3개, 첫 걸음, 일정이다.
- 회차는 `runs`에 두 단계로 기록한다. 두뇌의 답을 먼저 `outbound_text`에 저장하고, 그다음 보낸다.
- 전송이 안 되면 바로 3회 시도한다. 그래도 안 되면 5분 뒤 전송만 한 번 더 한다.
- 이 티켓의 따라잡기는 R4와 R5뿐이다. 한계 안이면 늦게라도 보내고, 한계 밖이면 `skipped(late)`로 둔다.
- 브리핑에 답하면 12:00까지는 그 회차의 대화로 이어진다.
**Blocked by:** 04

**Files:** `store/migrations/003_runs.sql`, `store/repos/runs.py`, `loop/{schedule,catchup,runner}.py`, `harness/prompts/morning_brief.md`, `harness/dispatcher.py`, `harness/conversations.py`, `app.py`

**Interfaces**
- Consumes: `Dispatcher`, `ConversationRouter`, `build_preamble`, `StateRepo`, `Clock`
- Produces:

`003_runs.sql`
- `runs(id, loop, cadence NOT NULL DEFAULT 'day', scheduled_for, status, skip_reason NULL, attempt DEFAULT 0, started_at, finished_at, outbound_text NULL, resent INT DEFAULT 0, error NULL, conversation_id NULL, merged_run_ids DEFAULT '[]', created_at)`
- UNIQUE `(loop, cadence, scheduled_for)`
- status와 skip_reason에 CHECK 제약

`RunsRepo(conn, clock)`
- `ensure(loop, scheduled_for, cadence=Cadence.day) -> Run`, `get(id) -> Run|None`
- 상태 바꾸기: `mark_queued`, `mark_running`, `save_outbound(id, text)`, `mark_done`, `mark_failed(id, error)`, `mark_skipped(id, reason)`, `add_merged(id, ids)`, `mark_resent(id)`
- 조회: `pending() -> list[Run]`, `between(start, end)`, `has_tool_events(id) -> bool`
- `@dataclass Run(id, loop, cadence, scheduled_for, status, skip_reason, attempt, outbound_text, resent, conversation_id, merged_run_ids: list[int])`

`schedule.py`
- `@dataclass(frozen=True) Due(loop, scheduled_for, cadence=Cadence.day)`
- `due_between(start, end, cfg, tz, loops: set[LoopKey]) -> list[Due]`: `(start, end]` 구간, 시간순, `loops`에 든 루프만. 앱이 켜는 루프는 05에서 `{morning_brief}`, 07에서 `evening_checkin`, 08에서 `review`를 더한다(`ENABLED_LOOPS` 상수). 프롬프트가 없는 루프가 실행되지 않게 하려는 것이다. 테스트는 모든 루프를 켜고 부른다.
- `window_start(now, last_seen_at, installed_at) = min(now, max(last_seen_at, installed_at, now - 7일))`
- `limit_for(due, cfg, tz, boundary)`, `reply_window_end(due, tz, boundary)`

`catchup.py`
- `@dataclass Decision(primary: Due|None, merged: list[Due], skipped: list[tuple[Due, SkipReason]], create_return: bool, carry_review: Due|None)`
- `decide(now, last_seen_at, pending, *, carried_review=None, paused_until=None, limited_until=None, brain_calls_today=0, proactive_today=0, plan_open=False, cfg, tz, boundary) -> Decision`
- 이 티켓에서는 R4와 R5만 구현한다. 나머지 인자는 티켓 08~11에서 쓴다.

`Runner(clock, settings, runs, state, dispatcher)`
- `tick()` 순서:
  1. `now`와 이전 `last_seen_at`을 읽는다.
  2. `due_between(window_start(...), now)`의 각 항목마다 `runs.ensure`를 부른다.
  3. `decide`에 `runs.pending()`을 Due로 바꿔 넘기고, 결과를 적용한다. 건너뛸 회차는 skip으로 기록한다. `primary`와 `merged` 회차는 `mark_queued`한 뒤 `submit_run`으로 넘긴다.
  4. `last_seen_at = now`
- `run_forever(interval=60)`
- 첫 실행이면(`installed_at`이 없으면) 지금 시각을 기록한다.
- 하루 한 번 작업: `register_daily(job: Callable[[date], None])`. tick 끝에서 `app_state.last_daily_jobs_date`가 논리적 오늘과 다르면 등록된 작업을 차례로 부르고 날짜를 기록한다. 06, 12가 작업을 등록한다.
- `app.main()` 시작 순서(스펙 5.1): 창 숨김 → 잠금 → 로그 → DB → (12의 복구) → `installed_at` → 첫 tick 판정 → 폴링 → `run_forever`.

대화 라우터 변경
- `ConversationRouter.for_run(run) -> Conversation`: 항상 새 `run` 대화를 연다.
- `for_user_message`는 답장 창 안의 가장 최근 `run` 대화를 30분 규칙보다 먼저 본다.

디스패처 `submit_run(run, merged)`
1. `mark_running`
2. 루프 프롬프트(스펙 5.3 "프롬프트 선택")와 preamble로 두뇌를 부른다.
3. `save_outbound`
4. 전송한다. 바로 3회(1, 2, 4초 간격)까지 시도한다.
5. `mark_done`(primary와 merged 모두), `incr_usage(today, "proactive_messages")`
- 전송이 끝내 안 되면: `mark_failed`, 5분 뒤 `outbound_text`로 한 번 다시 보낸다(`mark_resent`).
- 두뇌 단계가 안 되면(`error`): `has_tool_events`가 False이고 한계 안이면 한 번 다시 실행한다. 아니면 `failed`로 둔다. 어느 경우든 사용자에게는 아무것도 보내지 않는다. `auth_error`와 `rate_limited`는 재실행하지 않는다(티켓 10).
- 큐 순서: 사용자 메시지(우선순위 0)가 회차(1)보다 먼저다. 같은 우선순위는 들어온 순서.
- 회차 대화에 사용자가 답할 때는 루프 지시문 없이 메시지만 넘긴다. 그 대화의 resume이 실패하면 preamble과 `recent(conv, 20)`만 넘긴다.

**Slices**

예정 시각
- [ ] `test_weekday_times`: 2026-10-26(월) → 09:00, 17:30 KST
- [ ] `test_weekend_times`: 2026-10-24(토) → 10:00, 18:00
- [ ] `test_half_open_interval`
- [ ] `test_window_start_first_run_uses_installed_at`, `test_window_start_capped_7_days`, `test_window_start_future_last_seen_clamped_to_now`
- [ ] `test_limits_and_reply_windows`
  - 한계: 아침 → 당일 12:00, 저녁(월 17:30) → 화 04:00, 회고 → +3일
  - 답장 창: 아침 → 12:00, 저녁 → 04:00, 회고 → 24시간

따라잡기 판정
- [ ] `test_spec_table_row_1`: 월 08:00 → 월 10:30이면 실행
- [ ] `test_spec_table_row_2`: 월 08:00 → 월 13:00이면 `late`

러너
- [ ] `test_tick_creates_runs_and_submits_due`: FakeClock 월 09:00:30 → `morning_brief` 하나가 `queued`가 되고 제출된다
- [ ] `test_run_not_resubmitted_while_queued`: 두 번째 tick에서는 제출이 없다
- [ ] `test_tick_updates_last_seen_even_when_nothing_due`
- [ ] `test_daily_jobs_run_once_per_logical_day`: 등록한 가짜 작업이 하루 1회, 04:00 경계로 다음 날
- [ ] `test_installed_at_set_once`

디스패처
- [ ] `test_morning_run_two_phase`: `outbound_text`를 저장한 뒤 보낸다. 상태는 `done`, proactive 카운터는 1
- [ ] `test_send_retries_3_then_failed_then_resend_once`: Sender가 계속 안 되면 3회 시도 후 `failed`, 5분 뒤 한 번 다시 보낸다. 두뇌 호출 수는 그대로다
- [ ] `test_brain_failure_without_tool_events_reruns_once`, `test_brain_failure_with_tool_events_not_rerun`, `test_run_failure_sends_nothing_to_user`
- [ ] `test_reply_within_morning_window_continues_run_conversation`, `test_reply_window_beats_30_minutes`
- [ ] `test_reply_to_run_has_no_loop_prompt`
- [ ] `test_run_and_message_serialized`: 회차 처리 중 들어온 메시지는 회차가 끝난 뒤 처리되고, 대기 중인 회차보다는 먼저 처리된다

마무리
- [ ] **수동 확인**: 다음 날 아침 실제로 브리핑을 받는다.
- [ ] **Review + Commit** `feat: morning brief on schedule with two-phase runs`

---

### 티켓 06: 비서 제안은 초안, 버튼으로 확정

**What to build:**
- 브리핑이나 대화에서 비서가 제안한 할 일은 `propose_tasks`로 `draft`가 된다.
- 메시지의 마지막 조각 아래에 초안마다 `✓ 추가` `✗ 빼기` 버튼을 붙이고, `전부 추가` 버튼도 하나 붙인다. 버튼은 두뇌를 거치지 않는다.
- 사용자가 글로 "좋아 다 넣어"라고 하면 두뇌가 `confirm_tasks`를 부른다.
- 3일 동안 확정하지 않은 초안은 조용히 `dropped`가 된다.
- `/today`와 아침 브리핑에는 초안이 보이지 않는다.
**Blocked by:** 05

**Files:** `tools/core.py`, `bot/callbacks.py`, `bot/telegram_io.py`, `loop/runner.py`(하루 한 번 작업), `harness/dispatcher.py`

**Interfaces**
- Consumes: `Tools`, `TasksRepo`, `Outbound`, `TelegramSender`, `Runner`
- Produces:
  - `Tools.propose_tasks(ctx, tasks: list[dict])`: ToolEvent는 `tasks_proposed`(data에 ids).
  - `Tools.confirm_tasks(ctx, ids)`: 결과는 `{"confirmed": [...], "skipped_ids": [...]}`. ToolEvent는 `tasks_confirmed`, 확인 문구는 `✓ 확정: {title}`. `tasks_proposed`에는 확인 문구가 없다(버튼이 대신한다).
  - 디스패처: `tasks_proposed`의 id를 `Outbound.draft_task_ids`에 넣고, `draft_conversation_id=ctx.conversation_id`로 둔다.
  - 콜백 데이터: `d:c:<task_id>`(추가), `d:x:<task_id>`(빼기), `d:all:<conversation_id>`(전부 추가). 모두 64바이트 이하다.
    - `d:all`은 `tool_events_log`에서 그 대화의 `tasks_proposed` task_id를 찾고, 그중 아직 `draft`인 것을 확정한다.
  - `handle_callback(query, owner_id, tools, ...) -> str`
    1. 보낸 사람이 사용자가 아니면 무시한다.
    2. 이미 `draft`가 아닌 할 일이면 "이미 정리된 할 일이에요."라고 답한다.
    3. 항상 `query.answer()`를 부른다.
    4. 원문 기록에 `[버튼] 확정: {title}`처럼 남긴다.
  - `Runner.register_daily`(티켓 05)에 `expire_drafts(3일)`을 등록한다.

**Slices**

도구
- [ ] `test_propose_tasks_creates_drafts`, `test_confirm_tasks_only_drafts`
- [ ] `test_drafts_cannot_be_priorities`

텔레그램 어댑터
- [ ] `test_draft_buttons_layout`, `test_buttons_only_on_last_chunk`
- [ ] `test_draft_all_callback_fits_64_bytes_and_confirms_conversation_drafts`
- [ ] `test_stale_draft_button`, `test_callback_from_other_user_ignored`, `test_button_logged_to_transcript`
- [ ] `test_today_hides_drafts`

러너
- [ ] `test_expire_drafts_after_3_days`: 2일 23시간이면 그대로, 3일이면 `dropped`

마무리
- [ ] **Review + Commit** `feat: secretary proposals are drafts confirmed by buttons`

---

### 티켓 07: 저녁 체크인과 컨디션 버튼

**What to build:**
- 평일 17:30, 주말 18:00에 체크인 메시지가 온다. `1 2 3 4 5` 버튼으로 그날 컨디션을 기록한다.
- 자정이 지나 답해도 04:00까지는 같은 체크인 대화로 이어진다.
- 아침 브리핑 때 어제 컨디션 기록이 없고 어제 체크인이 `done`이 아니면, 브리핑에 어제 날짜의 컨디션 버튼을 붙인다.
- 컨디션이 2 이하면 비서가 할 일을 줄이자고 먼저 제안한다(프롬프트에 넣는다).
**Blocked by:** 06 (콜백 장치와 버튼 렌더링)

**Files:** `store/migrations/004_conditions.sql`, `store/repos/conditions.py`, `tools/core.py`, `bot/callbacks.py`, `harness/prompts/evening_checkin.md`, `harness/dispatcher.py`, `harness/context.py`

**Interfaces**
- Produces:
  - `004_conditions.sql`: `conditions(date PK, score CHECK 1~5, note, recorded_at)`
  - `ConditionsRepo`: `upsert(date, score, note)`, `get(date)`
  - `Tools.record_condition(ctx, score, date=None, note=None)`: `date`를 안 주면 논리적 오늘이다. 점수가 범위 밖이면 error dict.
  - 콜백 `c:<YYYY-MM-DD>:<1-5>`: 콜백에 든 날짜로 기록하고 "컨디션 {n} 기록했어요."라고 답한다.
  - 디스패처
    - 저녁 회차: `ask_condition_for`는 그 회차의 논리적 날짜다.
    - 아침 회차: 스펙 5.4 "어제 컨디션" 조건에 맞으면 `ask_condition_for`는 어제다.
  - preamble의 `## 어제 컨디션`: 기록이 없으면 "기록 없음".

**Slices**

도구
- [ ] `test_record_condition_defaults_to_logical_today`: KST 01:30이면 전날로 기록
- [ ] `test_record_condition_out_of_range_error`

텔레그램 어댑터
- [ ] `test_condition_buttons_layout`
- [ ] `test_condition_button_records_original_date`: 10/23 버튼을 10/24에 눌러도 10/23에 기록

디스패처
- [ ] `test_evening_run_sets_ask_condition_for_logical_date`
- [ ] `test_reply_to_evening_checkin_after_midnight_continues`, `test_reply_after_0400_opens_new_chat`
- [ ] `test_morning_asks_yesterday_condition_when_evening_not_done`: 어제 체크인이 `late`일 때와 `merged_into_return`일 때 모두
- [ ] `test_morning_no_ask_when_condition_exists`

따라잡기 판정
- [ ] `test_spec_table_row_3`: 월 17:00 → 화 01:00이면 저녁 체크인 실행
- [ ] `test_spec_table_row_4`: 월 17:00 → 화 05:00이면 `late`

마무리
- [ ] **Review + Commit** `feat: evening check-in with condition buttons`

---

### 티켓 08: 일요일 주간 회고

**What to build:**
- 일요일 18:00에 주간 회고가 저녁 체크인과 합쳐져 한 메시지로 온다. 회고 지시문은 체크인 지시문 뒤에 이어 붙인다.
- 다음 주 우선순위 제안은 초안으로 낸다. 사용자가 확정하고 승인하면 두뇌가 `set_priorities`를 부른다.
- 두뇌의 답을 `data/reviews/week/<YYYY-Www>.md`에 저장한다. 어느 주인지는 회고 회차 `scheduled_for`의 논리적 날짜로 정한다.
- 합쳐진 회차는 실행된 회차가 전송에 성공하면 함께 `done`이 된다.
**Blocked by:** 07 (06의 초안을 07을 거쳐 씀)

**Files:** `loop/schedule.py`, `loop/catchup.py`, `store/reviews.py`, `harness/prompts/review_week.md`, `harness/dispatcher.py`

**Interfaces**
- Produces:
  - `due_between`이 일요일 18:00에 `Due(review, ..., Cadence.week)`를 돌려준다.
  - `decide`의 합치기: 같은 tick에서 실행할 회차 중 `primary` 하나를 고르고, 나머지는 `merged`에 넣는다. 고르는 순서는 `return_ > evening_checkin > morning_brief > review`.
  - `save_weekly_review(data_dir, period, text) -> Path`: 같은 주 파일이 있으면 덮어쓴다.
  - 디스패처: primary가 회고이거나 `merged`에 회고가 있으면 저장한다. `period = period_of(week, logical_date(review.scheduled_for))`.

**Slices**
- [ ] 예정 시각 `test_sunday_has_review_at_1800`: 2026-10-25 → morning 10:00, evening 18:00, review(week) 18:00
- [ ] 따라잡기 판정 `test_spec_table_row_9`: 일 17:00 → 일 18:10이면 저녁 체크인이 primary, 회고는 merged
- [ ] 디스패처 `test_weekly_review_saved_when_merged_into_evening`: `data/reviews/week/2026-W43.md`가 생긴다. 메시지는 1개, 두 회차 모두 `done`, 지시문에 회고 문구가 있다
- [ ] 디스패처 `test_merged_runs_marked_done_after_send`
- [ ] **Review + Commit** `feat: weekly review merged into Sunday check-in`

---

### 티켓 09: 꺼졌다 켜져도 알맞게 따라잡는다

**What to build:** 스펙 5.4의 R1을 끝까지 구현한다.
- 24시간 이상 꺼졌다 켜지면 복귀 인사 하나만 보낸다. 내용은 "다시 이어서 해 볼까요"와 오늘 할 것이다.
- 공백 동안의 회차는 `skipped(merged_into_return)`가 된다.
- 복귀 인사가 그날 아침 브리핑 시각 전에 나가면 그날 아침 브리핑도 건너뛴다.
- 3일 안에 있었던 회고는 넘겨 받아 다음 정규 연락에 합친다.
- 하루 4번째가 될 메시지는 보내지 않고 기다린다.
- 시계 이상도 처리한다(Review Focus 4).
**Blocked by:** 08

**Files:** `loop/catchup.py`, `loop/runner.py`, `harness/prompts/return.md`

**Interfaces**
- Produces:

`decide`의 R1
- `create_return=True`, `primary=Due(return_, now)`
- 복귀 인사가 오늘 아침 브리핑 예정 시각 전에 나가면, 오늘 아침 브리핑의 **아직 오지 않은** Due를 `skipped`에 `merged_into_return`으로 넣는다. 러너는 그 Due를 `ensure`한 뒤 skip을 기록하므로, 09:00 tick에는 이미 `skipped`라 실행되지 않는다.
- 공백 중에 회고가 있었고 +3일 이내면 `carry_review`에 넣는다.
- 넘겨 받은 회고(`carried_review`)는 혼자 실행하지 않는다. 정규 연락이 실행될 때 `merged`에 넣는다. 한계를 넘으면 `skipped(late)`.
- 시계가 뒤로 갔으면 공백을 0으로 보고 `Decision.clock_backwards=True`. 경고 로그는 러너가 남긴다(`decide`는 부작용 없음).

하루 3회 상한
- `proactive_today >= 3`이면 `primary`를 비우고, skip도 기록하지 않는다(그대로 기다린다).
- 다음 판정 때 한계 안이면 다른 회차에 합쳐지고, 한계를 넘으면 `late`가 된다.

러너
- `create_return`이면 `runs.ensure(return_, now)`를 부른다.
- `carry_review`는 `app_state.carry_review_run_id`에 저장한다. 합쳐지거나 `late`가 되면 지운다.
- 루프 `return_`의 프롬프트는 `return.md`다.

**Slices**

따라잡기 판정
- [ ] `test_spec_table_row_5`: 토 17:00 → 일 18:30이면 R1, 회고는 넘겨 받는다
- [ ] `test_spec_table_row_6`: 금 22:00 → 화 08:00이면 `return` 하나. `skipped`에 화 09:00 아침 브리핑(`merged_into_return`)이 있다. 회고는 `carry_review`이고 화 17:30 체크인에 합친다. 화 09:00 tick에 보낼 메시지와 월요일 컨디션 버튼은 없다(러너 테스트로 확인)
- [ ] `test_spec_table_row_7`: 금 22:00 → 목 08:00이면 회고는 `merged_into_return`
- [ ] `test_spec_table_row_10`: 금 18:00 → 토 09:30이면 보낼 회차가 없다
- [ ] `test_carried_review_not_executed_alone`, `test_carried_review_late_after_3_days`
- [ ] `test_fourth_proactive_message_waits_then_merges_or_late`
- [ ] `test_clock_went_backwards`: 공백 0, R1이 아니다, `clock_backwards=True`
- [ ] `test_clock_jumped_far_ahead_is_capped_at_7_days`: 30일 앞으로 가면 `return` 하나, 판정 대상은 7일치뿐이다

러너
- [ ] `test_tick_after_25h_gap_creates_single_return_run`, `test_r1_carried_review_merges_into_next_contact`, `test_deferred_run_reconsidered_next_tick`
- [ ] `test_return_before_morning_skips_that_morning`: 화 08:00 복귀 → 09:00 tick에 제출 없음
- [ ] `test_clock_backwards_logs_warning`

앱 시작과 운영 산출물
- [ ] `test_prompts_have_no_banned_words`: 프롬프트 파일의 금지어를 검사한다. `system.md`의 `<!-- banned-words:start/end -->` 블록은 금지어 목록 자체라서 뺀다

마무리
- [ ] **Review + Commit** `feat: catch-up rules and return message`

---

### 티켓 10: 멈춤, 상한, 로그인·한도 오류

**What to build:**
- `/pause <1~14>`로 그 기간 동안 회차를 멈춘다(`skipped(paused)`). 멈춤 중에도 사용자 메시지에는 답한다. 멈춤 중에는 24시간 넘게 꺼졌다 켜져도 복귀 인사를 보내지 않는다. `/unpause`로 푼다.
- 하루 두뇌 호출이 60회를 넘으면 대화에는 고정 문구로 답하고, 회차는 `skipped(daily_cap)`로 둔다.
- 로그인이 풀리면 하루 한 번 안내하고, 회차는 `skipped(auth)`로 둔다.
- 사용 한도에 닿으면 구간마다 한 번 안내하고, 풀릴 때까지 회차는 `skipped(rate_limit)`로 둔다.
- 사용자 메시지를 처리하다 오류가 나면 2, 4, 8초 간격으로 3회 다시 시도하고, 그래도 안 되면 고정 문구로 답한다.
**Blocked by:** 09

**Files:** `bot/commands.py`, `loop/catchup.py`, `harness/brain.py`, `harness/dispatcher.py`, `harness/context.py`

**Interfaces**
- Produces:
  - `decide`: R2(`paused_until`), R3(`brain_calls_today >= 60`), `limited_until`을 적용한다. R1은 멈춤 중이 아닐 때만 적용한다.
  - `app_state` 키: `pause_until`, `last_auth_notice_date`, `limited_until`, `last_rate_limit_notice_until`
  - `ClaudeBrain`이 스펙 5.3 "오류 판별 규칙"대로 `auth_error`와 `rate_limited`를 가려내고 `retry_at`을 채운다. SDK가 시각을 주지 않으면 지금 + 1시간.
  - 고정 문구는 스펙 5.3과 7장 그대로다. 비서가 먼저 보내는 하루 3회에는 세지 않는다.
  - preamble의 `## 멈춤`

**Slices**

따라잡기 판정
- [ ] `test_paused_skips_with_reason`
- [ ] `test_spec_table_row_8`: 멈춤 중이면 R2, `return` 없음
- [ ] `test_daily_cap_skips_with_reason`, `test_rate_limited_until_skips_with_reason`
- [ ] `test_pause_boundary`: 멈춤이 끝나기 1분 전 회차는 `paused`, 1분 뒤 회차는 실행

텔레그램 어댑터
- [ ] `test_pause_sets_until_and_rejects_15`, `test_unpause`

디스패처
- [ ] `test_paused_still_answers_messages`
- [ ] `test_daily_cap_reply_without_brain_call`: 61번째 메시지에는 고정 문구, 두뇌 호출 0회, `/today`는 그대로 동작
- [ ] `test_auth_error_notice_once_per_day`, `test_rate_limited_notice_once_per_window`
- [ ] `test_billing_error_uses_billing_copy`: `error="billing"`이면 결제 문구, 하루 한 번
- [ ] `test_rate_limited_resume_text_formats`: 재개가 오늘 21:30이면 `21:30쯤`, 10/30 09:00이면 `10월 30일 09:00쯤`, 이미 지난 `retry_at`이면 지금+1시간
- [ ] `test_error_retries_3_times_with_backoff_then_fixed_text`: 호출 4회, `brain_calls` +4
- [ ] `test_run_error_no_backoff_max_two_calls`
- [ ] `test_run_auth_error_marked_skipped_not_rerun` (rate_limited도 같은 테스트에서 `skipped(rate_limit)`)

마무리
- [ ] **Review + Commit** `feat: pause, daily cap, auth and rate-limit handling`

---

### 티켓 11: 계획 모드

**What to build:**
- `/plan [주제]`로 계획 대화를 연다. 비서는 질문을 하나씩 하며 할 일과 목표를 좁히고, 초안 버튼으로 확정받는다.
- `/done`으로 닫는다. 마지막 메시지 뒤 2시간이 지나면 저절로 닫힌다.
- 계획 대화가 열려 있는 동안 시작되는 회차는 닫힐 때까지 미룬다. 한계를 넘으면 `late`.
- 사용자가 글로 "같이 계획 세우자", "여기까지"라고 쓰면 비서가 명령을 안내한다(프롬프트에 넣는다).
**Blocked by:** 06

**Files:** `harness/conversations.py`, `bot/commands.py`, `harness/prompts/plan.md`, `loop/catchup.py`, `loop/runner.py`

**Interfaces**
- Produces:
  - `ConversationRouter.start_plan() -> Conversation`: 열려 있던 다른 계획 대화는 닫는다.
  - `ConversationRouter.end_plan() -> bool`, `plan_open() -> bool`
  - `for_user_message`는 2시간 이내의 열린 계획 대화를 가장 먼저 본다.
  - `/plan`: 주제가 있으면 그 주제를, 없으면 "계획 모드 시작"을 `plan.md`와 함께 디스패처에 넘긴다.
  - `decide(plan_open=True)`이면 한계 안의 회차는 판정하지 않고 그대로 둔다.

**Slices**

디스패처
- [ ] `test_plan_takes_precedence_and_expires_after_2h`, `test_plan_uses_plan_prompt`

텔레그램 어댑터
- [ ] `test_plan_command_opens_plan_conversation`, `test_done_without_plan_says_nothing_open`

따라잡기 판정
- [ ] `test_plan_open_defers_within_limit`, `test_plan_open_past_limit_is_late`

러너
- [ ] `test_plan_mode_defers_run`: 16:50 `/plan`, 17:30 체크인은 대기, 18:00 `/done` 뒤 다음 tick에 체크인 실행

마무리
- [ ] **Review + Commit** `feat: plan mode`

---

### 티켓 12: 오래 돌아가도 안전하다

**What to build:**
- 매일 첫 tick에 `state/backups/planner-YYYY-MM-DD.db`로 백업하고, 14개를 남긴다.
- 로그는 하루 단위로 회전하고 30일 보관한다.
- 시작할 때 복구한다.
  - `queued`나 `running`으로 남은 회차는 `interrupted`로 바꾸고, 스펙 5.4-3 재실행 규칙을 적용한다.
  - `failed` 중 아직 다시 보내지 않은 회차는 답장 창 안이면 한 번 다시 보낸다.
- DB 무결성 검사가 실패하면 안전 모드로 들어간다. 알림은 표식 파일로 한 번만 보내고, 폴링과 tick 없이 기다린다.
- 처리한 `update_id`는 2일 뒤 지운다.
- README에 백업 복구 절차를 쓴다.
**Blocked by:** 05

**Files:** `store/backup.py`, `logging_setup.py`, `app.py`, `loop/runner.py`, `README.md`

**Interfaces**
- Produces:
  - `daily_backup(conn, backups_dir, today, keep) -> Path|None`: 오늘 백업이 이미 있으면 None.
  - `recover_on_start(runs, dispatcher, clock, settings) -> None`
  - `enter_safe_mode(state_dir, sender) -> None`: 표식 파일은 `state/integrity_notice_sent`.
  - `Runner.register_daily`에 `daily_backup`, `prune_updates(2일)`, 로그 정리를 등록한다.
  - `app.main()`의 복구 단계(티켓 05 시작 순서의 자리)에 `recover_on_start`와 무결성 검사를 넣는다.

**Slices**

러너
- [ ] `test_backup_name_and_keeps_14`: 15일 연속 tick → 14개가 남고, 이름은 `planner-2026-10-23.db` 형식

앱 시작과 운영 산출물
- [ ] `test_log_cleanup_keeps_30_days`: 날짜별 로그 파일 31개를 만들어 두고 `register_daily`에 등록한 로그 정리 작업을 한 번 돌리면 최근 30개가 남는다(회전 자체는 표준 핸들러에 맡긴다)

디스패처
- [ ] `test_startup_marks_queued_and_running_as_interrupted`
- [ ] `test_interrupted_without_tool_events_reruns_within_limit`
- [ ] `test_crash_mid_run_no_duplicate_task`: `add_task` 뒤 크래시하고 다시 시작해도 할 일은 1개
- [ ] `test_failed_run_resent_on_start_within_reply_window`

앱 시작과 운영 산출물
- [ ] `test_integrity_failure_notifies_once_and_idles`: 손상된 DB로 `app.main()`을 두 번 시작해도 알림은 1회, 폴링은 시작하지 않는다

마무리
- [ ] **Review + Commit** `feat: backups, log retention, startup recovery, safe mode`

---

### 티켓 13: 로그온·절전·전원과 상관없이 늘 돈다

**What to build:**
- `scripts/register_task.ps1`이 상시 작업 `my-planner`를 등록한다.
  - 트리거: 로그온, 절전 복귀, 5분 워치독
  - 설정: 배터리에서도 실행, 시간 제한 없음, IgnoreNew, 1분 간격 999회 재시작, 작업 폴더는 루트
- 같은 스크립트가 깨우기 작업 `my-planner-wake`도 등록한다. 회차 시각 5분 전에 깨우고, `pythonw -c pass`만 실행한다.
- `check_tasks.ps1`이 등록된 값을 점검한다.
- 직전 tick과 지금의 차이가 3분을 넘으면 절전 복귀로 보고 텔레그램 폴링을 다시 시작한다.
- 두뇌 호출과 전송 동안은 절전을 막는다(`keep_awake`를 넣어 준다).
**Blocked by:** 12

**Files:** `scripts/*.ps1`, `scripts/*.xml.tmpl`, `src/my_planner/wake_times.py`, `loop/runner.py`, `app.py`

**Interfaces**
- Produces:
  - `python -m my_planner.wake_times`: 회차 시각보다 5분 이른 시각을 한 줄에 하나씩 `weekday HH:MM` / `weekend HH:MM` 형식으로 출력한다.
  - `register_task.ps1 [-Root E:\my-planner] [-NoWake]`
    - 템플릿의 `{{PYTHONW}}`, `{{ROOT}}`, `{{USER}}`, `{{WAKE_TRIGGERS}}`를 채운다.
    - UTF-16 LE로 저장한다.
    - `Register-ScheduledTask -Xml (Get-Content -Raw ...) -TaskName ... -Force`로 등록한다.
  - `Runner(on_resume: Callable[[], Awaitable[None]])`: tick을 시작할 때 이전 `last_seen_at`과 지금의 차이가 3분을 넘으면 부른다. 프로세스를 시작한 뒤 첫 tick에는 부르지 않는다(첫 tick은 따라잡기만). app은 `updater.stop()` 뒤 `updater.start_polling(...)`을 부른다.

**Slices**

XML 템플릿
- [ ] `test_main_task_settings`: `DisallowStartIfOnBatteries=false`, `StopIfGoingOnBatteries=false`, `ExecutionTimeLimit=PT0S`, `IgnoreNew`, `RestartOnFailure PT1M×999`, `InteractiveToken`
- [ ] `test_main_task_triggers`: Logon 1개, EventTrigger(Power-Troubleshooter ID 1), 5분 반복 TimeTrigger
- [ ] `test_main_task_working_directory_is_root`
- [ ] `test_wake_task_has_wake_to_run_battery_and_noop_action`

앱 시작과 운영 산출물
- [ ] `test_wake_times_output`: 기본 설정이면 `weekday 08:55`, `weekday 17:25`, `weekend 09:55`, `weekend 17:55`

러너
- [ ] `test_resume_detected_after_gap_calls_on_resume`, `test_first_tick_after_start_does_not_call_on_resume`

디스패처
- [ ] `test_keep_awake_held_during_brain_and_send`: 주입한 가짜 `keep_awake`가 두뇌 호출과 전송 동안만 잡혀 있다(회차와 메시지가 겹쳐도 풀림은 마지막에 한 번)

마무리
- [ ] **수동 확인** (노트북)
  1. `powershell -ExecutionPolicy Bypass -File scripts\register_task.ps1`
  2. `powershell -ExecutionPolicy Bypass -File scripts\check_tasks.ps1` → 전부 OK
  3. 로그오프/로그온, 절전/복귀, 전원 분리를 해 보고, `state/logs`에 시작·복귀 로그가 남는지 본다
- [ ] **Review + Commit** `feat: always-on via Task Scheduler`

---

### 티켓 14: 7일 수용 테스트

**What to build:** Dahun이 7일 동안 실제로 써 보면서 스펙 1장 완료 조건 1~5를 확인한다.
**Blocked by:** 10, 11, 13

- [ ] `docs/acceptance/sp1-checklist.md`를 만든다. 날짜 × 완료 조건 표와 확인용 SQL을 둔다: `SELECT loop, status, skip_reason, count(*) FROM runs WHERE scheduled_for >= ? GROUP BY 1,2,3`
- [ ] 7일 동안 매일 체크하고, 발견한 문제는 새 이슈로 남긴다.
- [ ] **Commit** `docs: SP1 acceptance results`

---

## 스펙 대비 확인 (셀프 리뷰)

스펙 1장 완료 조건
- 1 (회차가 모두 done 또는 규칙에 맞는 skipped) → 티켓 05, 07, 08, 09, 10, 그리고 14
- 2 (할 일 확정과 확인 문구) → 티켓 03, 04, 06
- 3 (다른 계정 무시) → 티켓 01
- 4 (재부팅, 절전, 전원 분리 뒤에도 동작) → 티켓 13
- 5 (원문 기록과 가리기) → 티켓 01, 04, 06
- 6 (자동 테스트 통과) → 각 티켓의 `pytest -q`

스펙 각 절
- 5.1 시작 순서와 안전 모드 → 티켓 01, 12
- 5.2 → 티켓 01, 02
- 5.3 → 티켓 01, 02, 05, 10
- 5.4 → 티켓 05, 08, 09, 10, 12
- 5.5 → 티켓 03, 04, 06, 07
- 5.6 → 티켓 04, 10, 11
- 5.7 → 티켓 06, 11
- 5.8 → 티켓 01, 04, 06
- 7장 → 티켓 01, 05, 10, 12, 13

스펙 8장 따라잡기 표 10행
- 1, 2행 → 티켓 05
- 3, 4행 → 티켓 07
- 5, 6, 7, 10행 → 티켓 09
- 8행 → 티켓 10
- 9행 → 티켓 08
