# SP14 마스터 구조 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 쓰기 경로마다 사건 한 줄(`agent_events`)을 같은 트랜잭션에 남기고, 코드 규칙으로 아래층 받은편지함(`agent_inbox`)에 넣고, 하루 끝 판단(운동메이트, 하루 1회)이 관찰 한 줄(`agent_notes`) 0~2개를 쓰고, 마스터(비서)의 아침 브리핑이 그 가운데 많아야 하나를 붙인다. 앱에서 메이트에게 말을 걸면 안 읽은 사건을 앞머리에 붙인다(즉시 판단).

**Architecture:** 사건은 도구 층의 공통 함수 `tools.activity.record_agent_event`가 쓴다(활동 기록과 같은 자리, 같은 트랜잭션, `RunContext`에서 `origin`을 안다). 받는 상대는 `harness/routing.py`의 순수 함수 `route`가 정한다. 하루 끝 판단은 디스패처 큐의 새 작업 `_DayendJob`(순간 정리 다음 차례)이고 입력·판정·정리는 `harness/dayend.py`, 즉시 판단 블록은 `harness/inbox.py`, 아침 브리핑 한 줄은 `harness/brief_notes.py`가 맡는다. 관찰 도구 `write_note`·`hand_off`는 `tools/agents.py` 믹스인이고 `RunContext.kind == "dayend"`일 때만 주어진다.

**Tech Stack:** Python 3.12, SQLite, Claude Agent SDK(하네스), aiohttp, pydantic / Next.js(pages router, 정적 PWA), vitest.

**Spec:** `docs/superpowers/specs/2026-11-01-sp14-master-hierarchy-design.md` v1.1. Dahun이 SP13~15 세 스펙을 2026-11-01에 승인했다("계속 진행해"). 15장 D1~D3은 추천값 그대로(D1 메이트 관찰은 아침 브리핑을 거쳐 옴, D2 상대마다 2개·브리핑 많아야 1개, D3 더보기 "비서 메모" 한 줄). 이하 "스펙 N.N"은 이 문서의 절. ADR 0021, ADR 0019 끝의 "덧붙임 (SP14)"(이미 있음). SP15 스펙(`2026-11-01-sp15-life-manager-panel-design.md`)이 이 계획의 산출물 위에 얹힌다: 각 Task의 Produces에 "SP15"로 표시한 것은 SP15가 그대로 쓴다.

## Global Constraints

- 시작 조건: SP13이 `develop`에 합쳐진 뒤(측정값 저장이 `measure_saved`를 남겨야 한다, 스펙 14장). 브랜치는 `origin/develop`에서, PR base는 `develop`. 마이그레이션 번호는 `023`(`023_agent_events.sql`).
- **개인 값과 사용자 글은 사건 기록·로그·테스트 고정 자료·문서에 넣지 않는다.** `agent_events`에는 종류·`ref`(id)·영역·날짜·`origin`만. 할 일 제목, 일정 제목, 메모 본문, 측정값 숫자는 사건·받은편지함·로그 어디에도 없다(스펙 1장 8, T2). 로그 `agent_dayend`에는 상대·개수·결과만.
- `origin` 값은 정확히 `app`, `telegram`, `scheduler`, `brain`, `import` 다섯(DB `CHECK`와 코드 검사 둘 다). 아이폰 단축어(`POST /body`)는 `app`.
- 사건 종류는 스펙 5.2의 18개 그대로: `task_done`, `task_postponed`, `task_added`, `task_dropped`, `event_added`, `event_changed`, `event_removed`, `memo_saved`, `habit_checked`, `condition_logged`, `body_logged`, `workout_logged`, `measure_saved`, `moment_saved`, `review_answered`, `suggestion_accepted`, `suggestion_dismissed`, `handoff`. 목록 밖은 코드가 `ValueError`로 거절한다. `suggestion_*`는 SP14에서 쓰는 자리가 없다(SP15가 쓴다).
- `ref` 모양은 SP15 근거 검사(SP15 7.2)와 맞춘다: `task:<id>`, `event:<id>`, `memo:<id>`, `habit:<id>`, `checkin:<YYYY-MM-DD>`, `body_day:<YYYY-MM-DD>`, `workout:<id>`, `measure:<id>`, `moment:<id>`, `review:<YYYY-Qn>:<영역>`, `suggestion:<id>`, `note:<id>`(넘기기). 정규식 `^[a-z_]+:[0-9A-Za-z_:-]+$` 밖이면 `ValueError`(제목이 섞이지 않게).
- 상수와 자리(값은 이대로): `EVENT_DEDUPE_S = 60`, `EVENTS_KEEP_DAYS = 90`, `INBOX_SEEN_KEEP_DAYS = 30`, `NOTES_KEEP_DAYS = 365`(`store/repos/agents.py`) · `NOTE_TEXT_MAX = 120`, `NOTES_PER_JUDGMENT = 2`, `HANDOFFS_PER_DAY = 2`, `NOTE_REFS_MAX = 5`(`tools/agents.py`) · `DAYEND_LOOKBACK_DAYS = 7`, `DAYEND_MAX_TURNS = 3`, `DAYEND_MAX_ATTEMPTS = 2`, `DAYEND_EVENTS_MAX = 100`, `DAYEND_PAST_NOTES = 3`(`harness/dayend.py`) · `INBOX_BLOCK_MAX = 30`, `INBOX_WINDOW_DAYS = 7`(`harness/inbox.py`) · `BRIEF_NOTE_DAYS = 2`(`harness/brief_notes.py`). 사용자 몫은 기존 `moments.MOMENTS_RESERVE_CALLS = 10`을 그대로 쓴다.
- 두뇌 호출 수: 하루 끝 판단은 상대마다 하루 1회. SP14의 `DAYEND_AGENTS = ("mate",)`라 하루 합계 1회(SP15가 `"manager"`를 더해 2회). 모든 호출은 `_call_brain`을 지나 `daily_brain_calls`에 센다. 열기만(`GET /agents/{agent}/inbox/count`)은 두뇌를 부르지 않는다.
- 아래층 상대는 먼저 말하지 않는다: 하루 끝 판단은 원문 기록·알림·푸시·텔레그램·`runs` 어디에도 쓰지 않는다. 사용자에게 가는 길은 아침 브리핑 한 줄뿐이다(스펙 1장 4, T13).
- 관찰 문구 금지: `tools.ui.banned_words()`(정본 `system.md` 블록 + `연속`·`스트릭`·`달성률`) + `NOTE_EXTRA_BANNED = ("%", "못 했", "못했")`(ADR 0006).
- 상대 이름(사용자에게 보이는 접두어): `AGENT_LABELS = {"mate": "운동메이트", "manager": "라이프 매니저"}`. 브리핑 줄 모양 `"{이름}: {관찰}"`.
- 파일 읽기는 늘 `encoding="utf-8"`.
- BE 검사: `.venv/bin/python -m pytest -q`(약 7분), `.venv/bin/ruff check src tests`(이 저장소에 mypy는 없다). 앱: `cd web/app && PATH=/opt/node22/bin:$PATH npm test && npm run typecheck && npm run lint:copy && npm run size`. 타입은 `npm run gen:types`(앱·대시보드 각 폴더, PowerShell `>` 리다이렉트 쓰지 않음).
- **모든 Task의 Step 2 기대 출력**: 새 테스트가 `ImportError`/`ModuleNotFoundError`/`AttributeError` 또는 `AssertionError`로 FAIL(그 밖의 오류면 테스트부터 고친다). **모든 Task의 마지막 검사**: 그 Task의 테스트 파일 PASS, 그 뒤 `.venv/bin/python -m pytest -q`와 `.venv/bin/ruff check src tests`가 종료 코드 0.
- 텔레그램 화면과 대시보드 화면은 바꾸지 않는다(대시보드는 픽토그램·스키마 생성 파일의 기계적 동기화만, Task 8·9).

## Review Focus

1. **앱의 빠른 토글**(습관 체크 → 취소 → 다시 체크를 10초 안에): 사건은 하나뿐이고 받은 쪽이 원문을 읽으면 지금 상태(체크됨)가 보인다. 61초 뒤 다시 체크하면 둘. Task 2 `test_quick_toggle_is_one_event`.
2. **노트북이 아침에야 켜짐**(하루 경계 뒤 첫 tick에 아침 브리핑 회차와 하루 끝 판단이 함께 큐에 든다): 회차(차례 1)가 판단(차례 3)보다 먼저 돌아 그날 브리핑에는 관찰이 없다. 관찰은 지워지지 않고 다음 날 브리핑 후보로 남는다(2일 창). Task 6 `test_note_judged_after_brief_shows_next_morning`.
3. **두뇌가 관찰 줄을 살짝 바꿔 씀**(띄어쓰기, 앞 이름 생략): 하네스는 관찰 본문을 공백 정규화해 찾고, 못 찾은 `priority` 2 줄은 보인 것으로 표시하지 않는다(다음 날 다시 후보). `priority` 1은 찾지 못하면 그대로 덧붙여 두 번 나오지 않게 한다. Task 6 `test_brief_match_ignores_spacing_and_label`.
4. **사건 쓰기가 실패하면 원래 쓰기도 없다**(같은 트랜잭션): 사건 줄 쓰기에서 예외가 나면 할 일 완료도 되돌아간다. 반대로 나중 단계(경험치) 예외면 사건도 없다. Task 2 `test_rollback_leaves_no_event`, `test_event_failure_rolls_back_write`.
5. **메이트 대화 중 두뇌 실패**(재시도까지 모두 `error`): 붙였던 사건은 `seen_at`이 비어 있고 다음 메시지·하루 끝 판단에 다시 나온다. 멈추기(stop)로 끝난 차례도 같다. Task 5 `test_instant_block_not_marked_on_failure`, `test_instant_block_not_marked_on_stop`.

---

### Task 1: 마이그레이션 023, 도메인 이름, `AgentsRepo`, 라우팅, 쓰기 경로 감시 준비 (SP14-01)

**Files:**
- Create: `src/my_planner/store/migrations/023_agent_events.sql`
- Create: `src/my_planner/store/repos/agents.py`
- Create: `src/my_planner/harness/routing.py`
- Modify: `src/my_planner/domain.py`, `src/my_planner/standing/metrics.py`
- Modify: `tests/test_write_paths.py`(스펙 5.2 "먼저 더하고 시작"), `tests/test_migrations.py`의 최신 버전 숫자 22 → 23(`test_latest_version_no_chat_migration`, `test_schema_version_latest`, 017 훅 시험의 `migrate(conn) == 22`)
- Test: `tests/test_migrations.py`(더함), `tests/test_agent_events.py`(새)

**Interfaces:**
- Produces:
  - SQL: 스펙 5.1의 세 표와 두 인덱스 그대로(훅 없음).
  - `domain.py`:
    - `EventKind = Literal[...]`(Global Constraints의 18개), `EVENT_KINDS: tuple[str, ...]`(같은 순서)
    - `EventOrigin = Literal["app", "telegram", "scheduler", "brain", "import"]`, `EVENT_ORIGINS: tuple[str, ...]`
    - `InboxAgent = Literal["mate", "manager"]`, `INBOX_AGENTS: tuple[InboxAgent, ...] = ("mate", "manager")` (SP15가 쓴다. `Agent`는 SP15가 늘린다)
    - `RunKind`에 `"dayend"` 추가
    - `RunContext` 새 칸: `in_brain: bool = False`(두뇌 호출 안의 도구 호출, Task 2), `dayend_day: date | None = None`(판단하는 날, Task 3), `notes_written: int = 0`(이 호출에서 저장한 관찰 수, Task 3)
  - `standing/metrics.py`:
    - `HEALTH_LOOKS_METRICS: frozenset[str]` = `weight_kg`, `body_fat_pct`, `fat_free_mass_kg`, `skeletal_muscle_kg`, `waist_cm`, `face_rating`, `grooming_rating`, `bp_sys`, `bp_dia`, `fasting_glucose`, `ldl`, `alt`, `checkup_flag`, `shuttle_run_laps`, `grip_rel_pct`, `situp_per_min`, `run_6k_min`, `squat_1rm_kg`, `bench_1rm_kg`, `deadlift_1rm_kg`, `smoking`, `drinking`, `exercise_days_week`(23개)
    - `metric_area(metric: str) -> str | None`: 위 23개 → `"health"`; `salary_krw`, `company_tier`, `role_points`, `years_exp`, `level_points`, `outside_activity_count`, `recruiter_contacts_6m`, `offer_ratio` → `"career"`; `net_worth_krw`, `monthly_saving_krw`, `monthly_net_income_krw`, `savings_rate_pct` → `"finance"`; `support_people`, `monthly_meetups`, `dating_status`, `lonely_often` → `"relationships"`; `cert` → `"learning"`; 그 밖(`profile_*`, `height_cm`, `education_tier`, `double_major`, `family_*`) → `None`
  - `harness/routing.py`: `route(kind: EventKind, area: str | None, *, handoff_to: InboxAgent | None = None) -> tuple[InboxAgent, ...]` — 스펙 5.3 표 그대로, 튜플 순서는 늘 `("mate", "manager")`. "건강·외모 지표"는 `area == "health"`로 본다(`metric_area`). `handoff` → `(handoff_to,)`. `handoff_to`가 없거나 `handoff`가 아닌데 주면 `ValueError`
  - `store/repos/agents.py`(쓰기는 부르는 쪽 `transaction`, `WorkoutRepo`와 같은 방식):
    - `@dataclass(frozen=True) AgentEvent(id: int, occurred_at: datetime, day: date, kind: str, ref: str, area: str | None, origin: str)`
    - `@dataclass(frozen=True) AgentNote(id: int, agent: str, day: date, text: str, priority: int, refs: tuple[str, ...], shown_at: datetime | None, created_at: datetime)`
    - `class AgentsRepo(conn, clock)`:
      - `add_event(kind: str, ref: str, area: str | None, origin: str, day: date, *, to: tuple[str, ...], now: datetime, seen_by: str | None = None) -> int | None` — `kind`·`origin`·`ref` 검사(`ValueError`). 같은 `kind`·`ref`의 줄이 `occurred_at >= now − 60초`면 쓰지 않고 `None`. 아니면 사건 한 줄 + `to`마다 받은편지함 한 줄. `seen_by`가 `to`에 있으면 그 상대의 줄은 `seen_at = now`로 쓴다(자기 대화에서 생긴 사건, Task 2).
      - `events_since(kinds: Iterable[str], since: date) -> list[AgentEvent]` — 읽음 표시와 상관없이 `day >= since`인 그 종류들, 오래된 것부터. **SP15**의 코드 단계(패널 제안 상태 갱신이 `task_done`·`task_postponed`를 본다)가 쓴다.
      - `unseen(agent: str, since: date, limit: int | None = None) -> list[AgentEvent]` — `seen_at IS NULL`, 사건 `day >= since`, 최신 먼저(`occurred_at`, `id` 내림차순)
      - `unseen_count(agent: str, since: date) -> int`
      - `mark_seen(agent: str, event_ids: Iterable[int], now: datetime) -> int`
      - `mark_seen_before(agent: str, day: date, now: datetime) -> int` — 안 읽은 줄 가운데 사건 `day < day`(SP15가 켜는 날도 같은 규칙, 스펙 5.5)
      - `add_note(agent: str, day: date, text: str, priority: int, refs: list[str], now: datetime) -> int`
      - `notes(agent: str | None, since_day: date, limit: int | None = None) -> list[AgentNote]` — `day >= since_day`, 최신 먼저(`day`, `id` 내림차순)
      - `handoffs_on(agent: str, day: date) -> int` — 그 상대·그 날 `priority = 3` 줄 수
      - `brief_candidates(today: date) -> list[AgentNote]` — `shown_at IS NULL`, `priority IN (1, 2)`, `day >= today − 2일`, `priority`, `created_at`, `id` 오름차순
      - `mark_shown(ids: Iterable[int], now: datetime) -> int`
      - `prune(today: date, now: datetime) -> dict[str, int]` — `{"events": n, "inbox": n, "notes": n}`: 사건 `day < today − 90일`(받은편지함 줄은 CASCADE), 본 받은편지함 `seen_at < now − 30일`, 관찰 `day < today − 365일`

- [ ] **Step 1: 실패하는 테스트**
  - `test_migrations.py::test_023_agent_tables`: 표 셋. `origin='bogus'` 사건 INSERT → `IntegrityError`(T14). `agent='secretary'` 받은편지함 → `IntegrityError`. `text` 121자 관찰 → `IntegrityError`. `priority` 0·4 → `IntegrityError`. 사건을 지우면 받은편지함 줄도 없어진다(`foreign_keys=ON`).
  - `test_agent_events.py::test_route_table`(T3): 18개 종류 전부를 표로 — 예 `route("workout_logged", "health") == ("mate", "manager")`, `route("measure_saved", "health") == ("mate", "manager")`, `route("measure_saved", "finance") == ("manager",)`, `route("measure_saved", None) == ("manager",)`, `route("memo_saved", None) == ("manager",)`, `route("handoff", None, handoff_to="mate") == ("mate",)`, `route("handoff", None)`은 `ValueError`.
  - `test_agent_events.py::test_add_event_validates`(T14): 목록 밖 `kind`, `origin="bogus"`, `ref="task:장보기"`(한글) 셋 다 `ValueError`, 쓴 줄 0.
  - `test_agent_events.py::test_dedupe_within_60s`(T4): 12:00:00 `("habit_checked", "habit:3")` → id. 12:00:59 같은 것 → `None`, 사건 1줄. 12:01:01 → 새 id. 다른 `ref`는 59초 안이어도 새 줄.
  - `test_agent_events.py::test_seen_by_and_events_since`: `add_event(..., to=("mate", "manager"), seen_by="mate")` → `unseen_count("mate", …) == 0`, `manager`는 1. `mark_seen` 뒤에도 `events_since(["workout_logged"], since)`가 그 줄을 준다. 다른 종류는 빠진다.
  - `test_agent_events.py::test_unseen_window_and_mark`: 날짜 `today−8`, `today−7`, `today−1` 사건 → `unseen("mate", today−7)`은 뒤 둘(최신 먼저). `mark_seen_before("mate", today−7, now)` == 1. `mark_seen` 뒤 `unseen_count == 0`, 다른 상대 줄은 그대로.
  - `test_agent_events.py::test_brief_candidates_two_day_window`: 관찰 `(day=today−1, p2)`, `(today−2, p1)`, `(today−3, p2)`, `(today−1, p3)`, `(today−1, p2, shown)` → 후보는 앞 둘, 순서 `[p1, p2]`.
  - `test_agent_events.py::test_prune_keeps_90_30_365`(T9): 사건 `day = today−91`은 지움, `today−90`은 남김. 본 받은편지함 `seen_at = now−31일`은 지움, `now−29일`은 남김, 안 읽은 줄은 남김(사건이 남는 동안). 관찰 `day = today−366`은 지움, `today−365`는 남김. 돌려준 개수가 맞다.
  - `test_agent_events.py::test_metric_area`: `metric_area("body_fat_pct") == "health"`, `"salary_krw"` → `"career"`, `"net_worth_krw"` → `"finance"`, `"cert"` → `"learning"`, `"height_cm"` → `None`. `HEALTH_LOOKS_METRICS <= set(METRICS)`이고 23개.
- [ ] **Step 2:** `.venv/bin/python -m pytest tests/test_migrations.py tests/test_agent_events.py -q` → FAIL.
- [ ] **Step 3:** SQL, `domain.py` 이름, `metrics.py`의 두 이름, `routing.py`, `AgentsRepo` 구현. 시각 저장은 `clock.to_iso`, `refs_json`은 `json.dumps(refs, ensure_ascii=False)`.
- [ ] **Step 4:** `tests/test_write_paths.py`를 먼저 넓힌다(아직 쓰는 코드가 없어도 통과해야 한다):
  - `TOOLS`에 `"my_planner.tools.workout"`, `"my_planner.tools.agents"`(Task 3에서 생김).
  - 상수 `DAYEND_JOB = "my_planner.harness.dayend"`, `IMPORTER = "my_planner.standing.importer"`.
  - `ALLOWED`에 `body_notes`, `workout_plans`, `workout_plan_sessions`, `workout_logs`, `workout_log_items`: `set(TOOLS)`; `agent_events`: `{*TOOLS, IMPORTER, DAYEND_JOB}`(90일 정리는 하루 끝 작업); `agent_inbox`: `{*TOOLS, DISPATCHER, DAYEND_JOB, IMPORTER}`(읽음 표시는 디스패처·하루 끝 작업, 정리는 하루 끝 작업); `agent_notes`: `{*TOOLS, DISPATCHER, DAYEND_JOB}`(쓰기는 `tools.agents`, `shown_at`은 디스패처, 정리는 하루 끝 작업); `app_state`에 `DAYEND_JOB`(`agent_dayend_day:*`, `agent_dayend_attempts:*`). SP13의 `standing_*`는 이미 있다.
  - 모듈 docstring의 도구 모듈 목록에 운동(`tools/workout.py`)과 관찰(`tools/agents.py`)을 더한다.
- [ ] **Step 5:** 같은 명령 PASS, 그 뒤 전체 PASS·ruff 0.
- [ ] **Step 6:** `git commit -m "feat(sp14): 023 사건 기록·받은편지함·관찰 표와 라우팅"`

### Task 2: 쓰기 경로마다 사건 한 줄 (SP14-02)

**Files:**
- Modify: `src/my_planner/tools/activity.py`(공통 함수 둘), `src/my_planner/tools/core.py`(`Tools(agents=...)`, `_agent_event`, 할 일·컨디션·회고 자리), `src/my_planner/tools/events.py`, `src/my_planner/tools/memos.py`, `src/my_planner/tools/habits.py`, `src/my_planner/tools/body.py`, `src/my_planner/tools/workout.py`, `src/my_planner/tools/standing.py`, `src/my_planner/tools/moments.py`, `src/my_planner/standing/importer.py`, `src/my_planner/harness/dispatcher.py`(`_call_brain`이 `run_ctx.in_brain = True`), `src/my_planner/app.py`(`AgentsRepo(conn, clock)`를 `Tools(agents=...)`에)
- Test: `tests/test_agent_event_writes.py`(새), `tests/test_standing_import.py`(더함), `tests/test_write_paths.py`(단언 더함)

**Interfaces:**
- Consumes: Task 1 `AgentsRepo.add_event`, `route`, `metric_area`, `EventKind`, `EventOrigin`, `RunContext.in_brain`.
- Produces:
  - `tools/activity.py`:
    - `event_origin(ctx: RunContext) -> EventOrigin`: `ctx.in_brain`이면 `"brain"`; 아니면 `activity_origin(ctx)`의 통로(`app`·`telegram`·`scheduler`).
    - `record_agent_event(repo: AgentsRepo | None, ctx: RunContext, kind: EventKind, ref: str, area: str | None, *, day: date, now: datetime, handoff_to: InboxAgent | None = None) -> int | None` — 저장소가 없으면(SP1 시험) `None`. `to = route(kind, area, handoff_to=handoff_to)`. `ctx.kind == "chat"`이고 `ctx.agent`가 `INBOX_AGENTS`에 있으면 `seen_by=ctx.agent`(그 상대가 자기 대화에서 쓴 사건은 그 상대에게는 이미 본 것. 다른 상대에게는 안 읽은 것). 트랜잭션 안에서 부른다. **SP15**의 `accept_suggestion`·`dismiss_suggestion`이 이것을 부른다.
  - `Tools.__init__(..., agents: AgentsRepo | None = None)`, `self.agents`. 믹스인이 쓰는 `Tools._agent_event(ctx, kind, ref, area=None, *, handoff_to=None) -> None`(`day=self.today()`, `now=self.clock.now()`).
  - `Dispatcher._call_brain`: `self.brain.run` 앞에서 `run_ctx.in_brain = True`.
  - 쓰는 자리(모두 이미 열린 트랜잭션 안, 활동 기록 옆):

| 자리 | 조건 | `kind` | `ref` | `area` |
|---|---|---|---|---|
| `core._finish`(`task_added`) | 늘 | `task_added` | `task:<id>` | 첫 영역(`t.areas[0]`, 없으면 None) |
| `core.confirm_tasks` | 확정된 할 일마다 | `task_added` | `task:<id>` | 첫 영역 |
| `core._set_status` | 새 상태 `done` | `task_done` | `task:<id>` | 첫 영역 |
| `core._set_status` | 새 상태 `dropped`이고 전 상태 `open`(초안 빼기·만료는 없음) | `task_dropped` | `task:<id>` | 첫 영역 |
| `core.move_task` | 전 `planned_for`가 있고 새 날짜가 그보다 늦음(앞당김·날짜 지움은 없음) | `task_postponed` | `task:<id>` | 첫 영역 |
| `core.record_condition` | 늘 | `condition_logged` | `checkin:<날짜>` | None |
| `core.record_area_scores` | 기록한 영역마다 | `review_answered` | `review:<분기>:<영역>` | 그 영역 |
| `events._event_change` | `event_created` / `event_updated`·`event_skipped`·`event_repeat_ended` / `event_deleted` | `event_added` / `event_changed` / `event_removed` | `event:<id>` | None |
| `memos._memo_change` | `memo_created`, `memo_updated`(고정·지우기는 없음) | `memo_saved` | `memo:<id>` | None |
| `habits.check_habit` | 체크했을 때(취소는 없음) | `habit_checked` | `habit:<id>` | 습관 영역 |
| `body.record_body_days` | 날마다, 그 날 행이 새로 생겼거나 값(걸음·잠)이 바뀌었을 때만(단축어는 매번 지난 며칠을 다시 보낸다) | `body_logged` | `body_day:<날짜>` | `"health"` |
| `workout.log_workout`, `workout.update_workout_log` | 늘 | `workout_logged` | `workout:<id>` | `"health"` |
| `standing.save_measures` | 저장한 줄마다 | `measure_saved` | `measure:<id>` | `metric_area(metric)` |
| `moments.save_moments` | 저장한 순간마다 | `moment_saved` | `moment:<id>` | 순간의 영역 |
| `standing/importer.run_import` | 저장한 줄마다(`dry_run` 아님) | `measure_saved`, `origin="import"` | `measure:<id>` | `metric_area(metric)` |

  - 되돌리기(`tools/activity.py`의 undo)는 사건을 지우지 않고 반대 사건도 남기지 않는다(스펙 5.2). 지금 코드 그대로 두면 된다.
  - 가져오기는 `RunContext`가 없으므로 `AgentsRepo(conn, clock).add_event(..., origin="import", to=route(...))`를 직접 부른다(같은 트랜잭션).

- [ ] **Step 1: 실패하는 테스트**(`tests/test_agent_event_writes.py`, 저장소는 `tmp_path` DB + `migrate`, 시계는 `FakeClock`)
  - `test_write_path_leaves_one_event`(T1, `pytest.mark.parametrize` 19가지: `add_task`, `confirm_tasks`, `complete_task`, `drop_task`(열린 것), `move_task`(늦춤), `record_condition`, `record_area_scores`, `create_event`, `update_event`, `delete_event`(`all`), `delete_event`(`one` → 건너뜀), `create_memo`, `update_memo`, `check_habit`, `record_body_days`, `log_workout`, `update_workout_log`, `save_measures`, `save_moments`): 위 표의 자리마다(`suggestion_*`·`handoff` 뺌, `handoff`는 Task 3) 도구를 한 번 부르면 `agent_events`가 정확히 한 줄 늘고(여러 줄 자리는 그 개수) `kind`·`ref`·`area`가 표와 같다. 예: `add_task(title="가짜 할 일", areas=["career"])` → `("task_added", "task:1", "career")`; `move_task(1, 더 늦은 날)` → `task_postponed`; `move_task(1, 더 이른 날)` → 사건 없음; `drop_task`(초안) → 사건 없음; `save_measures` 두 줄(`body_fat_pct`, `net_worth_krw`) → 두 사건, 받은편지함은 첫 줄만 `mate`에도.
  - `test_body_days_event_only_on_change`: 같은 날 같은 값을 두 번(61초 간격) → `body_logged` 1줄, 걸음이 바뀐 세 번째 → 2줄.
  - `test_own_chat_event_seen_for_self`: 메이트 대화(`RunContext(kind="chat", agent="mate", in_brain=True)`)의 `log_workout` → `mate` 받은편지함 줄은 `seen_at` 있음, `manager` 줄은 없음. 비서 대화의 `add_task`는 `manager`에 안 읽은 줄.
  - `test_events_routed_to_inbox`(T3): `log_workout` 뒤 `agent_inbox`에 `mate`·`manager` 두 줄, `create_memo` 뒤 `manager` 한 줄.
  - `test_rollback_leaves_no_event`(T1): `complete_task` 안의 `_grant`를 `RuntimeError`로 바꿔(monkeypatch) 부르면 예외, 할 일은 `open`, `agent_events` 0줄.
  - `test_event_failure_rolls_back_write`: `AgentsRepo.add_event`를 예외로 바꾸고 `add_task` → 할 일 0개.
  - `test_events_have_ref_only_no_titles`(T2): 제목 `"비밀제목XYZ"` 할 일, 본문 `"비밀본문XYZ"` 메모, 제목 `"비밀일정XYZ"` 일정을 만들고 `caplog`(DEBUG)로 잡는다 → `agent_events`·`agent_inbox` 모든 칸을 이은 글과 로그 글 전부에 세 문자열이 없다.
  - `test_quick_toggle_is_one_event`(T4, Review Focus 1): 습관 체크 → 취소 → 10초 뒤 체크 → `habit_checked` 1줄. 61초 뒤 다시 취소·체크 → 2줄.
  - `test_origin_by_path`(T14): 즉시 갈래 `/actions`(앱, `actor="user"`, `channel="app"`) → `app`; 텔레그램 버튼(`channel="telegram"`) → `telegram`; `RunContext(..., in_brain=True)` → `brain`; `RunContext(actor="secretary", activity_channel="scheduler")` → `scheduler`; `apply_action(ActionRequest("record_body_days", ..., actor="user", channel="app", endpoint="body"))`(단축어 경로) → `app`.
  - `test_undo_keeps_event`: `complete_task` → 되돌리기 → 사건 1줄 그대로, 새 사건 없음.
  - `test_standing_import.py::test_import_leaves_measure_events`: 고정 자료 가져오기 → `measure_saved` 줄 수 = 가져온 줄 수, 모두 `origin = "import"`. `--dry-run`은 0줄. 두 번째 가져오기(모두 건너뜀)도 0줄 더함.
- [ ] **Step 2:** `.venv/bin/python -m pytest tests/test_agent_event_writes.py tests/test_standing_import.py -q` → FAIL.
- [ ] **Step 3:** 표의 자리마다 구현. `app.py`에서 `agents = AgentsRepo(conn, clock)`를 만들어 `Tools(..., agents=agents)`에, 이후 Task가 쓰도록 `BeParts`에도 싣는다(`parts.agents`).
- [ ] **Step 4:** `tests/test_write_paths.py::test_each_table_written_only_by_its_path`에 단언 더함: `("agent_events", "my_planner.tools.activity", "my_planner.api.actions", True) in rec.tool_calls`, `("agent_inbox", "my_planner.tools.activity") in rec.seen`. PASS, 전체 PASS·ruff 0.
- [ ] **Step 5:** `git commit -m "feat(sp14): 쓰기 경로마다 사건 기록과 받은편지함"`

### Task 3: 관찰 도구 `write_note`·`hand_off`, 측정값 읽기, 도구 목록, `agent_dayend.md` (SP14-03)

**Files:**
- Create: `src/my_planner/tools/agents.py`(`AgentTools` 믹스인), `src/my_planner/harness/prompts/agent_dayend.md`
- Modify: `src/my_planner/tools/core.py`(믹스인 더함), `src/my_planner/tools/standing.py`(`get_measures`), `src/my_planner/tools/mcp_adapter.py`(`MATE_TOOLS`, `DAYEND_READ_TOOLS`, `DAYEND_TOOLS`, `tool_names_for`, 설명·스키마), `docs/adr/0019-workout-mate-is-a-second-agent-in-be.md`("덧붙임 (SP14)" 끝에 한 줄: "하루 끝 판단 때는 일정 읽기(`list_events`, 읽기만)도 받는다. `get_mate_context`의 오늘 일정만으로는 이번 주 운동할 시간을 판단할 수 없어서다.")
- Test: `tests/test_agent_tools.py`(새), `tests/test_mate_prompts.py`(`test_mate_tool_list` 고침), `tests/test_prompts.py`(더함)

**Interfaces:**
- Consumes: Task 1 `AgentsRepo.add_note`·`handoffs_on`, `INBOX_AGENTS`, `HEALTH_LOOKS_METRICS`; Task 2 `Tools._agent_event`.
- Produces:
  - `mcp_adapter.py`:
    - `MATE_TOOLS`의 `"list_workouts"` 바로 다음(9번째, 인덱스 8)에 `"get_measures"`(ADR 0019 덧붙임과 같다). 메이트 전용 도구가 앞 9개가 된다.
    - `DAYEND_READ_TOOLS: dict[InboxAgent, list[str]] = {"mate": ["get_mate_context", "list_workouts", "get_measures", "list_events", "find_conversations"]}` (**SP15**가 `"manager"` 줄을 더한다)
    - `DAYEND_TOOLS: list[str] = ["write_note", "hand_off"]`
    - `tool_names_for(ctx)`: `ctx.kind == "dayend"`이면 `[*DAYEND_READ_TOOLS[ctx.agent], *DAYEND_TOOLS]`(순간 분기 바로 다음, 상대 분기보다 먼저). `write_note`·`hand_off`는 `TOOL_NAMES`·`APP_ONLY_TOOLS`·`MATE_TOOLS` 어디에도 없다.
  - `StandingTools.get_measures(ctx) -> dict[str, Any]` → `{"measures": [{"metric", "label", "value", "unit", "measured_on", "reliability"}]}`: `StandingRepo.latest()`에서 `HEALTH_LOOKS_METRICS`만, `METRICS` 순서. 저장소가 없으면 `{"measures": []}`. 로그 없음. 설명: "건강·외모 측정값(체성분, 혈압·혈당 같은 검진 수치, 체력 기록)의 지표마다 가장 최근 값을 읽습니다. 읽기만 합니다."
  - `AgentTools.write_note(ctx, text=None, priority=None, refs=None) -> dict[str, Any]`: `ctx.kind == "dayend"`이 아니면 거절. 검사 순서와 오류 문구(이대로):
    - `ctx.notes_written >= 2` → `"관찰은 한 번에 2개까지예요."`
    - `text`: 앞뒤 공백 뺀 1~120자, 줄바꿈 없음 → 아니면 `"관찰은 120자 안의 한 줄이에요."`
    - 금지어(`banned_words()` + `NOTE_EXTRA_BANNED`)가 들어 있으면 `"관찰에 쓰지 않는 말이 있어요: {말}"`
    - `priority`가 1 또는 2가 아니면 `"priority는 1(꼭 알림) 또는 2예요."`(3은 넘기기 몫)
    - `refs`: `^[a-z_]+:[0-9A-Za-z_:-]+$` 모양 1~5개 → 아니면 `"refs는 근거 참조(예: workout:12) 1~5개예요."`
    - 맞으면 트랜잭션에 `add_note(ctx.agent, ctx.dayend_day, text, priority, refs, now)`, `ctx.notes_written += 1`, `ToolEvent("note_written", None, {"id": id})`(글 없음), 결과 `{"ok": True, "id": id}`. 로그는 `note_written`(`agent`, `priority`만).
  - `AgentTools.hand_off(ctx, to=None, text=None, refs=None) -> dict[str, Any]`: `ctx.kind == "dayend"`만. `to`가 `INBOX_AGENTS`에 없거나 `ctx.agent`와 같으면 `"넘길 상대는 mate 또는 manager이고, 자기 자신에게는 넘기지 않아요."`. `text`·`refs`는 `write_note`와 같은 검사. `handoffs_on(ctx.agent, ctx.dayend_day) >= 2`면 `"넘기기는 하루 2번까지예요."`. 맞으면 한 트랜잭션에 `add_note(..., priority=3, ...)` + `_agent_event(ctx, "handoff", f"note:{id}", None, handoff_to=to)`. `notes_written`은 늘리지 않는다. 결과 `{"ok": True, "id": id}`.
  - `agent_dayend.md`(문구는 이대로):
    ```
    ## 하루 끝 판단
    지금은 대화가 아닙니다. 하루 끝에 받은편지함을 보고 관찰 한 줄을 남기는 시간입니다. 아무에게도 말을 걸지 않습니다.

    - 아래 `## 새로 생긴 것`은 무엇이 생겼는지(종류, 참조, 영역, 날짜)만 알려 줍니다. 내용은 읽기 도구로 원문을 직접 읽습니다.
    - 관찰이 있으면 `write_note`로 남깁니다. 많아야 2개이고, 없으면 아무것도 쓰지 않아도 됩니다.
    - 관찰은 120자 안의 한 줄이고 판단과 근거가 함께 있습니다. 예: "이번 주 저녁 일정 5개, 운동 가능한 날은 토요일뿐이에요."
    - `priority` 1은 건강이나 돈의 위험처럼 꼭 알려야 할 때만 쓰고, 그 밖은 2입니다.
    - `refs`에는 근거로 본 참조(`workout:12`, `event:7` 같은 것)를 넣습니다.
    - 비율(%)이나 이어서 한 날 수를 말하지 않고, 하지 않은 것을 탓하지 않습니다.
    - 다른 상대가 알아야 할 것이 있으면 `hand_off`로 넘깁니다(하루 2번까지).
    - 기록을 바꾸는 도구는 없습니다. 플랜과 기록은 그대로 둡니다.
    ```

- [ ] **Step 1: 실패하는 테스트**(`tests/test_agent_tools.py`)
  - `test_dayend_tools_are_read_only`(T6): `tool_names_for(RunContext(None, None, kind="dayend", agent="mate")) == ["get_mate_context", "list_workouts", "get_measures", "list_events", "find_conversations", "write_note", "hand_off"]`. 이 목록은 메이트 쓰기 도구 `{"save_body_note", "drop_body_note", "set_workout_plan", "log_workout", "update_workout_log", "delete_workout_log", "record_condition"}`, `TOOL_NAMES` 전부, `set(APP_ONLY_TOOLS) - {"find_conversations", "list_events"}`와 겹치지 않는다. 판단 호출에서 `list_events`가 이번 주 일정을 돌려준다(시험 일정 하나, 7일 범위).
  - `test_note_tools_only_in_dayend`: `"write_note"`·`"hand_off"`가 `tool_names_for`의 메이트 대화(`agent="mate"`, `channel="app"`)·비서 앱·텔레그램·`moments` 목록에 없다. `kind="chat"`으로 `write_note`를 직접 부르면 오류, 관찰 0줄.
  - `test_write_note_third_call_rejected`(T12): 맞는 호출 둘 → `ok`, 셋째 → `{"error": "관찰은 한 번에 2개까지예요."}`, 관찰 2줄. 틀린 호출(121자)은 세지 않는다(그 뒤 맞는 호출이 둘째로 저장된다).
  - `test_note_rejects_banned_and_shape`(T11, 매개변수): `"오늘 운동 실패예요."`, `"이번 주 연속 3일 했어요."`, `"걸음이 50% 줄었어요."`, `"어제 못 했어요."`, 121자, 두 줄 글 → 모두 오류, 관찰 0줄. `priority=3`·`refs=[]`·`refs=["장보기"]`도 오류.
  - `test_hand_off_cap_and_inbox`(T10): `hand_off(to="manager", text="체지방 목표를 루틴에 반영할 거리가 있어요.", refs=["workout:1"])` 두 번 → `ok`, 셋째 → `"넘기기는 하루 2번까지예요."`. `manager` 받은편지함에 `handoff` 사건 2줄(`ref = note:<id>`), `mate` 받은편지함에는 없음. 관찰은 `priority` 3이고 `brief_candidates`에 없다. `to="mate"`(자기 자신)는 오류.
  - `test_get_measures_health_looks_only`: `body_fat_pct`(두 날짜)와 `salary_krw` 저장 → `get_measures` 결과는 `body_fat_pct` 하나(나중 날짜 값), `salary_krw` 없음. `MATE_TOOLS.index("get_measures") == MATE_TOOLS.index("list_workouts") + 1 == 8`.
  - `test_mate_prompts.py::test_mate_tool_list`: 기대 목록의 `"list_workouts"` 다음에 `"get_measures"`, 그리고 81~82줄의 자르기를 `MATE_TOOLS[:9]`(메이트 전용, 비서 목록과 겹치지 않음)·`MATE_TOOLS[9:]`(비서 목록에도 있음)로.
  - `test_prompts.py::test_agent_dayend_prompt_has_no_banned_words`(T11): `agent_dayend.md`가 있고 `banned_words()` 어느 말도 없다. 첫 줄이 `## 하루 끝 판단`.
- [ ] **Step 2:** `.venv/bin/python -m pytest tests/test_agent_tools.py tests/test_mate_prompts.py tests/test_prompts.py -q` → FAIL.
- [ ] **Step 3:** 구현. `_SPECS`에 세 도구의 설명·스키마(`write_note`: `text` string ≤120, `priority` enum [1, 2], `refs` array 1~5; `hand_off`: `to` enum `["mate", "manager"]`, `text`, `refs`; `get_measures`: 인자 없음).
- [ ] **Step 4:** PASS, 전체 PASS·ruff 0.
- [ ] **Step 5:** `git commit -m "feat(sp14): write_note·hand_off·get_measures와 하루 끝 판단 도구 목록"`

### Task 4: 하루 끝 판단 작업 (SP14-04)

**Files:**
- Create: `src/my_planner/harness/dayend.py`, `src/my_planner/harness/inbox.py`(`event_line`만)
- Modify: `src/my_planner/harness/dispatcher.py`(`_DayendJob`, `_PRIORITY_DAYEND`, `submit_dayend`, `_process`, `_handle_dayend`, `_call_brain`의 조용한 종류), `src/my_planner/loop/runner.py`(`queue_dayend_daily`), `src/my_planner/app.py`(등록)
- Test: `tests/test_dayend_job.py`(새)

**Interfaces:**
- Consumes: Task 1 `AgentsRepo.unseen`·`mark_seen`·`mark_seen_before`·`notes`·`prune`; Task 3 `DAYEND_TOOLS`, `RunContext.notes_written`; `harness.moments.remove_session_file`, `MOMENTS_RESERVE_CALLS`; `Dispatcher._moments_blocked()`(사용자 몫·로그인·사용 한도 대기를 같은 규칙으로 본다).
- Produces:
  - `harness/dayend.py`:
    - `DAYEND_AGENTS: tuple[InboxAgent, ...] = ("mate",)`, `DAYEND_PROMPTS: dict[InboxAgent, str] = {"mate": "mate.md"}` (**SP15**가 `"manager": "manager.md"`와 함께 늘린다)
    - `CodeStep = Callable[[sqlite3.Connection, Clock, date], None]`, `DAYEND_CODE_STEPS: list[CodeStep] = []` — 두뇌 없는 코드 단계. **SP15**가 패널 제안 상태 갱신·예측 맞춰 보기를 넣는다. `_handle_dayend`가 판단 전에 **늘** 돈다(받은편지함이 비어도, 사용자 몫이 모자라도). 단계마다 따로 트랜잭션, 예외는 `agent_dayend_step_error`(`step` 이름, 오류 종류) 로그 뒤 다음 단계.
    - 상태 키 `DAYEND_DAY_KEY = "agent_dayend_day:{agent}"`(마지막으로 부른 논리적 날짜), `DAYEND_ATTEMPTS_KEY = "agent_dayend_attempts:{agent}"`
    - `@dataclass(frozen=True) DayendInput(text: str, event_ids: tuple[int, ...], events: int)`
    - `prepare(repo: AgentsRepo, state: StateRepo, agent: InboxAgent, today: date, now: datetime) -> DayendInput | Literal["already", "empty"]` — 한 트랜잭션에서: `since = today − 7일`보다 이른 안 읽은 줄을 본 것으로(`mark_seen_before`), 그날 이미 불렀으면(`DAYEND_DAY_KEY == today`) `"already"`, 안 읽은 줄이 없으면 `"empty"`. 있으면 최신 100개로 입력을 만들고, 100개 밖의 창 안 줄도 `event_ids`에 넣어 함께 본 것으로 만든다.
    - `build_dayend_input(today: date, events: list[AgentEvent], past: list[AgentNote]) -> str` — 모양(빈 섹션은 `- 없음`):
      ```
      ## 판단하는 날
      {today−1 ISO} ({요일})

      ## 새로 생긴 것
      - {kind} {ref} · {area} · {day ISO}      (오래된 것부터, area가 없으면 그 칸을 뺀다)

      ## 지난 관찰
      - {day ISO} {text}                       (그 상대의 최근 3개, 최신 먼저)
      ```
      사건 줄은 `harness.inbox.event_line(e: AgentEvent) -> str`(이 Task에서 `harness/inbox.py`를 만들어 이 함수만 둔다. Task 5가 같은 파일에 블록을 더한다).
    - `mark_called(state: StateRepo, agent: InboxAgent, today: date) -> None` — `DAYEND_DAY_KEY`를 오늘로(트랜잭션). 이 모듈만 쓴다(쓰기 경로 감시가 `app_state`의 하루 끝 작업 쓰기를 이 모듈로 본다).
    - `dayend_system_prompt(agent: InboxAgent) -> str` = `prompts.load(DAYEND_PROMPTS[agent]) + "\n\n" + prompts.load("agent_dayend.md")`
    - `settle(repo, state, agent, today, inp: DayendInput, result: BrainResult, notes_written: int, now) -> Literal["ok", "retry", "failed", "limited"]`:
      - `result.status == "ok"` 또는 `notes_written > 0` → `inp.event_ids`를 본 것으로, 시도 수 0 → `"ok"`
      - `rate_limited`·`auth_error` → 아무것도 표시하지 않고 시도 수 그대로 → `"limited"`
      - 그 밖 → 시도 수 + 1. 2에 닿으면 `inp.event_ids`를 본 것으로, 시도 수 0, 로그 `agent_dayend_failed`(`agent`, `events`) → `"failed"`. 아니면 `"retry"`(다음 날 쌓인 것과 함께 다시)
    - `prune(repo: AgentsRepo, today: date, now: datetime) -> dict[str, int]` — 트랜잭션 + `AgentsRepo.prune`, 로그 `agent_tables_pruned`(개수만)
  - `dispatcher.py`:
    - `_PRIORITY_DAYEND = 3`(순간 정리 `2` 다음, 스펙 6.1 순서), `@dataclass _DayendJob(date: date)`(그날 = 논리적 오늘)
    - `submit_dayend(today: date) -> None`
    - `_handle_dayend(job) -> None`: 먼저 `DAYEND_CODE_STEPS`를 차례로(멈추는 중이어도). 멈추는 중이면 그다음은 안 함. `DAYEND_AGENTS` 순서대로 상대마다 `_dayend_one(agent, today)`, 끝나면 늘 `dayend.prune(...)`(스펙 6.1 "→ 정리").
    - `_dayend_one(agent, today) -> None`: `prepare`가 `"already"`·`"empty"`면 로그 `agent_dayend`(`result`가 그 값)만. `_moments_blocked()`면 로그 `result="waiting"`(받은편지함 그대로, 그날 키도 쓰지 않음 → 다음 날 따라잡기). 아니면 `dayend.mark_called(state, agent, today)` 뒤 `RunContext(None, None, kind="dayend", actor="secretary", activity_channel="scheduler", channel="app", agent=agent, dayend_day=today − 1일)`로 `_call_brain(inp.text, session_id=None, run_ctx=…, system_prompt=dayend_system_prompt(agent), max_turns=3, persist_session=False)`. `finally`에서 `remove_session_file(sid, config_dir=…, event="agent_dayend_session_cleanup")`(순간 작업과 같은 방식). `rate_limited`면 `_set_limited`. `settle` 뒤 로그 한 줄.
    - 로그 `agent_dayend` 칸: `agent`, `events`(입력 사건 수), `notes`, `handoffs`, `result`(`ok`·`retry`·`failed`·`limited`·`empty`·`already`·`waiting`), `duration_ms`. 글·`ref` 없음(스펙 12장).
    - `'입력 중'`은 보내지 않는다: `channel="app"`이라 `_call_brain`의 `quiet`가 이미 참이다(종류 목록은 고치지 않는다).
  - `runner.py`: `queue_dayend_daily(target: DayendSubmitter) -> Callable[[date], None]`(`job.__name__ = "queue_dayend"`, 로그 `dayend_queued`), `class DayendSubmitter(Protocol): def submit_dayend(self, today: date) -> None`.
  - `app.py`: `runner.register_daily(queue_dayend_daily(dispatcher))`를 `queue_moments_daily` 바로 다음 줄에.

- [ ] **Step 1: 실패하는 테스트**(`tests/test_dayend_job.py`, `test_moments_job.py`와 같은 디스패처 조립·`FakeBrain` 방식)
  - `test_dayend_one_call_per_day_sp14`(T5, AC7): `mate`·`manager` 받은편지함 모두 안 읽은 줄이 있다. 같은 논리적 날짜에 `submit_dayend`를 두 번 → `kind == "dayend"` 두뇌 호출 1회, 둘째 로그 `result="already"`, `usage.brain_calls`가 정확히 1 늘었다, 그 호출의 `run_ctx.agent == "mate"`. `manager` 줄은 안 읽은 채 그대로.
  - `test_dayend_skips_when_reserve_short`(T5, AC7): `usage.brain_calls = daily_brain_calls − 10` → 호출 0, 줄 그대로, 그날 키 없음. 다음 날(사용 0) → 호출 1, 입력에 두 날의 사건 `ref`가 모두 있다.
  - `test_catch_up_one_call_older_than_7_seen`(T5): 사건 날짜 `today−9`, `today−8`, `today−7`, `today−3`, `today−1` → 호출 1, 입력에 뒤 셋만, 앞 둘은 호출 전에 본 것. 성공 뒤 다섯 다 본 것.
  - `test_empty_inbox_no_call`(1장 3): 안 읽은 줄 없음 → 호출 0, 로그 `result="empty"`.
  - `test_code_steps_run_always`: `DAYEND_CODE_STEPS`에 가짜 단계(호출 수를 셈)와 예외를 내는 단계 → 받은편지함이 비어도, 사용자 몫이 모자라도 가짜 단계가 한 번씩 돌고 두뇌 호출 0, 예외 단계 뒤 단계도 돈다.
  - `test_input_shape`: 입력이 `## 판단하는 날\n{어제} (요일)`로 시작하고, 사건 줄이 `- workout_logged workout:3 · health · 2026-11-01` 모양, 영역 없는 사건은 `- event_added event:2 · 2026-11-01`, 지난 관찰 3개(4개 중 최신 3)가 최신 먼저. 시스템 지시문이 `mate.md` 글 + `\n\n` + `agent_dayend.md` 글. `max_turns == 3`, `persist_session is False`.
  - `test_events_capped_100_rest_seen`: 창 안 105줄 → 입력 사건 줄 100개(최신), 성공 뒤 105줄 모두 본 것.
  - `test_zero_notes_ok`(T12, 1장 3): 두뇌가 도구 없이 `ok` → 결과 `ok`, 줄 본 것, 관찰 0.
  - `test_failure_retries_next_day_then_marks_seen`(스펙 6.2·12장): `status="error"` → 줄 안 읽음, 시도 1, 결과 `retry`. 다음 날 또 `error` → 줄 본 것, 로그 `agent_dayend_failed` 한 줄, 시도 0. `rate_limited` → 시도 수 그대로, `limited_until` 기록.
  - `test_dayend_after_moments_then_prune`(스펙 6.1): `BeEnv`(`moments=True`)에서 04:01 tick → 두뇌 호출 종류 `["moments", "dayend"]` 순서. 91일 전 사건은 그 tick 뒤 지워졌다.
  - `test_queue_dayend_registered_after_moments`: `BeEnv`의 `[j.__name__ for j in env.parts.runner._daily]`에서 `"queue_dayend"`가 `"queue_moments"` 바로 다음.
  - `test_session_file_removed_after_dayend`(6.3): 순간 작업 테스트와 같은 가짜 설정 폴더 → 세션 jsonl 지움(오류 때도).
  - `test_dayend_log_has_counts_only`(T2, 12장): `caplog`의 `agent_dayend` 기록 칸이 정확히 `{agent, events, notes, handoffs, result, duration_ms}`이고 로그 전체에 관찰 글·`ref` 문자열이 없다.
  - `test_dayend_sends_nothing`(T13 실행 쪽, 1장 4): `FakeSender`·`FakePushSender`로 판단(관찰 2개 저장) → 보낸 메시지 0, 푸시 0, `usage.proactive_messages` 그대로, `runs` 줄 수 그대로, 원문 기록 파일 없음.
- [ ] **Step 2:** `.venv/bin/python -m pytest tests/test_dayend_job.py -q` → FAIL.
- [ ] **Step 3:** 구현.
- [ ] **Step 4:** PASS, 전체 PASS·ruff 0.
- [ ] **Step 5:** `git commit -m "feat(sp14): 하루 끝 판단 작업과 따라잡기·정리"`

### Task 5: 즉시 판단 — 메이트 대화의 "새로 생긴 것" 블록 (SP14-05)

**Files:**
- Modify: `src/my_planner/harness/inbox.py`(Task 4가 만든 파일에 블록), `src/my_planner/harness/dispatcher.py`(`_handle_messages`)
- Test: `tests/test_inbox_instant.py`(새)

**Interfaces:**
- Consumes: Task 1 `AgentsRepo.unseen`·`mark_seen`, `INBOX_AGENTS`.
- Produces:
  - `inbox.py`:
    - `event_line(e: AgentEvent) -> str`(Task 4, 그대로)
    - `@dataclass(frozen=True) InboxBlock(text: str, event_ids: tuple[int, ...])`
    - `inbox_block(repo: AgentsRepo, agent: InboxAgent, today: date) -> InboxBlock | None` — 사건 `day >= today − 7일`의 안 읽은 줄 최신 30개, 글은 오래된 것부터: `"## 새로 생긴 것 (지난 대화 뒤)\n" + 줄들`. 없으면 `None`. **SP15** 라이프 매니저 앞머리의 "새로 생긴 것" 블록이 이것이다.
  - `_handle_messages`: `conv.agent`가 `INBOX_AGENTS`에 있고 `self.tools.agents`가 있으면 `body`의 `## 메시지` 바로 앞에 블록(메시지마다, 이어진 세션에서도). 마지막 두뇌 결과가 `status == "ok"`면 `_send_reply` 전에 `mark_seen(agent, block.event_ids, now)`(디스패처가 쓴다). 비서 대화에는 붙이지 않는다. 멈추기(`_Stopped`)·오류·상한·사용 한도 길에서는 표시하지 않는다.

- [ ] **Step 1: 실패하는 테스트**(`tests/test_inbox_instant.py`, `BeEnv`로 앱 `/chat`)
  - `test_instant_block_prepended_and_marked_seen`(T8, 1장 5): 메이트 받은편지함에 안 읽은 줄 2개 → 메이트에게 메시지 → 두뇌 프롬프트에 `## 새로 생긴 것 (지난 대화 뒤)`와 두 `ref`가 있고 그 블록이 `## 메시지`보다 앞. 응답 뒤 두 줄 `seen_at` 있음. 같은 대화 둘째 메시지 프롬프트에는 블록이 없다.
  - `test_event_mid_conversation_attached_next_message`(7장): 첫 메시지 뒤 `/actions`로 일정 추가 → 둘째 메시지 프롬프트에 그 `event:<id>` 하나만.
  - `test_instant_block_not_marked_on_failure`(T8, Review Focus 5): 두뇌 `error` 4회(재시도 포함) → 줄 안 읽음.
  - `test_instant_block_not_marked_on_stop`: 두뇌 호출 중 `POST /chat/stop` → 줄 안 읽음.
  - `test_instant_block_capped_30_newest`: 35줄 → 블록 줄 30개(최신 30, 글은 오래된 것부터), 응답 뒤 안 읽은 줄 5.
  - `test_secretary_chat_has_no_inbox_block`: 비서 앱 대화 프롬프트에 블록 없음, 메이트 줄 그대로.
- [ ] **Step 2:** `.venv/bin/python -m pytest tests/test_inbox_instant.py -q` → FAIL.
- [ ] **Step 3:** 구현.
- [ ] **Step 4:** PASS, 전체 PASS·ruff 0(`tests/test_mate_prompts.py::test_mate_prompt_parts`가 프롬프트 모양을 그대로 비교하면, 안 읽은 줄이 없는 그 시험은 그대로 통과해야 한다).
- [ ] **Step 5:** `git commit -m "feat(sp14): 메이트 대화의 즉시 판단 블록"`

### Task 6: 마스터의 아침 브리핑 한 줄과 "먼저 말하지 않는다" 검사 (SP14-06)

**Files:**
- Create: `src/my_planner/harness/brief_notes.py`
- Modify: `src/my_planner/harness/dispatcher.py`(`_run_brain`, `_prepare_run`, `_run_delivered`, `__init__`의 `self._brief_shown: dict[int, tuple[int, ...]]`), `src/my_planner/harness/prompts/morning_brief.md`
- Test: `tests/test_brief_notes.py`(새), `tests/test_agent_silence.py`(새), `tests/test_api_e2e.py`(이야기 하나), `tests/test_write_paths.py`(단언 더함)

**Interfaces:**
- Consumes: Task 1 `AgentsRepo.brief_candidates`·`mark_shown`; Task 3 `write_note`; Task 4 하루 끝 판단.
- Produces:
  - `brief_notes.py`:
    - `AGENT_LABELS: dict[InboxAgent, str] = {"mate": "운동메이트", "manager": "라이프 매니저"}`
    - `note_line(n: AgentNote) -> str` → `"{AGENT_LABELS[n.agent]}: {n.text}"`
    - `brief_block(cands: list[AgentNote]) -> str` — 후보가 없으면 `""`. `priority` 1이 하나라도 있으면(문구 이대로):
      ```
      ## 아래층 관찰
      하네스가 아래 줄을 메시지 끝에 그대로 붙입니다. 같은 내용을 다시 쓰지 않습니다.
      - {note_line}            (priority 1 줄들만)
      ```
      없으면:
      ```
      ## 아래층 관찰
      아래 가운데 오늘 도움이 될 줄이 있으면 하나만 골라 그대로 메시지 끝에 한 줄로 붙입니다. 없으면 붙이지 않습니다.
      - {note_line}            (priority 2 줄들)
      ```
    - `@dataclass(frozen=True) BriefNotes(text: str, shown_ids: tuple[int, ...])`
    - `BRIEF_P1_MAX = 2`. 붙일 `priority` 1은 `brief_candidates` 순서(`priority`, `created_at`, `id`)로 앞 2개. 나머지 `priority` 1은 표시하지 않고 다음 브리핑 후보로 남는다. `brief_block`도 그 2개만 싣는다.
    - `settle_brief(text: str, cands: list[AgentNote]) -> BriefNotes` — 찾기는 관찰 본문을 공백 정규화(`" ".join(s.split())`)해 그 줄에 들어 있는지로 본다(앞 이름은 보지 않는다). 찾아서 남기는 줄은 그 줄 전체를 `note_line(n)`으로 바꿔 쓴다(앱 `splitAgentNotes`가 `"운동메이트: "`로 시작하는 줄만 읽으므로):
      - `priority` 1이 있으면: 본문에 든 `priority` 2 줄은 지운다. 붙일 `priority` 1(많아야 2)마다 이미 있으면 그 줄을 `note_line`으로, 없으면 끝에 덧붙인다(본문 뒤 빈 줄 하나 + 덧붙일 줄들을 `\n`으로). `shown_ids` = 붙인 `priority` 1.
      - 없으면: 본문에 든 `priority` 2 가운데 처음 나온 하나만 `note_line`으로 남기고 나머지 든 줄은 지운다. `shown_ids` = 남긴 하나(없으면 빈 튜플).
  - 디스패처:
    - `_run_brain`: 회차들(`run`, `*merged`) 가운데 `LoopKey.morning_brief`가 있고 `tools.agents`가 있으면 `brief_block(brief_candidates(today))`를 프롬프트의 앞머리 뒤(조건 블록들 앞)에 넣는다. 다른 회차에는 없다.
    - `_prepare_run`: 같은 조건이면 `text`(두뇌 글 또는 턴 상한 글)에 `settle_brief`를 확인 문구를 붙이기 **전에** 적용하고, `self._brief_shown[run.id] = shown_ids`.
    - `_run_delivered`: `self._brief_shown.pop(run.id, ())`를 `mark_shown(ids, now)`(트랜잭션). 보내지 못하면(`_record_not_sent`) 표시하지 않는다. 재전송이 성공하면 `_run_delivered`가 표시한다.
    - 하루 먼저 보내는 말 수(3회)는 그대로다(관찰은 브리핑 안이라 세지 않음, 스펙 8장).
    - 범위 밖: `_brief_shown`은 메모리에만 있다. 보내기 전에 BE가 다시 켜지면 표시되지 않고 다음 브리핑 후보로 남는다(같은 줄이 한 번 더 나올 수 있다. 시험하지 않는다).
  - `morning_brief.md` 끝에 한 줄(이대로): `- 앞머리에 \`## 아래층 관찰\`이 있으면 그 섹션의 안내를 따릅니다. 관찰 줄은 고치지 않고 그대로 씁니다.`

- [ ] **Step 1: 실패하는 테스트**
  - `tests/test_brief_notes.py`(순수 함수, T7):
    - `test_at_most_one_p2`: 후보 p2 a·b, 두뇌 글에 두 줄 → 결과에 a 줄만, b 줄 없음, `shown_ids == (a,)`.
    - `test_p1_appended_even_if_brain_omits`: 후보 p1 하나, 두뇌 글 `"좋은 아침이에요."` → 결과 `"좋은 아침이에요.\n\n운동메이트: {p1.text}"`, `shown_ids == (p1,)`.
    - `test_p1_not_duplicated_when_brain_wrote_it`: 두뇌 글에 이미 그 줄 → 한 번만.
    - `test_p1_capped_at_two`: p1 셋(`created_at` 순서 x, y, z) → 끝에 x·y 두 줄, `shown_ids == (x, y)`, z는 `brief_candidates`에 남는다.
    - `test_matched_line_rewritten_to_label_form`: 두뇌가 `"- 참고로 {p2 본문}"`이라고 쓰면 결과의 그 줄은 정확히 `"운동메이트: {p2 본문}"`.
    - `test_two_p1_both_and_no_p2`: p1 둘 + p2 하나, 두뇌가 p2 줄을 씀 → p1 두 줄이 끝에, p2 줄은 지워짐, `shown_ids`는 p1 둘.
    - `test_brief_match_ignores_spacing_and_label`(Review Focus 3): 두뇌가 `"메이트:  {p2 본문의 공백 두 칸}"`처럼 써도 찾는다. 본문을 바꿔 쓰면 못 찾고 `shown_ids == ()`.
    - `test_block_copy`: p1이 있을 때와 없을 때 `brief_block` 글이 위 두 모양 그대로.
  - `tests/test_brief_notes.py`(디스패처, `FakeBrain`·`FakeSender`):
    - `test_morning_brief_gets_block_others_not`: 아침 브리핑 회차 프롬프트에 `## 아래층 관찰`, 저녁 체크인 회차에는 없음.
    - `test_p1_appended_by_harness_with_fake_brain`(T7 "두뇌 답을 가짜로 바꿔도"): 두뇌 글에 관찰이 없어도 보낸 메시지 글(`FakeSender.sent[-1].text`)과 `runs.outbound_text` 끝이 `운동메이트: …`.
    - `test_shown_marked_only_after_delivery`: `FakeSender(fail=True)` → `shown_at` NULL. 성공 전송 → `shown_at` 있음.
    - `test_unchosen_note_kept`(T7): p2 둘 중 두뇌가 하나를 씀 → 다른 하나는 `shown_at` NULL로 남고 지워지지 않는다. 3일 뒤 `brief_candidates`에는 없고 `AgentsRepo.notes(None, today−7)`에는 있다.
    - `test_note_judged_after_brief_shows_next_morning`(Review Focus 2): 같은 tick에 아침 브리핑과 하루 끝 판단이 큐에 듦 → 그날 브리핑에 관찰 없음, 판단이 쓴 관찰은 다음 날 브리핑 끝에 붙는다(p1).
  - `tests/test_agent_silence.py::test_lower_agents_have_no_send_path`(T13 정적 쪽): `src/my_planner` 아래 모든 `.py`를 `ast`로 읽어 이름이 `deliver_run`, `deliver_notice`, `deliver_reminder`, `deliver_digest`, `send_notice`, `send_run_telegram`, `send_with_retry`인 호출이 있는 모듈 집합을 모은다 → `my_planner.harness.dayend`, `my_planner.harness.inbox`, `my_planner.harness.brief_notes`, `my_planner.tools.agents`, `my_planner.store.repos.agents`가 없다. 또 `dayend.py`·`tools/agents.py`는 `harness.delivery`·`bot`을 가져오지 않는다. 그리고 `dispatcher.py`의 `Dispatcher._handle_dayend`·`Dispatcher._dayend_one` 함수 몸통(`ast.FunctionDef`)에 `send_notice`, `_run_notice_auth`, `_run_notice_rate_limit`, `_send_reply`, `_send_run`, `_fixed_reply`, `deliver_*` 호출과 `self.sender`·`self.delivery` 속성 읽기가 없다.
  - `tests/test_api_e2e.py::test_sp14_master_story`(1장 1·3·4, 쓰기 경로 감시가 이 이야기도 돈다): 2026-11-01 13:00 `/actions`로 할 일 추가·완료 → 메이트에게 "스쿼트 60kg 5x5 했어"(가짜 두뇌 `log_workout`. 메이트 자기 대화의 사건이라 메이트에게는 본 것) → `/actions create_event`로 11-03 저녁 일정 하나(메이트 받은편지함에 안 읽은 `event_added`) → 11-02 04:01 tick(하루 끝 판단, 가짜 두뇌 `write_note(priority=1, text="가짜 관찰 한 줄이에요.", refs=["workout:1"])`) → 아침 브리핑 시각 tick(가짜 두뇌 글 `"좋은 아침이에요."`). 두뇌 호출 종류 `["chat", "dayend", "run"]`, 보낸 브리핑 글 끝 `"운동메이트: 가짜 관찰 한 줄이에요."`, 그 관찰 `shown_at` 있음, `agent_events`에 `task_added`·`task_done`·`workout_logged`·`event_added`, 하루 끝 판단 입력에 `event_added`가 있고 `workout_logged`는 없다, 메이트 받은편지함은 모두 본 것.
  - `tests/test_write_paths.py`: `("agent_notes", "my_planner.tools.agents", DISPATCHER, True) in rec.tool_calls`, `("agent_notes", DISPATCHER) in rec.seen`(`shown_at`), `("agent_inbox", "my_planner.harness.dayend") in rec.seen`, `("app_state", "my_planner.harness.dayend") in rec.seen`.
- [ ] **Step 2:** `.venv/bin/python -m pytest tests/test_brief_notes.py tests/test_agent_silence.py tests/test_api_e2e.py::test_sp14_master_story -q` → FAIL.
- [ ] **Step 3:** 구현.
- [ ] **Step 4:** PASS, `tests/test_write_paths.py` PASS, `tests/test_dispatcher_runs.py::test_morning_prompt_file_covers_brief_without_banned_words` PASS, 전체 PASS·ruff 0.
- [ ] **Step 5:** `git commit -m "feat(sp14): 아침 브리핑의 관찰 한 줄과 priority 1 덧붙이기"`

### Task 7: API — 받은편지함 수, 관찰 목록, `/health` 기능 (SP14-07)

**Files:**
- Create: `src/my_planner/api/agents.py`
- Modify: `src/my_planner/api/server.py`(`READ_ROUTES`), `src/my_planner/api/models.py`(모델, `MODELS`), `src/my_planner/api/health.py`(`features`), `web/app/src/api/schema.json`·`types.gen.ts`, `web/dashboard`의 스키마 사본(`npm run gen:types`)
- Test: `tests/test_api_agents.py`(새), `tests/test_api_schema.py`, `tests/test_api_health.py`(더함)

**Interfaces:**
- Consumes: Task 1 `AgentsRepo.unseen_count`·`notes`, `INBOX_AGENTS`; Task 5 `INBOX_WINDOW_DAYS`; SP13 `api.standing.dashboard_device`.
- Produces:
  - `GET /api/v1/agents/{agent}/inbox/count` → 모델 `InboxCount {unseen: int}`: 사건 `day >= 오늘 − 7일`의 안 읽은 줄 수(즉시 판단이 붙일 범위). `agent`는 `mate`·`manager`, 그 밖은 `404 {"error": {"code": "not_found", "message": "없는 대화 상대예요."}}`. 두뇌를 부르지 않는다(읽기 전용 연결).
  - `GET /api/v1/agents/notes?days=7` → 모델 `AgentNotes {notes: [AgentNoteOut]}`, `AgentNoteOut {id: int, agent: "mate"|"manager", day: "YYYY-MM-DD", text: str, priority: 1|2|3, shown_at: str|null, created_at: str}`(최신 먼저, 시각은 지금 API 방식 UTC ISO). `days`는 정수 1~30, 기본 7, 그 밖은 `400 invalid_request`("days는 1부터 30까지예요."). 대시보드 기기는 `403 forbidden`("이 화면에서는 볼 수 없어요.", SP13과 같은 규칙).
  - `/health`의 `features`: `["mate", "agent_notes"]`(앱이 받은편지함 수·비서 메모를 부를지 정한다).
- [ ] **Step 1: 실패하는 테스트**
  - `test_inbox_count_per_agent`(T8 "시트만 열면 호출 없음"): 메이트 안 읽은 2(하나는 8일 전) → `{"unseen": 1}`, `manager` → 그 수, `secretary`·`bogus` → 404. 그동안 `env.brain.calls == []`, `usage.brain_calls == 0`.
  - `test_notes_days_param`: 관찰 `day` 오늘−1·오늘−8 → 기본은 하나, `days=30`은 둘, `days=0`·`31`·`abc` → 400.
  - `test_notes_dashboard_forbidden`: `client='dashboard'` 기기 토큰 → 403, `client='app'` 기기·API 토큰 → 200.
  - `test_notes_include_handoff_priority_3`: 넘기기 관찰도 목록에 있고 `priority == 3`.
  - `test_api_schema.py`: 묶음에 `InboxCount`, `AgentNotes`.
  - `test_api_health.py`: `features == ["mate", "agent_notes"]`.
- [ ] **Step 2:** `.venv/bin/python -m pytest tests/test_api_agents.py tests/test_api_schema.py tests/test_api_health.py -q` → FAIL.
- [ ] **Step 3:** 구현(`read_handler`, 경로 순서는 `/agents/notes`를 `/agents/{agent}/inbox/count`와 함께 `READ_ROUTES` 끝에).
- [ ] **Step 4:** `cd web/app && PATH=/opt/node22/bin:$PATH npm run gen:types`, `cd web/dashboard && PATH=/opt/node22/bin:$PATH npm run gen:types`, 그리고 `.venv/bin/python -m pytest tests/test_dashboard_fixtures.py -q`(스키마 사본 일치. 대시보드 고정 자료는 새 경로를 쓰지 않으므로 다시 기록하지 않는다). PASS, 전체 PASS·ruff 0.
- [ ] **Step 5:** `git commit -m "feat(sp14): GET /agents/{agent}/inbox/count, /agents/notes"`

### Task 8: 운영 앱 — 상대 고르기의 "새로 본 것", 브리핑 관찰 줄 픽토그램, 더보기 "비서 메모" (SP14-08)

**Files:**
- Modify: `web/shared/pictograms.svg`(`dumbbell`, `compass` 기호), `DESIGN.md`(Pictograms 표 두 줄, 개수 28 → 30), `web/app/src/components/pictograms.gen.tsx`·`web/dashboard/src/components/pictograms.gen.tsx`(`npm run sync:design`, 생성만), `web/app/src/components/Segmented.tsx`·`Segmented.module.css`, `web/app/src/chat/ChatSheet.tsx`, `web/app/src/screens/Today.tsx`, `web/app/src/screens/Checkin.tsx`, `web/app/src/screens/More.tsx`, `web/app/src/lib/copy.ts`, `web/app/src/api/client.ts`(경로 둘)
- Create: `web/app/src/lib/agentNotes.ts`·`agentNotes.test.ts`, `web/app/src/components/AgentNoteLines.tsx`
- Test: `web/app/src/chat/ChatSheet.test.tsx`, `web/app/src/screens/Today.test.tsx`, `web/app/src/screens/Checkin.test.tsx`, `web/app/src/screens/More.test.tsx`, `web/app/src/components/Pictogram.test.tsx`, `Segmented`의 테스트(있는 파일에 더하거나 `Segmented.test.tsx` 새로)

**Interfaces:**
- Consumes: Task 7 `GET /agents/{agent}/inbox/count`, `GET /agents/notes`, 생성 타입 `InboxCount`, `AgentNotes`, `/health` `features`에 `"agent_notes"`; Task 6 브리핑 줄 모양 `"{이름}: {관찰}"`.
- Produces(화면 규칙, 스펙 10장, 새 화면 없음):
  - 픽토그램 `dumbbell`(운동메이트), `compass`(라이프 매니저, **SP15**가 상대 고르기에 쓴다). 24px 격자, 선 1.75, 채우지 않음(DESIGN.md 규칙 1). DESIGN.md 표: `| \`dumbbell\` | 운동메이트 | 브리핑 관찰 줄, 비서 메모 |`, `| \`compass\` | 라이프 매니저 | 브리핑 관찰 줄, 비서 메모(SP15 상대 고르기) |`.
  - `Segmented` 선택지에 선택 칸 `hint?: string`: 있으면 이름 아래 작은 줄(`--muted`), 접근 이름은 이름 그대로이고 `hint`는 `aria-describedby`.
  - `copy.ts`(이대로): `chat.agents.unseen: (n: number) => \`새로 본 것 ${n}개\``, `more.agentNotes: "비서 메모"`, `more.agentNotesEmpty: "아직 없어요."`, `agentNames: { mate: "운동메이트", manager: "라이프 매니저" }`(`chat.agents.mate`와 같은 글).
  - 채팅 시트: `features`에 `"agent_notes"`가 있고 상대 고르기가 보일 때 시트를 열면 `GET /agents/mate/inbox/count`를 한 번 부르고 운동메이트 선택지 `hint`에 `copy.chat.agents.unseen(n)`(0이면 `hint` 없음). 메이트에게 보낸 메시지의 답이 끝나면 다시 부른다. 누르면 아무 일 없음(정보만). 두뇌 호출 없음.
  - `lib/agentNotes.ts`: `splitAgentNotes(text: string): { body: string; notes: { agent: "mate" | "manager"; text: string }[] }` — 줄 맨 앞이 `"운동메이트: "` 또는 `"라이프 매니저: "`인 줄을 모두 뽑고(순서 그대로) 나머지 글은 `body`(끝 공백 줄 정리). 그 밖의 글은 그대로.
  - `AgentNoteLines({ notes })`: 줄마다 `<Pictogram name={agent === "mate" ? "dumbbell" : "compass"} size={20} />`(이름 글자가 있으므로 `aria-hidden`, DESIGN.md 규칙 3) + 상대 이름 + 관찰 글. `Today.tsx` 브리핑과 `Checkin.tsx` 본문이 `Markdown`에 `body`를, 그 아래 `AgentNoteLines`를 그린다. 접기(`FOLD_LINES`)는 `body`에만.
  - 더보기: `features`에 `"agent_notes"`가 있으면 `copy.more.agentNotes` 줄(설정 줄들 사이, "운동" 줄 다음). 누르면 그 자리에서 펼쳐 `GET /agents/notes?days=7` 목록(픽토그램, 상대 이름, 글, `M/D`). 비면 `copy.more.agentNotesEmpty`. 새 페이지를 만들지 않는다.
  - 첫 화면 예산: `npm run size` 180KB 이하(지금 약 178.5KB). 첫 화면에 드는 새 코드는 `splitAgentNotes`와 `AgentNoteLines`뿐이고 새 의존성은 없다. 채팅 시트는 따로 불러오는 조각이다.
- [ ] **Step 1: 실패하는 테스트**(vitest + Testing Library)
  - `agentNotes.test.ts`: `splitAgentNotes("좋은 아침이에요.\n\n운동메이트: 토요일만 비어요.")` → `{body: "좋은 아침이에요.", notes: [{agent: "mate", text: "토요일만 비어요."}]}`. `"라이프 매니저: …"` → `manager`. 가운데 줄도 뽑는다. `"메이트: …"`·`"운동메이트:붙여씀"`은 그대로 `body`.
  - `Pictogram.test.tsx`: `PICTOGRAM_NAMES`에 `"dumbbell"`, `"compass"`, 길이 30.
  - `Segmented` 테스트: `hint`가 있으면 그 글이 보이고 라디오의 접근 이름은 이름만, 설명으로 `hint`.
  - `ChatSheet.test.tsx`: `features: ["mate", "agent_notes"]`, 수 3 → 운동메이트 아래 "새로 본 것 3개". 0 → 그 글 없음. 메이트에게 보낸 뒤 수 0 응답 → 글 사라짐. `features: ["mate"]`만 → 수 경로를 부르지 않는다.
  - `Today.test.tsx`·`Checkin.test.tsx`: 브리핑 글 끝 `"운동메이트: 가짜 관찰이에요."` → `use[href="#p-dumbbell"]`가 있는 줄과 "가짜 관찰이에요.", 본문 Markdown에는 그 줄이 없다.
  - `More.test.tsx`: `"agent_notes"` 기능 → "비서 메모" 줄, 누르면 `GET /agents/notes?days=7` 목록 두 줄(픽토그램·이름·글). 빈 목록 → "아직 없어요.". 기능이 없으면 줄 없음.
- [ ] **Step 2:** `cd web/app && PATH=/opt/node22/bin:$PATH npm test` → FAIL.
- [ ] **Step 3:** 구현. 픽토그램은 `web/shared/pictograms.svg`를 고친 뒤 `cd web/app && npm run sync:design`, `cd web/dashboard && npm run sync:design`(DESIGN.md "두 앱의 생성 파일을 같은 커밋에서").
- [ ] **Step 4:** 이 Task를 시작할 때(Step 1 전) `npm run size` 출력 숫자를 적어 두고, `cd web/app && PATH=/opt/node22/bin:$PATH npm test && npm run typecheck && npm run lint:copy && npm run size`(180KB 이하). 전·후 숫자를 커밋 메시지 본문과 PR 설명에 한 줄로 적는다, `cd web/dashboard && PATH=/opt/node22/bin:$PATH npm test`, `.venv/bin/python -m pytest -q`(대시보드·앱 생성 파일 일치 테스트 포함) 모두 0.
- [ ] **Step 5:** `git commit -m "feat(sp14): 앱 상대 고르기의 새로 본 것, 브리핑 관찰 줄, 비서 메모"`

### Task 9: 마무리 — 노트북·아이폰 확인 목록 (SP14-09)

**Files:**
- Create: `docs/sp14/laptop-checklist.md`(절차만, 개인 값 없음)
- Modify: 스펙 맨 위(구현 중 이 계획과 다르게 정한 것이 생겼을 때만 "v1.2 정정" 한 줄)

- [ ] **Step 1:** `docs/sp14/laptop-checklist.md`(수용 기준 1·3·4·5·7을 사람이 본다). 내용:
  1. **업데이트.** BE를 업데이트하고 다시 켠다. 시작 로그에 마이그레이션 023이 돌았는지(`user_version` 23) 본다.
  2. **사건이 쌓인다(1장 1, 8).** 앱에서 할 일 하나를 끝내고, 메이트에게 운동 하나를 말한다. BE의 DB 파일을 `sqlite3 -readonly`로 열어 `SELECT kind, ref, area, origin FROM agent_events ORDER BY id DESC LIMIT 5`에 `task_done`·`workout_logged`가 있고 제목·본문 칸이 없는지 본다(결과를 저장소나 대화에 붙이지 않는다).
  3. **즉시 판단(1장 5).** 아이폰 앱에서 채팅 시트를 열고 운동메이트를 고른다 → 이름 아래 "새로 본 것 n개"가 보인다(열기만으로는 아무 답도 오지 않는다). 메이트에게 "오늘 뭐 할까?"를 보내면 첫 답이 새 일정·기록을 언급한다. 시트를 닫았다 열면 "새로 본 것"이 사라진다.
  4. **하루 끝 판단(1장 3, 7).** 다음 날 아침 로그에 `agent_dayend` 한 줄(`agent=mate`, `result=ok` 또는 `empty`)이 하나뿐이고, `brain_call` 가운데 하루 끝 판단은 하나다.
  5. **아침 브리핑(1장 4).** 그날(또는 다음 날) 아침 브리핑 끝에 덤벨 픽토그램과 "운동메이트: …" 한 줄이 많아야 하나 있다. 메이트가 따로 푸시·텔레그램을 보낸 적이 없다.
  6. **비서 메모.** 더보기 › 비서 메모를 누르면 지난 7일 관찰이 펼쳐진다.
  7. **노트북을 하루 이상 꺼 둔 뒤(1장 7).** 켠 날 `agent_dayend`가 한 번만 돌고(`events`가 며칠치 합), 두뇌 호출 상한에 걸리지 않는다.
  8. **대시보드.** 대시보드 화면은 바뀌지 않았다.
- [ ] **Step 2:** `.venv/bin/python -m pytest -q`, `.venv/bin/ruff check src tests`, 앱 검사(Task 8 Step 4) 모두 0.
- [ ] **Step 3:** `git commit -m "docs(sp14): 노트북·아이폰 확인 목록"`

---

## 스펙 대응표

| 스펙 | Task·테스트 |
|---|---|
| 1장 1 (같은 트랜잭션, 두뇌 없음) | Task 2 `test_write_path_leaves_one_event`, `test_rollback_leaves_no_event` |
| 1장 2 (라우팅) | Task 1 `test_route_table`, Task 2 `test_events_routed_to_inbox` |
| 1장 3 (비어 있지 않은 상대마다 1회, 0~2개) | Task 4 `test_empty_inbox_no_call`, `test_zero_notes_ok`; Task 3 `test_write_note_third_call_rejected` |
| 1장 4 (많아야 하나, 아래층은 안 보냄) | Task 6 `test_brief_notes.py`, `test_agent_silence.py`; Task 4 `test_dayend_sends_nothing` |
| 1장 5 (즉시 판단, 열기만이면 호출 없음) | Task 5, Task 7 `test_inbox_count_per_agent` |
| 1장 6 (원문은 직접 읽음, 받은편지함은 종류·id·영역) | Task 1 표 모양, Task 3 읽기 도구, Task 4 `test_input_shape` |
| 1장 7 / T5 (호출 수, 사용자 몫, 따라잡기) | Task 4 `test_dayend_one_call_per_day_sp14`, `test_dayend_skips_when_reserve_short`, `test_catch_up_one_call_older_than_7_seen` |
| 1장 8 / T2 (제목·본문 없음) | Task 2 `test_events_have_ref_only_no_titles`, Task 4 `test_dayend_log_has_counts_only` |
| T3 (라우팅 표) | Task 1 `test_route_table`, Task 2 `test_events_routed_to_inbox` |
| T4 (1분 안 하나) | Task 1 `test_dedupe_within_60s`, Task 2 `test_quick_toggle_is_one_event` |
| 5.2 되돌리기 | Task 2 `test_undo_keeps_event` |
| 5.4 / T10 | Task 3 `test_hand_off_cap_and_inbox` |
| 5.5 (SP15 켜는 날 7일) | Task 1 `mark_seen_before`, Task 4 따라잡기 규칙(SP15가 같은 작업에 상대만 더한다) |
| 6.2 실패 2회, 6.3 세션 파일 | Task 4 `test_failure_retries_next_day_then_marks_seen`, `test_session_file_removed_after_dayend` |
| 8장 | Task 6 |
| 10장·11장 | Task 7, Task 8 |
| 12장 로그 | Task 4 |
| T6 | Task 3 `test_dayend_tools_are_read_only` |
| T7 | Task 6 |
| T8 | Task 5, Task 7 |
| T9 | Task 1 `test_prune_keeps_90_30_365`, Task 4 `test_dayend_after_moments_then_prune` |
| T11 | Task 3 `test_note_rejects_banned_and_shape`, `test_agent_dayend_prompt_has_no_banned_words` |
| T12 | Task 3, Task 4 `test_zero_notes_ok` |
| T13 | Task 6 `test_lower_agents_have_no_send_path`, Task 4 `test_dayend_sends_nothing` |
| T14 | Task 1 `test_023_agent_tables`, `test_add_event_validates`; Task 2 `test_origin_by_path` |
