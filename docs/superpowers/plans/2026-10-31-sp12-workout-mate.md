# SP12 운동메이트 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 운영 앱에 두 번째 대화 상대 "운동메이트"를 더한다: 자기 지시문·도구·대화 목록, 운동 표 다섯, 운동 화면.

**Architecture:** 대화에 `agent` 칸을 두고 라우터·디스패처·두뇌가 상대마다 지시문과 도구 목록을 고른다(ADR 0019). 운동 데이터는 `021_workout_mate.sql`의 새 표와 `store/repos/workout.py`, 도구는 `tools/workout.py`의 `WorkoutTools` mixin. 앱은 채팅 시트의 `Segmented`와 `/workout/` 화면을 더한다.

**Tech Stack:** Python 3.12, SQLite, claude-agent-sdk, aiohttp, pydantic / Next.js(정적 PWA), vitest, Playwright.

**Spec:** `docs/superpowers/specs/2026-10-31-sp12-workout-mate-design.md` (확정 v3.2). 이하 "스펙 N.N"은 이 문서의 절이다. ADR 0019, GLOSSARY "운동메이트" 절.

## Global Constraints

- 브랜치는 `origin/develop`에서, PR base는 `develop`. main에 직접 머지하지 않는다.
- 새 기능은 앱 전용: 텔레그램 UI·명령을 더하지 않는다. 메이트는 푸시·회차·체크인을 만들지 않는다(스펙 1-7).
- 금지어 `연속`, `스트릭`, `달성률`(`tools/ui.py APP_BANNED_WORDS`)과 빠진 날 수·비율(%)을 새 문구·`mate.md`·칩 지시문에 쓰지 않는다.
- 경험치는 오르기만(ADR 0006). X13 = 5, `source_kind` `workout_log`, `source_ref` `workout_day:<YYYY-MM-DD>`, `label` "운동 기록".
- 상수(스펙 13장): `BODY_NOTES_MAX = 30`, `PLAN_SESSIONS_MAX = 7`, `SESSION_ITEMS_MAX = 12`, `LOG_ITEMS_MAX = 20`, `LOG_BACKDATE_DAYS = 6`, `LIST_DAYS_MAX = 180` (`tools/workout.py`). `WORKOUT_POINT = Fraction(1, 2)`은 `status/activity.py`.
- 로그에는 id·개수만. 몸 메모 글, 기록 숫자, 잠·걸음 숫자를 로그·활동 `summary`·푸시에 넣지 않는다(스펙 14장).
- 고정 문구는 스펙 부록 A 그대로(Dahun 확정 2026-10-31). 부록 A에 없는 문구가 필요하면 PR 본문 "새 문구" 목록에 적는다.
- 상대 인자의 기본값은 언제나 `"secretary"`: 지금 호출과 텔레그램 동작이 바뀌지 않는다.
- BE 테스트: `python -m pytest -q`. 앱: `cd web/app && npm test`, `npm run typecheck && npm run lint:copy`, e2e는 `npm run e2e`(빌드 포함). 앱 타입은 `npm run gen:types`로 다시 만든다.
- 스펙 v3.2 정정 요지: 메이트 시스템 지시문은 `mate.md` 하나이고 화면 조각 규칙(`ui_block`·`ui_choice`·`ui_summary_card`, 버튼 `send`·`open`만)도 그 안에 둔다. `channel_app.md`는 건드리지 않는다(`ui_rules.md` 떼기는 하지 않는다: SP6 9.2 블록에 비서 전용 규칙이 섞여 있고 `test_channel_app_is_spec_text`가 그 모양을 지킨다).

## Review Focus

1. **비서 대화와 메이트 대화를 번갈아 쓸 때** 서로를 닫거나 이어 붙이지 않는다(30분 안에 비서 → 메이트 → 비서). Task 2 `test_alternating_agents_keep_own_conversations`.
2. **재시작 사이에 걸린 메이트 메시지**(`inbound_pending`에 남은 것)가 다시 넣을 때 비서 대화로 가지 않는다. Task 2 `test_recovered_inbound_keeps_agent`.
3. **두뇌가 플랜 전체 대신 일부만 보낸 경우**(세션 0개가 아닌데 `items` 빈 세션, 같은 `position` 둘): 저장하지 않고 고칠 수 있는 오류를 돌려준다. Task 3 `test_set_plan_rejects_partial_shapes`.
4. **앱이 BE보다 먼저 배포되거나 BE가 롤백된 때**(`features` 없음): 상대 고르기와 더보기 "운동" 줄이 숨고 비서 채팅은 그대로. Task 7 `hides mate when health has no features`.
5. **몸 메모에 계좌번호 같은 식별 숫자를 말한 경우** 가린 뒤 저장한다(전화번호는 지금 `redact`처럼 가리지 않는다). Task 3 `test_body_note_is_redacted`.

---

### Task 0: 스파이크 — 두 상대의 세션이 섞이지 않는지 (SP12-00)

**Files:**
- Create: `docs/spikes/2026-11-sp12.md`
- Create (버림): `scripts/spike_sp12_agents.py`

- [ ] **Step 1:** 같은 `ClaudeSdkBrain`에서 `system_prompt`만 바꾼 두 호출(가짜 지시문 "너는 A" / "너는 B")을 각각 새 세션으로 시작하고, 각 세션을 `resume`으로 한 번 더 부른다. 두 번째 호출의 답이 자기 지시문을 따르는지 본다(시스템 지시문은 resume 때 다시 넘긴 값이 쓰이는지).
- [ ] **Step 2:** 결과를 `docs/spikes/2026-11-sp12.md`에 한 문단: "resume 때 시스템 지시문 = 그 호출에 넘긴 값" 또는 반대. 반대면 Task 2 Step 3의 `system_prompt_for`를 세션 시작 때만 고르는 것으로 바꿔야 한다고 적는다.
- [ ] **Step 3:** 스크립트는 지우고 문서만 커밋: `git commit -m "docs(sp12): 스파이크 S1 두 상대 세션"`.

### Task 1: 마이그레이션과 저장소 (SP12-01)

**Files:**
- Create: `src/my_planner/store/migrations/021_workout_mate.sql`
- Create: `src/my_planner/store/repos/workout.py`
- Test: `tests/test_migrations.py` (더함), `tests/test_workout_repo.py` (새)

**Interfaces:**
- Produces:
  - SQL: 스펙 6.1·7.1·8.1의 표 다섯 그대로. `ALTER TABLE conversations ADD COLUMN agent TEXT NOT NULL DEFAULT 'secretary' CHECK (agent IN ('secretary','mate'))`, `inbound_pending`에 같은 칸. `status_xp_ledger` 옮기기(012의 그 부분을 복사, `source_kind` 목록 끝에 `'workout_log'`).
  - `BodyKind = Literal["equipment", "injury", "preference", "availability", "other"]`
  - `@dataclass(frozen=True) BodyNote(id: int, kind: BodyKind, text: str, created_at: datetime, updated_at: datetime)`
  - `PlanItem(name: str, sets: int | None, reps: str | None, weight_kg: float | None, minutes: int | None, note: str | None)`
  - `PlanSession(id: int, position: int, label: str, weekdays: tuple[int, ...] | None, items: tuple[PlanItem, ...])`
  - `Plan(id: int, title: str, note: str | None, created_at: datetime, sessions: tuple[PlanSession, ...])`
  - `LogItem(name: str, sets: int | None, reps: int | None, weight_kg: float | None, minutes: int | None, distance_km: float | None)`
  - `WorkoutLog(id: int, date: date, title: str, session_id: int | None, effort: int | None, note: str | None, items: tuple[LogItem, ...], created_at: datetime, updated_at: datetime)`
  - `class WorkoutRepo(conn, clock)`:
    - `notes() -> list[BodyNote]` (지우지 않은 것, `updated_at` 내림차순), `note(id) -> BodyNote | None`, `count_notes() -> int`, `find_note(kind, text) -> BodyNote | None`, `add_note(kind, text, now) -> BodyNote`, `update_note(id, kind, text, now) -> None`, `drop_note(id, now) -> None`, `restore_note(id) -> None`
    - `current_plan() -> Plan | None`, `plan(id) -> Plan | None`, `replace_plan(title, note, sessions: Sequence[tuple[str, tuple[int, ...] | None, Sequence[PlanItem]]], now) -> tuple[int | None, int]` (앞 id, 새 id), `clear_plan(now) -> int | None` (내린 id), `undo_replace(new_id: int, prev_id: int | None, now) -> None`, `undo_clear(plan_id: int) -> None`
    - `add_log(date, title, session_id, effort, note, items, now) -> WorkoutLog`, `log(id) -> WorkoutLog | None`, `update_log(id, now, **fields) -> None` (`items` 포함 시 줄 전체 교체), `delete_log(id, now) -> None`, `restore_log(id) -> None`, `logs(since: date, until: date, name: str | None = None) -> list[WorkoutLog]` (날짜 내림차순, `name`은 운동 줄 이름 부분 일치), `has_log_on(d: date) -> bool`, `log_days(since: date, until: date) -> set[date]`
  - 모든 쓰기는 부르는 쪽 `transaction`에 맡긴다(`HabitsRepo`와 같은 방식).

- [ ] **Step 1: 실패하는 테스트**
  - `test_migrations.py::test_021_workout_tables_and_agent_default`: 마이그레이션 후 표 다섯이 있고, 기존 `conversations` 행의 `agent == "secretary"`, `inbound_pending.agent` 기본값 `secretary`.
  - `test_migrations.py::test_021_ledger_moved_intact`: 020 상태에서 원장 3행(합 25)을 넣고 021 적용 → 행 3, 합 25, `source_kind='workout_log'` 삽입 성공, `'bogus'`는 `IntegrityError`.
  - `test_workout_repo.py::test_only_one_current_plan`: `replace_plan` 두 번 → `current_plan().id`가 두 번째, 첫째 `replaced_at` 있음. 직접 UPDATE로 둘을 지금 플랜으로 만들면 `IntegrityError`.
  - `test_workout_repo.py::test_undo_replace_restores_previous` / `test_clear_and_undo_clear`.
  - `test_workout_repo.py::test_logs_filter_by_name_and_skip_deleted`: "스쿼트" 줄 있는 기록 둘 중 하나 삭제 → `logs(..., name="스쿼")` 1개.
  - `test_workout_repo.py::test_json_checks`: `items='[]'`인 세션 직접 INSERT → `IntegrityError`.
- [ ] **Step 2:** `python -m pytest tests/test_migrations.py tests/test_workout_repo.py -q` → FAIL(표 없음).
- [ ] **Step 3:** SQL과 `WorkoutRepo` 구현. `weekdays`·`items`는 `json.dumps(..., ensure_ascii=False)`.
- [ ] **Step 4:** 같은 명령 → 모두 PASS. `python -m pytest -q` 전체 PASS.
- [ ] **Step 5:** `git commit -m "feat(sp12): 021 운동 표와 WorkoutRepo"`

### Task 2: 대화 상대 — 라우터, 디스패처, 두뇌 지시문, 도구 목록 (SP12-02)

**Files:**
- Modify: `src/my_planner/domain.py` (`Agent = Literal["secretary", "mate"]`, `RunContext.agent: Agent = "secretary"`)
- Modify: `src/my_planner/store/repos/conversations.py` (`Conversation.agent`, `open(..., agent=)`, `latest_open(kind, channel, agent="secretary")`, `recent(..., agent="secretary")`)
- Modify: `src/my_planner/tools/conversations.py` (`find_conversations`가 `repo.recent(..., agent=ctx.agent)`)
- Modify: `src/my_planner/store/repos/state.py` (`PendingInbound.agent: Agent = "secretary"`, `add_pending_inbound(..., agent: Agent = "secretary")`, `pending_inbound`이 읽음), `src/my_planner/loop/runner.py` (`resubmit_inbound`), 디스패처 `resubmit_app_row`
- Modify: `src/my_planner/harness/conversations.py` (스펙 5.2 표의 함수 모두에 `agent: Agent = "secretary"`)
- Modify: `src/my_planner/harness/dispatcher.py` (`Inbound.agent`, `route_app_message(..., agent=)`, `_app_conversation`, `_message_ctx`가 `conv.agent`를 `RunContext.agent`로, 프롬프트 조각 표 스펙 5.4, `new_conversation(agent)`)
- Modify: `src/my_planner/harness/brain.py` (`system_prompt_for(channel, agent="secretary")`)
- Create: `src/my_planner/harness/prompts/mate.md` (첫 판: 스펙 5.4 요지 1~9와 화면 조각 규칙 — `ui_block`·`ui_choice`·`ui_summary_card`만, 버튼은 `send`·`open`만, 한 답에 두 개까지. Task 3에서 9장 규칙을 더해 완성한다)
- Modify: `src/my_planner/tools/mcp_adapter.py` (`MATE_TOOLS`, `tool_names_for`)
- Modify: `src/my_planner/store/transcripts.py` (`Speaker`에 `"운동메이트"`, `_HEADER`에 화자와 ` @mate`, `read_range(..., drop_mate=False)`)
- Test: `tests/test_mate_routing.py` (새), `tests/test_mate_prompts.py` (새), `tests/test_transcript_channels.py` (더함), `tests/test_inbound_recovery.py` (더함)

**Interfaces:**
- Consumes: Task 1의 `agent` 칸.
- Produces:
  - `MATE_TOOLS: list[str] = ["record_condition", "find_conversations", "ui_block", "ui_choice", "ui_summary_card"]` (지금 있는 도구만. Task 3이 운동 도구 8개를 앞에 더해 스펙 5.3 표가 된다. 그래야 `_SPECS[name]`이 KeyError를 내지 않는다)
  - `tool_names_for(ctx)`: `moments` → `MOMENTS_TOOLS`, `NO_TOOL_KINDS` → `[]`, `ctx.agent == "mate"` → `list(MATE_TOOLS)`, 그 밖은 지금 그대로.
  - `ClaudeSdkBrain.system_prompt_for(channel: str, agent: Agent = "secretary") -> str`: 메이트는 `mate.md` 그대로, 비서는 지금 값 그대로(바이트까지 같다).
  - `Dispatcher.route_app_message(..., agent: Agent = "secretary")`, `Dispatcher.new_conversation(agent: Agent = "secretary") -> list[int]`
  - 원문 머리글: `### HH:MM 운동메이트 [12] #m-12-3 @app @mate`, 메이트 대화의 사용자 줄 `### HH:MM 사용자 [12] @app @mate`. (API 화자 변환은 Task 5)
  - `add_pending_inbound(..., agent: Agent = "secretary")`, `PendingInbound.agent`.

- [ ] **Step 1: 실패하는 테스트**
  - `test_mate_routing.py::test_mate_message_opens_own_conversation`: 비서 `chat`이 10분 전 열림 → 메이트 메시지 → 새 대화 `agent == "mate"`, 비서 대화는 열린 채.
  - `test_mate_routing.py::test_alternating_agents_keep_own_conversations` (Review Focus 1): 비서 → 메이트 → 비서(각 5분 간격) → 대화 2개, 비서 둘째 메시지는 첫 비서 대화에.
  - `test_mate_routing.py::test_close_expired_per_agent`: 비서 마지막 31분 전, 메이트 1분 전 → `close_expired()` 뒤 비서 닫힘·요약 대기열(`summary_pending`)에 있음, 메이트 열림.
  - `test_mate_routing.py::test_resume_other_agent_rejected`: 비서 대화 id를 `agent="mate"`로 고르면 `ValueError("agent_mismatch")` (API 400은 Task 5).
  - `test_mate_routing.py::test_resume_secretary_keeps_mate_open`, `test_new_conversation_closes_only_that_agent`, `test_continued_from_inherits_agent`(비서 쪽만).
  - `test_inbound_recovery.py::test_recovered_inbound_keeps_agent` (Review Focus 2): `add_pending_inbound(..., agent="mate")` 행을 남기고 `resubmit_inbound` → 메이트 대화로 처리, 비서 열린 대화는 그대로.
  - `test_mate_prompts.py::test_secretary_app_prompt_unchanged`: `system_prompt_for("app") == system.md + "\n\n" + channel_app.md.strip()`, `system_prompt_for("app", "mate") == load("mate.md")`. 지금 `test_prompts.py`가 그대로 통과.
  - `test_mate_prompts.py::test_mate_prompt_parts`: 메이트 첫 프롬프트에 `chat.md` 첫 줄 없음, `## 다른 곳에서 바뀐 것` 없음, `_recorded_condition()` 글 있음.
  - `test_mate_prompts.py::test_mate_tool_list`: `tool_names_for(RunContext(..., agent="mate", channel="app")) == MATE_TOOLS`, `RunContext(kind="summary", agent="mate")` → `[]`, `kind="moments"` → `MOMENTS_TOOLS`. (Task 3이 같은 테스트에 `set(MATE_TOOLS) & (set(TOOL_NAMES) | set(APP_ONLY_TOOLS)) == 공통 5`와 `(set(MATE_TOOLS) - 공통 5) & set(tool_names_for(비서 앱 ctx)) == set()`를 더한다.)
  - `test_transcript_channels.py::test_mate_header_parsed`: 메이트 줄 둘 + 비서 줄 하나 → `messages(conv)`가 3개로 가르고 화자 `운동메이트`; `recent_entries(mate_conv, 2)`가 메이트 대화 줄 둘; `erase_conversation`이 메이트 대화 줄만 지움.
  - `test_transcript_channels.py::test_secretary_read_drops_mate`: `read_range(..., drop_app_secretary=True, drop_mate=True)`에 메이트 사용자 줄 없음. `user_lines(day)`에는 있음.
- [ ] **Step 2:** `python -m pytest tests/test_mate_routing.py tests/test_mate_prompts.py tests/test_transcript_channels.py tests/test_inbound_recovery.py -q` → FAIL.
- [ ] **Step 3:** 구현. 디스패처의 프롬프트 조립(`instructions`, `_preamble`, `_elsewhere`)은 `conv.agent == "mate"`일 때 스펙 5.4 표대로 바꾼다. 메이트 앞머리 자리에는 `self._mate_preamble(now) -> str`을 두고 이 Task에서는 `""`를 돌려준다(Task 3이 `build_mate_preamble`로 채운다). 앱은 Task 5의 `features`가 생기기 전에는 메이트를 열 수 없으므로 빈 앞머리가 사용자에게 닿지 않는다. `read_transcript` 도구는 늘 `drop_mate=True`.
- [ ] **Step 4:** Step 2 명령 PASS, `python -m pytest -q` 전체 PASS.
- [ ] **Step 5:** `git commit -m "feat(sp12): 대화 상대 agent — 라우터·지시문·도구 목록"`

### Task 3: 메이트 도구, 앞머리, 지시문, 칩 (SP12-03)

**Files:**
- Create: `src/my_planner/tools/workout.py` (`WorkoutTools` mixin, 되돌리기 처리기, 상수)
- Modify: `src/my_planner/tools/core.py` (`Tools`가 `WorkoutTools` 상속, `workout: WorkoutRepo | None` 주입)
- Modify: `src/my_planner/tools/mcp_adapter.py` (`_SPECS`에 새 도구 8개 설명·스키마)
- Modify: `src/my_planner/tools/actions.py` (`ACTIONS`에 `drop_body_note`, `delete_workout_log`(확인), 둘의 `target`)
- Modify: `src/my_planner/tools/confirmations.py` (부록 A 확인 문구 다섯, 확인 카드 문구)
- Modify: `src/my_planner/status/xp.py` (`XP_WORKOUT_LOG: Final = 5  # X13`, `LABEL_WORKOUT_LOG: Final = "운동 기록"`)
- Create: `src/my_planner/harness/mate_context.py` (`build_mate_preamble`)
- Modify: `src/my_planner/harness/prompts/mate.md` (전문), Create: `chip_mate_today.md`, `chip_mate_log.md`, `chip_mate_plan.md`
- Modify: `src/my_planner/harness/chip_cards.py`, 디스패처 `chip_block` (메이트 칩 셋), `src/my_planner/api/models.py` (`ChipKey`에 `"mate_today", "mate_log", "mate_plan"`), `tests/test_prompts.py::test_chip_prompts_are_spec_text` (키 집합 = SP9c 4.3 다섯 + 메이트 셋)
- Modify: `src/my_planner/app.py` (`HabitsRepo(conn, clock)` 옆에 `WorkoutRepo(conn, clock)`를 `Tools`에 주입)
- Test: `tests/test_tools_workout.py` (새), `tests/test_mate_prompts.py` (더함)

**Interfaces:**
- Consumes: Task 1 `WorkoutRepo`, Task 2 `RunContext.agent`.
- Produces (`WorkoutTools`, 모두 `dict` 결과, 오류는 `_err(문구)`):
  - `get_mate_context(ctx) -> {"text": str}` (= `build_mate_preamble` 결과)
  - `save_body_note(ctx, kind, text, id=None)` → `{"note": {"id", "kind", "text"}}`. 활동 없음. 30개·같은 글·가리기(`harness.redact.redact`).
  - `drop_body_note(ctx, id)` → 활동 `body_note_dropped`, target `body_note:<id>`, `undo {"note_id"}`.
  - `set_workout_plan(ctx, title, note, sessions)`: `sessions`는 `[{"position": int, "label": str, "weekdays": list[int] | null, "items": [PlanItem 칸]}]`(MCP 스키마도 같음). 도구가 `position` 1..N 중복 없음·연속을 검사하고 `position` 순으로 `replace_plan`에 넘긴다. 결과 `{"plan": {...} | None}`. 지금 플랜이 없는데 `sessions=[]`이면 아무것도 바꾸지 않고 `{"plan": None}`(활동 없음). 활동 `workout_plan_set`, targets `["workout_plan:current", "workout_plan:<앞>", "workout_plan:<새>"]`, `undo {"new_id", "prev_id"}`(스펙 7.2) 또는 비우기 `{"cleared_id"}`. `workout_plan_set`은 `U3_PER_TARGET`에 넣지 않는다.
  - `log_workout(ctx, title, date=None, session_id=None, effort=None, note=None, items=None)` → 활동 `workout_logged`, X13(`status.grant(..., source_kind="workout_log", source_ref=f"workout_day:{d}", amount=XP_WORKOUT_LOG, label=LABEL_WORKOUT_LOG, area="health", gain=ctx.xp)`, `logical_date=d`).
  - `update_workout_log(ctx, id, **fields)` → `workout_log_updated`, `undo {"log_id", "before"}`.
  - `delete_workout_log(ctx, id)` → 두뇌 차례면 `_request_confirm(ctx, "delete_workout_log", {"id": id}, "운동 기록 '{title}'({MM-DD})를 지울까요?", ...)`, 확인 뒤 `workout_log_deleted`.
  - `list_workouts(ctx, days=28, name=None)` → `{"logs": [...]}` (`days` 1~180).
  - `build_mate_preamble(*, now, tz, boundary, conditions, body, events, workout) -> str`: 스펙 5.5 형식과 줄 수 상한(일정 8, 메모 30, 최근 기록 14일·8개). 빈 섹션 문구 "기록 없음" / "없음" / "아직 없음".
  - 칩 키: `mate_today` "오늘 뭐 할까?", `mate_log` "운동 기록하기", `mate_plan` "플랜 고치기" → `chip_mate_today.md` 등.
  - `MATE_TOOLS`를 스펙 5.3 표 전체로 넓힌다: 앞에 `"get_mate_context", "save_body_note", "drop_body_note", "set_workout_plan", "log_workout", "update_workout_log", "delete_workout_log", "list_workouts"`.
  - 오류 문구(부록 A): `MSG_NOTES_FULL = "몸 메모는 30개까지예요. 오래된 것을 정리해 주세요."`, `MSG_LOG_RANGE = "일주일 안의 기록만 남길 수 있어요."`.

- [ ] **Step 1: 실패하는 테스트** (`tests/test_tools_workout.py`, 시계 `kst(2026, 10, 31, 10, 0)` 토요일)
  - `test_log_date_window`: `2026-10-25` 허용, `2026-10-24` → `MSG_LOG_RANGE`, `2026-11-01` → `MSG_LOG_RANGE`; 시계 `kst(2026, 11, 1, 3, 59)`에서 `2026-10-25` 허용, `kst(2026, 11, 1, 4, 0)`에서 `2026-10-25` 거절.
  - `test_log_xp_once_per_day`: 10-31 기록 둘 → 원장 `workout_log` 1행 amount 5, `source_ref == "workout_day:2026-10-31"`; 첫 기록 삭제 뒤에도 1행; `date="2026-10-30"` 기록 → 2행.
  - `test_log_items_limits`: 운동 줄 20개 허용, 21개 거절; `reps=0`, `weight_kg=501` 거절; `update_workout_log`로 무게를 바꾸고 되돌리면 앞 값.
  - `test_plan_undo_latest_only`: A→B→C 뒤 A→B 활동 되돌리기 → superseded(U3), B→C 되돌리기 → 지금 플랜 B.
  - `test_plan_undo_after_clear`: A 비우기 → B 만들기 → A 비우기 되돌리기 거절; B 만들기 되돌리기 → `current_plan() is None`.
  - `test_set_plan_rejects_partial_shapes` (Review Focus 3): `items=[]` 세션, 같은 `position`, 8번째 세션, `weight_kg=0.3`, `weekdays=[7]` → 각각 오류이고 DB 변화 없음.
  - `test_body_note_limits`: 30개 뒤 31번째 → `MSG_NOTES_FULL`; 같은 kind+text → 새 행 없이 기존 노트.
  - `test_body_note_is_redacted` (Review Focus 5): "헬스장 회비 계좌 110-123-456789" → 저장 글에 `[가림]`이 있고 `456789` 없음.
  - `test_body_note_save_has_no_activity_drop_has`: 저장 뒤 활동 0, 지우기 뒤 `body_note_dropped` 1개이고 `summary == "몸 메모 지움"`, 되돌리기로 복원.
  - `test_delete_log_needs_confirm_from_brain`: 두뇌 ctx → `needs_confirm` 토큰, 기록 그대로.
  - `test_find_conversations_scoped_by_agent`: 비서·메이트 끝난 대화 하나씩 → 메이트 ctx 결과는 메이트 것만.
  - `test_mate_preamble_sections`: 데이터 없음 → 다섯 섹션 모두 빈 문구; 메모 31개(하나 삭제)·기록 9개 → 30줄·8줄; 15일 전 기록과 지운 기록은 없음.
  - `test_mate_prompts.py::test_mate_texts_have_no_banned_words`: `mate.md`, `chip_mate_*.md`, 부록 A 문구에 `APP_BANNED_WORDS`·"%"·"빠진" 없음.
- [ ] **Step 2:** `python -m pytest tests/test_tools_workout.py tests/test_mate_prompts.py -q` → FAIL.
- [ ] **Step 3:** 구현. `mate.md`는 스펙 5.4 요지 1~9와 9장 규칙(9.1~9.4)을 문장으로, 9.4 안전을 맨 앞 "꼭 지킬 것"에. 메이트 칩 글은 부록 A("오늘 뭐 할까?", "운동 기록하기", "플랜 고치기").
- [ ] **Step 4:** Step 2 명령 PASS, 전체 PASS.
- [ ] **Step 5:** `git commit -m "feat(sp12): 메이트 도구·앞머리·지시문·칩"`

### Task 4: 경험치 원장 표시, 활동 보너스, 이룬 순간 입력 (SP12-04)

**Files:**
- Modify: `src/my_planner/status/activity.py` (`WORKOUT_POINT = Fraction(1, 2)`, 점수표에 운동 기록 날, `ActivityCounts.workout_days`)
- Modify: `src/my_planner/store/repos/status.py` (`activity_rows`가 운동 기록 날도 읽음), `src/my_planner/status/snapshot.py` (`_bonuses`가 넘김)
- Modify: `src/my_planner/api/models.py` (`stats[].activity.workout_days: int`)
- Modify: `src/my_planner/harness/moments.py`, `src/my_planner/harness/prompts/moments.md`, `src/my_planner/tools/moments.py` (`## 운동 기록` 섹션, 출처 `workout:<id>`, `has_data`)
- Test: `tests/test_status_activity.py`, `tests/test_status_xp.py`, `tests/test_moments_job.py` (더함)

**Interfaces:**
- Consumes: Task 1 `WorkoutRepo.log_days`(같은 SQL을 `activity_rows`에 둔다), Task 3의 X13 원장 행.
- Produces: `ActivityRows.workout_days: frozenset[date]`, `area_points(tasks, checks, body, today, *, tz, boundary, workout_days: frozenset[date] = frozenset())`, `activity_counts(..., workout_days: frozenset[date] = frozenset())`, `ActivityCounts.workout_days: int = 0`, API `stats[].activity.workout_days: int`.

- [ ] **Step 1: 실패하는 테스트**
  - `test_status_activity.py::test_workout_day_adds_half_to_health`: 오늘 기록 2개 → 건강 `p = 1/2`; 습관 체크 4개(건강) + 기록 → 2.5; 습관 체크 6개 + 기록 → 3(하루 상한); 삭제한 기록만 있는 날 0.
  - `test_status_activity.py::test_workout_days_count`: 28일 안 3일 기록 → `workout_days == 3`.
  - `test_status_xp.py::test_x13_label_in_recent`: 상태창 최근 경험치 줄의 라벨 "운동 기록", 제목 없음.
  - `test_moments_job.py::test_workout_section_and_source`: 그날 기록 "하체" → 입력에 `## 운동 기록\n- 하체`, `save_moments`가 `sources=["workout:<id>"]` 받음, 다른 날 기록 id는 거절. 기록만 있는 날도 순간 작업이 돈다.
- [ ] **Step 2:** `python -m pytest tests/test_status_activity.py tests/test_status_xp.py tests/test_moments_job.py -q` → FAIL.
- [ ] **Step 3:** 구현.
- [ ] **Step 4:** PASS, 전체 PASS. `python -m my_planner schema` 결과로 `web/app/src/api/schema.json`과 대시보드 `schema.json`을 다시 만들고 `tests/test_dashboard_fixtures.py` PASS.
- [ ] **Step 5:** `git commit -m "feat(sp12): X13 운동 기록 경험치, 건강 보너스, 이룬 순간 입력"`

### Task 5: HTTP API (SP12-05)

**Files:**
- Create: `src/my_planner/api/workout.py` (`get_workout`)
- Modify: `src/my_planner/api/server.py` (`GET /workout` 등록), `src/my_planner/api/chat.py` (`ChatRequestBody.agent`, `post_new_conversation` 본문 `agent`, `agent=mate`면 `/` 명령을 해석하지 않음, 칩 키와 상대가 맞지 않으면 400), `src/my_planner/api/read.py` (`get_conversations?agent=`, 대화 기록 화자 `mate`), `src/my_planner/api/models.py` (`Workout*` 모델, `Health.features: list[str] | None = None`, 대화 기록 `speaker: Literal["user", "secretary", "mate"]`), `src/my_planner/api/health.py` (`features=["mate"]`)
- Test: `tests/test_api_workout.py` (새), `tests/test_api_chat.py` (더함)

**Interfaces:**
- Produces: `GET /api/v1/workout` → `Workout{plan: WorkoutPlan | null, logs: WorkoutLogOut[], notes: BodyNoteOut[]}` (스펙 11.3 필드 그대로, `logs`는 28일). `POST /chat` `agent?: "secretary" | "mate"`. `GET /conversations?agent=mate`. `POST /conversations/new` `{agent?}`. `GET /health` `features: ["mate"]`.

- [ ] **Step 1: 실패하는 테스트**
  - `test_api_workout.py::test_get_workout_empty` → `{"plan": null, "logs": [], "notes": []}`.
  - `test_api_workout.py::test_get_workout_shapes`: 플랜 1·기록 2(하나 29일 전)·메모 1 → `logs` 1개, 숫자 칸 그대로.
  - `test_api_workout.py::test_actions_drop_note_and_delete_log`: `POST /actions drop_body_note` → `applied` + 되돌리기 id. `delete_workout_log`는 `ActionSpec(needs_confirm=workout_log_delete_needs_confirm, target=...)`라(스펙 8.2, 이룬 순간 지우기와 같은 방식) 첫 요청 `needs_confirm` + 토큰, 토큰과 함께 두 번째 → `applied`.
  - `test_api_workout.py::test_health_features_has_mate`.
  - `test_api_chat.py`: `agent="mate"` 요청이 메이트 대화를 열고 `start` 메시지 id가 그 대화; 잘못된 `agent` 값 → `400 invalid_request`; 비서 대화 id를 `resume_conversation_id`로 `agent="mate"` → `400 invalid_request` "이 대화는 다른 상대예요."; `agent="mate"` + `chip="todo"` 또는 `agent="secretary"` + `chip="mate_log"` → `400 invalid_request`; `agent="mate"`의 `/plan 하체`는 두뇌로 가고 계획 대화를 열지 않음; `GET /conversations?agent=mate`가 메이트 것만; 메이트 대화 기록의 화자 `mate`.
- [ ] **Step 2:** `python -m pytest tests/test_api_workout.py tests/test_api_chat.py -q` → FAIL.
- [ ] **Step 3:** 구현. 로그는 경로 틀과 상태 코드만.
- [ ] **Step 4:** PASS, 전체 PASS, `cd web/app && npm run gen:types` 후 `git diff --stat src/api` 에 `schema.json`, `types.gen.ts`만.
- [ ] **Step 5:** `git commit -m "feat(sp12): /workout API, 채팅 agent 필드, health features"`

### Task 6: 앱 — 채팅 시트 상대 고르기와 퀵 칩 (SP12-06)

**Files:**
- Modify: `web/app/src/chat/ChatSheet.tsx`, `web/app/src/chat/sheetContext.ts` (`sheetState`를 상대마다: `{secretary: {pickedConversationId, freshSince}, mate: {...}}`, `openChat(opts?: {agent?: Agent})`), `web/app/src/pages/_app.tsx`(시트 여는 자리), `web/app/src/chat/transport.ts` (`agent` 본문), `web/app/src/chat/ConversationList.tsx` (`agent` 쿼리), `web/app/src/chat/history.ts`, `web/app/src/chat/quickChips.ts` (상대별 칩, `WIRE`에 `mate_today`·`mate_log`·`mate_plan`), `web/app/src/chat/MessageView.tsx` (화자 `mate` 머리 줄 "운동메이트"), `web/app/src/lib/copy.ts` (부록 A)
- Create: `web/app/src/chat/agent.ts` (`type Agent = "secretary" | "mate"`, `loadAgent(): Agent`, `saveAgent(a: Agent): void` — 둘 다 try/catch, 실패 시 `"secretary"`)
- Test: `web/app/src/chat/agent.test.ts`, `web/app/src/chat/ChatSheet.test.tsx`, `web/app/src/chat/contract.test.tsx` (더함)

- [ ] **Step 1: 실패하는 테스트**
  - `agent.test.ts`: `localStorage` 없음/던짐 → `"secretary"`; `saveAgent("mate")` 뒤 `"mate"`.
  - `ChatSheet.test.tsx` `switching to mate changes list, chips and request agent`: `Segmented`에서 "운동메이트" → 칩 글 셋이 부록 A, 보낸 요청 본문 `agent: "mate"`, 목록 요청 `agent=mate`.
  - `ChatSheet.test.tsx` `hides mate when health has no features` (Review Focus 4): `ConnectionProvider`의 `health.features` 없음 → `Segmented` 없음, 비서 채팅 그대로.
  - `ChatSheet.test.tsx` `picked conversation is per agent`: 비서 지난 대화를 고른 뒤 메이트로 바꿔 보내면 `resume_conversation_id` 없음, 다시 비서로 바꾸면 고른 대화 그대로.
  - `ChatSheet.test.tsx` `new conversation posts agent`.
  - `contract.test.tsx`: `ChatRequestBody`에 `agent` 필드가 스키마와 맞음.
- [ ] **Step 2:** `cd web/app && npx vitest run src/chat` → FAIL.
- [ ] **Step 3:** 구현. 새 색 없음, `Segmented` 부품 그대로(DESIGN.md).
- [ ] **Step 4:** PASS, `npm test` 전체 PASS, `npm run typecheck && npm run lint:copy` 깨끗.
- [ ] **Step 5:** `git commit -m "feat(app): 채팅 상대 고르기(비서/운동메이트)와 메이트 칩"`

### Task 7: 앱 — 운동 화면 (SP12-07)

**Files:**
- Create: `web/app/src/pages/workout.tsx`, `web/app/src/screens/Workout.tsx`, `web/app/src/screens/Workout.module.css`
- Modify: `web/app/src/screens/More.tsx` (줄 "운동", `features`에 `mate`일 때만), `web/app/src/lib/copy.ts`, `web/app/e2e/routes.ts`
- Create: `web/app/e2e/workout-mate.spec.ts`
- Test: `web/app/src/screens/Workout.test.tsx`, `web/app/src/screens/More.test.tsx` (더함)

**Interfaces:**
- Consumes: Task 5 `GET /workout`, `POST /actions`(`drop_body_note`, `delete_workout_log` + 확인 토큰), `useSnapshotted`(ADR 0009), `SwipeRow`, `ConfirmSheet`, Task 6의 `openChat({agent: "mate"})`.

- [ ] **Step 1: 실패하는 테스트** (`Workout.test.tsx`)
  - `empty state shows talk button`: 플랜 없음 → "운동메이트와 이야기하면서 플랜을 짜요"와 버튼, 누르면 시트가 `agent: "mate"`로 열림.
  - `plan sessions and weekdays render`: 세션 2개, 요일 "월·목".
  - `log expands to items` / `log delete asks then applies`(확인 시트 → 토큰 요청).
  - `note delete shows undo toast`.
  - `offline shows snapshot`: 연결 실패 + 저장한 스냅샷 → 그 내용과 오프라인 안내.
  - `no calendar or counts`: 화면에 "회", "%", 요일 격자 없음.
  - `More.test.tsx` `workout row only with mate feature`.
- [ ] **Step 2:** `cd web/app && npx vitest run src/screens/Workout src/screens/More` → FAIL.
- [ ] **Step 3:** 구현.
- [ ] **Step 4:** PASS. `npm run e2e -- e2e/workout-mate.spec.ts e2e/design.spec.ts`(빌드 포함. 가짜 BE: 메이트 대화 → `ui_block` 플랜 카드 → 더보기 → 운동 화면에 같은 플랜; 라이트·다크) → 실패 0.
- [ ] **Step 5:** `git commit -m "feat(app): 운동 화면"`

### Task 8: 마무리 — 문서, 노트북 프롬프트 평가 체크리스트 (SP12-08, SP12-09)

부록 A 문구는 Dahun이 2026-10-31에 확정했으므로 SP12-08 문구 확인은 이 Task의 PR 본문 "부록 A 밖 문구" 목록으로 대신한다.

**Files:**
- Modify: `README.md` (기능 목록에 운동메이트 한 줄)
- Create: `/mnt/project-files/my-planner-docs/sp12/laptop-checklist.md` (저장소 밖, 공유 폴더)
- Modify: `docs/superpowers/specs/2026-10-31-sp12-workout-mate-design.md` (변경 기록: 구현 중 바뀐 결정)

- [ ] **Step 1:** 노트북 체크리스트에 스펙 12장 프롬프트 평가 시나리오 8개를 하나씩: 보낼 문장, 기대(예: "가슴이 답답해" → 운동 멈춤 + 진료 권유, 진단 없음). dev BE(`E:\my-planner-dev`, 스테이징 앱)에서 Dahun이 해 볼 순서.
- [ ] **Step 2:** `python -m pytest -q` PASS, `cd web/app && npm test && npm run e2e` PASS.
- [ ] **Step 3:** `git commit -m "docs(sp12): README, 변경 기록"`, 체크리스트 파일은 공유 폴더에 쓰고 10초 뒤 다시 읽어 확인.
