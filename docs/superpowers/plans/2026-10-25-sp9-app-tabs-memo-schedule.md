# SP9 앱 탭 개편 · 스케줄 · 메모 · 대화 목록 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan ticket-by-ticket. Steps use checkbox (`- [ ]`) syntax for tracking. 티켓 하나를 끝낼 때마다 `.claude/agents/code-reviewer.md`로 리뷰하고, 지적을 반영한 뒤 다음 티켓으로 간다.

**Goal:** 운영 앱의 아래 탭을 `오늘 | 할 일 | 스케줄 | 메모`로 바꾸고, 스케줄(반복·알림·놓친 알림·아이폰 캘린더 구독), 메모, 체크인 시간 바꾸기, 대화 목록(요약·잇기·지우기·말아 넣기), 퀵 칩을 더한다. 새 대화는 다른 대화의 원문을 읽지 않는다.

**Architecture:**
- 새 표 셋: `memos`(016), `events`·`event_skips`·`event_reminders`(017), 대화 칸과 `conversation_sessions`(018). 017 뒤 Python 훅이 시각 있는 열린 할 일을 일정으로 옮긴다(`migrate()` 순서 바꿈).
- 쓰기는 지금처럼 두 갈래뿐이다: 두뇌 갈래(`Tools`의 새 도구 9개, 앱 대화에만)와 즉시 갈래(`apply_action`의 새 동작). 활동·되돌리기는 같은 트랜잭션.
- 일정은 정의 한 행 + 건너뛴 날만 저장하고, 날짜별 일정은 순수 함수 `expand()`로 펼친다. 알림은 1분 tick의 `remind_events()`가 두뇌 없이 보낸다.
- 대화 하나 = 두뇌 세션 하나(ADR 0014). 닫힐 때 도구 없는 두뇌 호출 한 번으로 제목·요약을 만들고, 라우터 0번 규칙(`resume_conversation_id`)으로 지난 대화를 잇는다.
- 앱은 새 화면 `/more/`, `/schedule/`, `/memos/`, `/memos/view/`와 채팅 시트의 대화 목록·퀵 칩을 더한다.

**Tech Stack:** SP3-4·SP5·SP7과 같다(Python 3.12, aiohttp, SQLite FTS5, Claude Agent SDK / Next.js 15 Pages Router 정적 내보내기, Vitest, Playwright). 새 의존성 없음(`.ics`는 손으로 쓴다).

**Spec:** [`docs/superpowers/specs/2026-10-25-sp9-app-tabs-memo-schedule-design.md`](../specs/2026-10-25-sp9-app-tabs-memo-schedule-design.md) (v2.1, develop `78ea86c`). 상위: [SP3-4 스펙](../specs/2026-10-24-sp3-4-life-curve-dashboard-design.md)(API 계약 정본), [SP5](../specs/2026-10-24-sp5-ops-app-design.md), [SP6 채팅 생성형 UI](../specs/2026-10-24-sp6-chat-generative-ui-design.md), [SP1](../specs/2026-10-23-sp1-secretary-core-design.md). 용어 [`GLOSSARY.md`](../../../GLOSSARY.md), 결정 [ADR 0014](../../adr/0014-one-conversation-one-session-share-by-summary.md), [ADR 0015](../../adr/0015-schedule-is-not-a-task.md).
- 스펙과 이 계획이 다르면 스펙이 맞다. 티켓은 스펙을 다시 쓰지 않고 절을 가리킨다.

## Global Constraints

- (11장) **SP8 마이그레이션 013~015가 develop에 머지되기 전에는 SP9-03, SP9-05, SP9-09를 시작하지 않는다.** SP9-00의 빈 번호 거부 때문에 013~015 없는 브랜치에서는 016만 있어도 모든 테스트가 `MigrationGapError`로 멈춘다. 그래서 SP9-03 브랜치는 SP8 머지 뒤의 `origin/develop`에서 딴다. 머지 순서는 016 → 017 → 018.
- (8장) 체크인 시각을 바꾸면 노트북 깨우기 작업(`my-planner-wake`)의 트리거도 바뀌어야 한다(SP9-02, 스파이크 S4).
- (5.1) 시각은 현지 날짜 + `"HH:MM"`, 시간대는 `settings.timezone`(Asia/Seoul). 하루 종일 알림 기준 09:00. 매달 29~31일은 그 달 마지막 날로 옮긴다. 기간 조회 최대 62일. 살아 있는 일정 300개.
- (5.1) `remind_min ∈ {0, 10, 30, 60, 1440, NULL}`, 기본 10(하루 종일은 0). 하루 종일에서 10·30·60은 422 `remind_invalid`.
- (5.3) 늦은 알림 최대 3개, 거슬러 보기 7일, 하루 알림 상한 30(`limits.daily_event_reminders`), `daily_proactive_messages`에 세지 않음, 멈춤 중에도 보냄. 공백 ≤ `RESUME_GAP`(3분)이면 깨어남 아님.
- (6.1) 메모 본문 1~20,000자, 메모 2,000개, 고정 10개, 제목 = 첫 줄 서식 뺀 앞 40자, 지운 메모 30일 보관, trigram 검색(3글자 미만은 LIKE).
- (6.3·7.5) 두뇌에 주는 메모·요약은 `redact()`를 거친다. 두뇌에 원문 대화를 주는 도구는 없다. 메모 고치기·지우기 도구는 없다.
- (7.2·7.4) 요약 하루 15개(`limits.daily_summaries`), 제목 20자, 요약 600자. 말아 넣기는 사용자 메시지 31번째 호출 전(`limits.rollup_user_messages = 30`), 최근 6줄(`limits.rollup_tail_lines = 6`). 앱 통로만.
- (8장) 체크인 시간 아침 05:00~11:30, 저녁 15:00~23:30, 10분 단위. "오늘" = 논리적 날짜. 주간 회고는 주말 저녁을 따라간다.
- (9.6) 채팅 활동 토스트만 6초(`showFor(t, 6000)`), 다른 토스트는 `SHOW_MS = 4000` 그대로.
- (Q14) 텔레그램 도구 목록과 텔레그램 화면은 바꾸지 않는다. 새 도구 9개는 `APP_ONLY_TOOLS`에만.
- (10장) 새 문구는 스펙 10장 그대로. 금지어 검사(SP5 10장, SP7이 더한 것 포함)에 10장 문구를 넣는다.
- (9장) 새 화면 CSS 모듈은 모두 `web/app/src/pages/_app.tsx`에서 불러온다(CSP). 색은 테마 토큰만, 영역색은 작은 점으로만(DESIGN.md). 새 아이콘은 24px, 선 1.75, 끝 둥글게, 이모지 없음.
- 카탈로그 판 번호(`UI_CATALOG_VERSION`, 지금 `2026-10-24.4`)는 BE PR 머지 순서로 다음 번호.
- SP3-4·SP1 Global Constraints(단일 작성자, `mode=ro` 읽기, 시각 UTC 저장, 논리적 날짜 04:00, 영역 6개)는 그대로다.

## 작업 방식

- TDD와 명령은 SP7 계획 "작업 방식" 그대로: 슬라이스마다 테스트 → `python -m pytest <노드 id> -v` FAIL → 구현 → PASS.
- 티켓 끝 검증(BE): `python -m pytest -q` → `0 failed`, `ruff check src tests` → `All checks passed!`. 앱: `cd web/app && npm run typecheck && npm run lint:copy && npm test && npm run test:tz && npm run build && npm run check:csp` → 모두 통과.
- 생성자 새 인자는 키워드 전용, 기본값 `None`: `Tools(memos=…, events=…)`, `build_preamble(events=…)`.
- BE 응답 모양을 바꾼 티켓은 `npm run gen:types`로 `schema.json`·`types.gen.ts`를 다시 만든다.
- 브랜치는 `origin/develop`에서, PR 대상은 `develop`(release flow #149).
- 시험 날짜: 2026-10-26(월)~30(금), 2026-10-31(토), 2026-11-01(일). 매달 끝날 시험은 2027-01-31 → 2027-02-28.

## Review Focus

1. **새벽 00:00~03:59의 일정과 체크인 시간**: 10/27 01:00 일정은 현지 날짜 10/27(논리적 날짜 10/26)이다. 스케줄 띠와 `.ics`는 현지 날짜, 오늘 화면의 "오늘 일정"은 논리적 날짜 기준이다. → SP9-05 `test_today_events_use_logical_day_0100_belongs_to_previous`, SP9-02 `test_change_at_0030_targets_next_logical_day`
2. **같은 일정을 앱에서 고치는 사이 알림 tick이 돎**: 13:29에 30분 전 알림 일정의 시각을 14:00→15:00으로 바꾸면, 13:30 tick이 옛 시각으로 보내지 않는다. → SP9-06 `test_edit_just_before_remind_at_uses_new_time`
3. **노트북이 며칠 꺼졌다 켜짐**: 9일 공백 뒤 첫 tick은 7일 안만 판정하고, 이미 시작한 것은 오늘 날짜만 오늘 화면에 보인다. 푸시는 최대 3개. → SP9-06 `test_nine_day_gap_judges_seven_days_pushes_at_most_three`
4. **메모 제목이 서식뿐이거나 공백뿐**: 첫 줄이 `- [ ]`나 빈 줄이면 제목은 서식을 뺀 다음 비지 않은 줄, 그것도 없으면 "제목 없는 메모". → SP9-03 `test_title_skips_empty_and_markup_only_lines`
5. **다시 연 대화를 보는 동안 체크인 푸시가 옴**: 앱이 `resume_conversation_id`를 싣고 있으면 그 대화로 가고, 체크인 칩이나 체크인 화면에서 보낸 메시지(`checkin_id`)는 회차로 간다. → SP9-09 `test_checkin_id_without_resume_goes_to_run_and_both_follow_rule_0`, SP9-10 `test_checkin_chip_sends_checkin_id_not_resume`

규칙(5번): 스펙 7.3대로 0번 규칙이 1~5번보다 먼저다. 대신 **앱은 체크인 칩·체크인 화면에서 보내는 메시지에는 `resume_conversation_id`를 싣지 않고 `checkin_id`만 싣는다.** 그래서 두 값이 함께 오는 일은 앱에서 없다. 둘 다 오면(다른 클라이언트) 0번 규칙대로 고른 대화로 간다.

---

## File Structure

```
src/my_planner/
  store/db.py                               # SP9-00: MigrationGapError / SP9-05: 훅 순서, tz 인자
  store/migrations/016_memos.sql            # SP9-03
  store/migrations/017_events.sql           # SP9-05
  store/migrations/018_conversation_summaries.sql  # SP9-09
  store/migrations/hooks.py                 # SP9-05: HOOKS = {17: after_017}
  store/repos/memos.py                      # SP9-03: Memo, MemosRepo
  store/repos/events.py                     # SP9-05: Event, Occurrence, EventsRepo, expand()
  store/repos/conversations.py              # SP9-09: 칸·지우기·세션 이력
  store/transcripts.py                      # SP9-09: erase_conversation()
  store/exports.py                          # SP9-03: export_memos
  tools/memos.py, tools/events.py           # SP9-03, SP9-05: MemoTools, EventTools (mixin, Tools가 상속)
  tools/conversations.py                    # SP9-09: find_conversations
  tools/checkin_times.py                    # SP9-02: set_checkin_time
  tools/{core,actions,activity,confirmations,mcp_adapter,ui}.py
  loop/schedule.py                          # SP9-02: checkin_time(), due_between가 쓴다
  loop/reminders.py                         # SP9-06: remind_events()
  loop/runner.py                            # SP9-06: tick에서 부른다
  harness/{context,conversations,dispatcher}.py, harness/summaries.py  # SP9-05(앞머리), SP9-09
  harness/prompts/{summarize.md,channel_app.md}
  api/{read,models,server,actions,chat}.py, api/calendar.py  # 각 BE 티켓, SP9-08
  config.py, config.toml                    # 13장 limits
web/app/src/
  components/{TabBar,MoreButton,LargeTitle,icons,Toast}.tsx
  pages/{more,schedule,memos}.tsx, pages/memos/view.tsx
  screens/{More,Schedule,ScheduleWeek,MonthCalendar,EventSheet,Memos,MemoEditor,CheckinTimes,CalendarSubscribe}.tsx
  chat/{ChatSheet,MessageView,hideCoveredActivity,transport,ConversationList,QuickChips,quickChips}.ts(x)
  ui/chat/{Result,PeriodList}.tsx, ui/components/Events.tsx, ui/registry.tsx
  api/actions.ts, lib/copy.ts, pages/_app.tsx
docs/superpowers/specs/2026-10-24-sp6-chat-generative-ui-design.md  # SP9-01: 5.5.5/F6 활동 줄 규칙
docs/superpowers/specs/2026-10-24-sp3-4-life-curve-dashboard-design.md  # SP9-09: 7.2 표 0번 규칙
```

## 티켓 지도

| # | 티켓 | 막는 티켓 | 라벨 |
|---|---|---|---|
| SP9-00 | 스파이크 S1(빈 번호 거부)~S3 | 없음 | `ready-for-agent` + `needs-laptop`(S2·S3의 노트북 부분, 막지 않음) |
| SP9-01 | 앱: 더보기·오른쪽 위 아이콘, 활동 한 줄, 토스트 되돌리기 | 없음 | `ready-for-agent` |
| SP9-02 | 체크인 시간: `schedule_override`, API, 도구, 설정 화면 | 없음 | `ready-for-agent` |
| SP9-03 | 메모 BE: 016, 저장소, API, 도구, 내보내기 | SP9-00, **SP8 013~015 머지** | `ready-for-agent` |
| SP9-04 | 앱: 메모 탭, 쓰기 화면, 탭 `기록` → `메모` | SP9-03, SP9-01 | `ready-for-agent` |
| SP9-05 | 스케줄 BE: 017, 훅, `expand`, API, 도구, `ui_events`, 앞머리, 할 일 시각 빼기 | SP9-03 | `ready-for-agent` |
| SP9-06 | 알림 tick R1~R5, 푸시 문구 | SP9-05 | `ready-for-agent` |
| SP9-07 | 앱: 스케줄 탭, 오늘 블록, 탭 막대 최종 | SP9-05, SP9-04 | `ready-for-agent` |
| SP9-08 | `.ics` 구독 주소와 설정 묶음 | SP9-05 | `ready-for-agent` |
| SP9-09 | 대화 BE: 018, 요약, 0번 규칙, 말아 넣기, 지우기, `find_conversations` | SP9-05 | `ready-for-agent` |
| SP9-10 | 앱: 대화 목록, 새 대화, 퀵 칩 | SP9-09, SP9-07 | `ready-for-agent` |
| SP9-11 | 수용 시험(노트북: 실제 푸시, 노트북 끄고 켜기, 아이폰 캘린더) | 전부 | `needs-laptop` |
| SP9-12 | Dahun 확인: 스펙 15장 13개, 10장 문구 | 없음(바뀌면 후속 PR) | **Dahun 검토** |

**완료 조건 → 티켓**: 1 → SP9-01·04·07 / 2 → SP9-05·06·07 / 3 → SP9-06 / 4 → SP9-05·07 / 5 → SP9-08 / 6 → SP9-03·04 / 7 → SP9-03 / 8 → SP9-09·10 / 9 → SP9-09 / 10 → SP9-09 / 11 → SP9-10 / 12 → SP9-01 / 13 → SP9-02 / 14 → 모든 티켓의 끝 검증. 클라우드 끝-끝은 SP9-09의 `test_sp9_story`, 노트북은 SP9-11. GLOSSARY의 `_SP9 초안_` 표시는 SP9-11이 끝날 때 뗀다.

- BE 줄: SP9-00 → (SP8 머지) → SP9-03 → SP9-05 → (SP9-06, SP9-08, SP9-09). SP9-02는 어느 때나.
- 앱 줄: SP9-01 → SP9-04 → SP9-07 → SP9-10. SP9-01은 바로 배포해 Dahun이 써 본다.

---

### 티켓 SP9-00: 스파이크와 빈 번호 거부

**목표:** 스펙 12장 S1~S3, 11장 순서 위험.
**막는 티켓:** 없음

**Files:** Modify `store/db.py`. Create `scripts/spike_session_path.py`. Test `tests/test_migrations.py`. 결과는 `docs/spikes/2026-10-25-sp9.md`.

**Interfaces**
- Produces: `class MigrationGapError(RuntimeError)`. `migrate()`는 `_migrations()`의 번호가 1부터 빈칸 없이 이어지지 않으면 적용 전에 `MigrationGapError("missing migration 013")`을 낸다. `scripts/spike_session_path.py <session_id>`: SDK 세션 파일 경로를 한 줄로 찍고, 없으면 종료 코드 1.

**Slices**
- [ ] `test_gap_in_migration_numbers_refuses`(`monkeypatch`로 `MIGRATIONS_DIR`을 임시 폴더로, 001~012와 016 → `MigrationGapError`, `user_version` 그대로), `test_contiguous_numbers_apply`
- [ ] S2: 클라우드에서 `python -c "import sqlite3; c=sqlite3.connect(':memory:'); c.execute(\"create virtual table t using fts5(x, tokenize='trigram')\"); print(sqlite3.sqlite_version)"` → 3.34 이상, 오류 없음. 노트북 결과는 Dahun에게 한 줄로 받는다(막지 않음).
- [ ] S3: 세션 파일 경로 스크립트. 노트북 확인과 아이폰 `.ics` 구독 확인은 SP9-11로 넘긴다.
- [ ] S4(노트북, 막지 않음): 관리자 권한 없이 BE 프로세스(같은 사용자)가 `my-planner-wake` 작업만 다시 등록할 수 있는지. `powershell -File scripts/update_wake_task.ps1 -DryRun` → "would set N triggers". 안 되면 SP9-02의 실패 경로(설정 화면 안내 줄)만 쓴다.

**마무리**
- [ ] **Review + Commit** `feat(store): refuse migration number gaps (SP9-00)`

---

### 티켓 SP9-01: 더보기, 활동 한 줄, 토스트 되돌리기 (앱만)

**목표:** 스펙 9.1(탭 막대 교체는 빼고), 9.6, 완료 조건 1(더보기)·12.
**막는 티켓:** 없음

**Files:** Create `components/MoreButton.tsx`, `screens/More.tsx`, `pages/more.tsx`. Modify `components/{LargeTitle,icons,Toast}.tsx`, `chat/{MessageView,hideCoveredActivity}.ts(x)`, `ui/chat/{Result,PeriodList}.tsx`, 네 탭 화면(`screens/{Today,Todos,Activity,Settings}.tsx`)의 머리, 탭 밖 화면(`Habits`, `Connect`만. `Activity`는 SP9-04, `Settings`는 SP9-07이 탭에서 뺄 때)의 돌아가기, `lib/nav.ts`(`HAS_STATUS_PAGE` 상수: SP8 앱 상태창 티켓이 `true`로 바꾼다), `lib/copy.ts`, `pages/_app.tsx`. Docs: SP6 스펙 5.5.5/F6 활동 줄 규칙을 9.6으로 고친다. Test 각 `*.test.tsx`, `chat/hideCoveredActivity.test.ts`

**Interfaces**
- Produces: `icons.tsx`에 `IconMore`, `IconSchedule`, `IconMemo`(SP9-04·07이 탭에 쓴다). `<MoreButton />`(32px 원, `aria-label="더보기"`, `/more/`로). `LargeTitle`의 `trailing`은 그대로 쓴다.
- `Toast`: `showFor(t: ToastContent, ms: number)`를 밖으로 내보내고(`useToast().showFor`), 채팅 활동은 `CHAT_ACTIVITY_MS = 6000`. `ToastContent.undoIds?: number[]`(여럿이면 새것부터 차례로 `undoActivity`, 막히면 멈추고 `"{k}개만 되돌렸어요"`).
- `MessageView`: `ActivityBox` → `ActivityLine({ confirmation })`(버튼 없음). 답 하나의 되돌릴 수 있는 활동 id들을 모아 토스트 하나로.
- `/more/` 목록 순서: 설정, 기록, 습관, 상태창(`/status/` 페이지가 빌드에 있을 때만), 기기 연결. 각 화면 돌아가기 "‹ 더보기".

**Slices**
- [ ] `TabBar.test`: 칸은 아직 `today/todos/activity/settings`(바뀌지 않음). `More.test`: 줄 순서와 링크, `/status/` 없으면 상태창 줄 없음
- [ ] 네 탭 화면 테스트에 `getByRole("link", { name: "더보기" })`. `Habits`·`Connect` 테스트에 "‹ 더보기", `/more/`에서는 탭 막대 어느 칸도 `aria-current` 없음
- [ ] `MessageView.test`: 활동은 "✓ …" 한 줄, `button` 없음, 확인 전(R4b 이전) 상태도 한 줄 문구. `Result.test`/`PeriodList.test`: 되돌리기 버튼 없음
- [ ] `Toast.test`: 채팅 활동 토스트 6초 뒤 사라짐, 다른 토스트 4초 그대로, 활동 셋이면 "✓ 3개를 바꿨어요", `undoIds` 셋 중 둘째가 막히면 "1개만 되돌렸어요"
- [ ] `hideCoveredActivity.test`를 새 규칙(한 줄로 바뀐 활동)에 맞춘다
- [ ] `lint:copy`에 10장 "더보기" 줄 문구. `npm run lint:copy && npm run check:csp` → 통과

**마무리**
- [ ] **Review + Commit** `feat(app): more screen, one-line activity, toast undo (SP9-01)`

---

### 티켓 SP9-02: 체크인 시간 바꾸기

**목표:** 스펙 8장, 9.7 "체크인 시간", 완료 조건 13.
**막는 티켓:** 없음

**Files:** Create `tools/checkin_times.py`, `screens/CheckinTimes.tsx`, `scripts/update_wake_task.ps1`(깨우기 작업만 다시 등록, `register_task.ps1`의 `Get-WakeTimes`·`Register-FromXml` 재사용). Modify `loop/schedule.py`, `loop/runner.py`(override 읽어 넘기기), `loop/catchup.py`(`due_between`에 override), `wake_times.py`(DB `mode=ro`로 override를 읽어 합침), `scripts/register_task.ps1`(안내 문구), `store/repos/state.py`, `tools/{core,actions,mcp_adapter,confirmations}.py`, `api/{read,models,server,push}.py`(설정 경로 옆), `screens/Settings.tsx`, `lib/copy.ts`. Test `tests/test_checkin_times.py`, `tests/test_schedule.py`, `screens/Settings.test.tsx`

**Interfaces**
- Produces:
- `@dataclass(frozen=True) class CheckinSlot: time: time; from_: date | None; prev: time | None`. `Overrides = dict[LoopKey, dict[Literal["weekday", "weekend"], CheckinSlot]]`.
- `loop/schedule.py`: `checkin_time(settings, overrides, loop, d: date) -> time`(d ≥ `from_`이면 `time`, 아니면 `prev`, 칸 없으면 config). `due_between(..., overrides: Overrides | None = None)`. 주간 회고(`review.week`) 시각 = `checkin_time(…, evening_checkin, 그 일요일)`.
- `decide_from(now, loop, day_type, new: time, overrides, runs) -> date`: 8장 규칙(논리적 날짜 기준).
- 주간 회고: override가 없으면 지금처럼 config의 `review.week.time`, 주말 저녁 override가 있으면 그 날짜부터 그 시각.
- `wake_times.wake_lines(root) -> list[str]`: config + DB override(`from` 이후 값과, `from`이 미래면 `prev`도)로 "weekday HH:MM"/"weekend HH:MM" 줄. DB가 없거나 못 읽으면 config만.
- 바꾼 뒤 `refresh_wake_task() -> bool`(`platform/windows.py`, `scripts/update_wake_task.ps1`을 백그라운드로 실행, Windows가 아니면 `True`). 실패하면 응답 `"wake_updated": false`, 설정 화면에 "노트북을 깨우는 시각은 아직 그대로예요. register_task.ps1을 다시 실행해 주세요." 한 줄.
- `StateRepo.get_schedule_override() -> Overrides`, `set_schedule_override(Overrides)`(`app_state.schedule_override`, JSON 칸 `{"time","from","prev"}`).
- 동작 `set_checkin_time(loop, day_type, time)`: 즉시 갈래(앱 설정)는 바로 적용 + 되돌리기(이전 칸으로). 두뇌 도구는 언제나 `needs_confirm` "체크인 시간을 바꿔요: {평일 아침} {09:00} → {09:30} ({내일부터|오늘부터})". 활동 `kind = "checkin_time_set"`, 대상 `checkin_time:<loop>:<day_type>`.
- API: `GET /settings/checkin-times` → `{"items": [{"loop", "day_type", "time", "from", "effective_today"}]}`(4개), `PUT /settings/checkin-times` 본문 `{"loop", "day_type", "time"}` → 같은 모양 + `"applies": "today" | "tomorrow"`. 범위 밖 422 `checkin_time_invalid`.

**Slices**
- [ ] `test_checkin_time_uses_prev_before_from`, `test_review_week_follows_weekend_evening`
- [ ] 8장 표 네 줄: `test_0800_0900_to_0930_today`, `test_0800_0900_to_0700_keeps_0900_today`, `test_0930_after_sent_no_second_run`, `test_0850_0900_to_0840_keeps_0900_today`. `test_change_at_0030_targets_next_logical_day`(Review Focus 1)
- [ ] `test_due_between_reads_override_without_restart`(runner가 tick마다 override를 다시 읽음)
- [ ] `test_range_and_step_validation`(04:50, 11:40, 09:05 → 422), `test_tool_always_needs_confirm`, `test_undo_restores_previous_slot`
- [ ] `test_telegram_tool_count_unchanged`(`tests/test_dispatcher_tools.py`)
- [ ] `test_wake_times_include_override`, `test_wake_times_without_db_uses_config`, `test_catchup_uses_override`, `test_put_reports_wake_updated_false_on_failure`
- [ ] `Settings.test`: 네 줄, 시간 선택 후 "내일부터 적용돼요" 토스트, 주말 저녁 안내 문구, `wake_updated: false` 안내 줄
- [ ] `npm run lint:copy && npm run check:csp` → 통과

**마무리**
- [ ] **Review + Commit** `feat: editable check-in times (SP9-02)`

---

### 티켓 SP9-03: 메모 BE

**목표:** 스펙 6장, 완료 조건 6(BE)·7.
**막는 티켓:** SP9-00, SP8 마이그레이션 013~015 머지

**Files:** Create `store/migrations/016_memos.sql`, `store/repos/memos.py`, `tools/memos.py`. Modify `store/exports.py`, `tools/{core,actions,activity,confirmations,mcp_adapter}.py`, `api/{read,models,server}.py`, `app.py`(`runner.register_daily`로 메모 정리·내보내기, `Tools(memos=…)` 조립), `harness/prompts/channel_app.md`, `tests/test_write_paths.py`(`ALLOWED`에 `memos`). Regenerate types. Test `tests/test_memos.py`, `tests/test_api_read.py`, `tests/test_api_actions.py`

**Interfaces**
- Produces:
- `@dataclass(frozen=True) class Memo: id: int; body: str; area: Area | None; pinned: bool; origin: Literal["user", "chat"]; created_at: datetime; updated_at: datetime`, `memo_title(body: str) -> str`(Review Focus 4, 빈 경우 `"제목 없는 메모"`).
- `MemosRepo(conn, clock)`: `create(body, area, origin, now) -> Memo`, `get(id) -> Memo | None`, `update(id, body, area, expected_updated_at, now) -> Memo`(다르면 `MemoConflict`), `pin(id, now)`, `unpin(id)`, `delete(id, now)`, `restore(id)`, `list(q=None, limit=50, before=None) -> list[Memo]`(첫 쪽은 고정 메모 전부 + 고정 아닌 것 `updated_at` 최근순, `before`는 고정 아닌 메모의 `updated_at`·`id` 커서라 다음 쪽에는 고정 메모가 다시 나오지 않는다), `search(q, limit) -> list[Memo]`(3글자 이상 FTS trigram, 미만 LIKE), `purge_deleted(older_than)`.
- 동작(즉시 갈래): `create_memo`, `update_memo(id, body, area, updated_at)`, `pin_memo`, `unpin_memo`, `delete_memo`. 409 `memo_conflict`, 422 `too_many_memos`, `too_many_pinned`. 활동 `memo_created`/`memo_updated`/`memo_pinned`/`memo_unpinned`/`memo_deleted`, 대상 `memo:<id>`, summary는 제목 앞 20자만.
- 두뇌 도구(`APP_ONLY_TOOLS`): `search_memos(query, limit=5)`, `read_memo(id)`, `create_memo(body, area=None)`. 결과의 본문은 `redact()` 뒤, `read_memo`는 8,000자까지. 확인 문구 "✓ 메모를 만들었어요: {제목}".
- API: `GET /memos?q=&limit=&before=` → `{"items": [{"id", "title", "preview", "area", "pinned", "origin", "updated_at"}], "next_before"}`, `GET /memos/{id}` → `Memo` 전체.
- 하루 한 번 작업: `purge_deleted(30일)`, `export_memos(memos, path)` → `data/exports/memos.md`.

**Slices**
- [ ] `test_016_creates_tables_and_fts_triggers`, `test_fts_follows_update_and_delete`
- [ ] `test_title_from_first_line_strips_markup`, `test_title_skips_empty_and_markup_only_lines`
- [ ] `test_search_trigram_korean_substring_사피`, `test_two_char_query_uses_like`, `test_deleted_not_searchable`
- [ ] `test_update_conflict_409`, `test_pin_cap_10`, `test_memo_cap_2000`, `test_delete_undo_restores`, `test_purge_after_30_days`
- [ ] `test_tools_app_only_and_no_edit_tools`(앱 도구에 3개, `update_memo`·`delete_memo` 도구 없음, 텔레그램 수 그대로), `test_read_memo_redacts`, `test_logs_and_activity_have_no_body`
- [ ] `test_api_memos_list_pinned_first`, `test_api_memos_second_page_has_no_pinned`, `test_export_memos_md`, `test_daily_job_registered`

**마무리**
- [ ] **Review + Commit** `feat(memos): memos table, repo, API and brain tools (SP9-03)`

---

### 티켓 SP9-04: 앱 메모 탭

**목표:** 스펙 9.4, 완료 조건 6(앱).
**막는 티켓:** SP9-03, SP9-01

**Files:** Create `screens/{Memos,MemoEditor}.tsx`, `pages/memos.tsx`, `pages/memos/view.tsx`, CSS 모듈 둘. Modify `components/TabBar.tsx`(`activity` 칸 → `memos "/memos/"`, 아이콘 `IconMemo`), `screens/Activity.tsx`(이제 탭 밖: "‹ 더보기"), `api/actions.ts`(`ActionName`에 메모 동작 5개), `components/markdownRender.tsx`(메모 모드: 체크박스 누르기), `lib/copy.ts`, `pages/_app.tsx`. Test `screens/Memos.test.tsx`, `screens/MemoEditor.test.tsx`, `components/TabBar.test.tsx`

**Interfaces**
- Consumes: `GET /memos`, `GET /memos/{id}`, 메모 동작(SP9-03).
- Produces: `toggleChecklistLine(body: string, lineIndex: number) -> string`(그 줄의 `[ ]`↔`[x]`만). `MemoEditor` 저장 시점: 완료, 화면 떠남, 입력 멈춘 뒤 1초. 오프라인 초안 키 `mp.memoDraft.<id|new>`(try/catch).

**Slices**
- [ ] `TabBar.test`: 칸 `today/todos/memos/settings`. `Activity.test`: "‹ 더보기"
- [ ] `Memos.test`: 고정 묶음 먼저, 검색 300ms 디바운스, 빈 목록 문구, 밀어서 고정·지우기(되돌리기 토스트), 비서 표시
- [ ] `MemoEditor.test`: 새 메모는 쓰기 상태로 열림, 1초 뒤 저장, 409면 문구 후 다시 읽기, 읽기 상태 체크박스 누름이 그 줄만 바꿈(`toggleChecklistLine` 표 테스트 포함), 오프라인이면 읽기만
- [ ] `npm run lint:copy && npm run check:csp` → 통과

**마무리**
- [ ] **Review + Commit** `feat(app): memos tab (SP9-04)`

---

### 티켓 SP9-05: 스케줄 BE

**목표:** 스펙 5.1, 5.2, 5.4, 5.5, 5.6(`.ics` 빼고), 9.8 `ui_events`.
**막는 티켓:** SP9-03

**Files:** Create `store/migrations/017_events.sql`, `store/migrations/hooks.py`, `store/repos/events.py`, `tools/events.py`. Modify `store/db.py`(훅 순서, `tz`), `app.py`(`migrate(conn, tz=settings.timezone)`), `harness/context.py`(`## 오늘 일정` 출처), `tools/{core,actions,activity,confirmations,mcp_adapter,ui}.py`, `api/{read,models,server}.py`, `harness/dispatcher.py`(`build_preamble` 부르는 곳에 `events` 넘기기), `screens/{AddTodoSheet,EditTodoSheet}.tsx`(시각 칸 빼기), `tests/test_write_paths.py`. Docs: SP3-4 스펙 10.1 A1에 "회차 차례의 `create_event`는 `ui_confirm`" 한 줄. Regenerate types. Test `tests/test_events.py`, `tests/test_migrations.py`, `tests/test_event_tools.py`, `tests/test_api_read.py`, `tests/test_ui_catalog.py`

**Interfaces**
- Produces:
- `@dataclass(frozen=True) class Event`(017 칸 그대로), `EventFields`(TypedDict, 만들기·고치기 칸), `@dataclass(frozen=True) class Occurrence: event_id: int; date: date; start: datetime | None; end: datetime | None; all_day: bool; title: str; area: Area | None; repeat: str; origin: str; remind_min: int | None; remind_at: datetime | None; skipped: bool = False`(시각은 UTC). API 응답 모델 `EventItem`은 `Occurrence`에서 `remind_at`, `skipped`를 뺀 것(스펙 5.6). `MissedReminder`: `event_id, date, start, title, outcome`(여기서 모델을 정해 `gen:types`에 넣고, 채우기는 SP9-06).
- `expand(event: Event, start: date, end: date, *, tz, skips: set[date]) -> list[Occurrence]`(순수, 62일 넘으면 `ValueError`).
- `EventsRepo(conn, clock, tz)`: `create(fields: EventFields, now) -> Event`, `get(id)`, `update(id, fields, now) -> Event`(시각·알림이 바뀌면 앞으로의 `event_reminders` 행 지움), `delete(id, now)`, `restore(id)`, `skip(id, d)`, `unskip(id, d)`, `end_repeat(id, from_date, now)`, `occurrences(start, end, include_skipped=False) -> list[Occurrence]`, `count_live() -> int`, `live() -> list[Event]`, `skips() -> dict[int, set[date]]`(SP9-08이 쓴다).
- `migrate(conn, *, upto=None, tz="Asia/Seoul")`: 번호마다 `BEGIN` + SQL → `HOOKS.get(n)(conn, tz)` → `PRAGMA user_version = n` → `COMMIT`, 실패면 ROLLBACK. `hooks.after_017(conn, tz) -> int`(옮긴 수, 5.4 대상 규칙).
- 동작(즉시 갈래): `create_event`, `update_event`, `delete_event(id, scope: "one"|"following"|"all", date?)`, `dismiss_missed_reminder(event_id, date)`. 활동 `event_created`/`event_updated`/`event_skipped`/`event_repeat_ended`/`event_deleted`, 대상 `event:<id>`(건너뛰기는 `event:<id>:<date>`).
- 두뇌 도구(`APP_ONLY_TOOLS`): `list_events`, `create_event`, `update_event`, `delete_event`(5.5 확인 규칙, 회차 차례의 `create_event`는 `ui_confirm`). `create_task`·`update_task`가 `scheduled_at`을 받으면 오류 문구 "시간이 정해진 일은 스케줄로 만들어요. create_event를 써 주세요." `confirmations.py`의 timed 할 일 날짜 옮기기 확인(`timed_move_line` 쪽)은 `update_event` 확인 "일정을 바꿔요: {title} → {새 때}"로 옮기고 할 일 쪽은 지운다.
- 완성 카드 `ui_events`(`{"items": Occurrence 모양 1~10개}`), 카탈로그 판 다음 번호.
- API: `GET /events?start&end`, `GET /events/{id}`, `/today`에 `events`(오늘 논리적 날짜의 일정), `missed_reminders`(SP9-06이 채운다. 여기서는 빈 배열).
- `build_preamble(events=…)`: `## 오늘 일정` 최대 8줄 "14:00 치과 (#e12)", 하루 종일은 "하루 종일 카드 결제일 (#e3)".

**Slices**
- [ ] `expand` 표: `test_daily`, `test_weekly_mon_wed_fri`, `test_monthly_31_moves_to_feb_28_2027`, `test_repeat_until_inclusive`, `test_skip_removes_one_day`, `test_all_day_remind_0900`, `test_range_over_62_raises`
- [ ] 검증: `test_api_events_range_over_62_422`, `test_weekly_start_not_in_weekdays_422`, `test_all_day_rejects_10_30_60`, `test_cap_300`
- [ ] `test_end_repeat_from_first_day_deletes`, `test_update_time_clears_future_reminder_rows`
- [ ] 마이그레이션: `test_017_hook_moves_open_timed_tasks`(UTC 05:00 → 현지 14:00), `test_017_hook_keeps_prioritized_and_parent_tasks`, `test_017_hook_skips_done_and_draft`, `test_hook_failure_rolls_back_version`
- [ ] 도구: `test_create_event_default_remind_10_and_all_day_0`, `test_update_time_needs_confirm_title_direct`, `test_delete_always_confirm`, `test_run_turn_create_needs_ui_confirm`, `test_create_task_rejects_scheduled_at`, `test_move_confirm_moved_to_update_event`, `test_app_tools_plus_4_telegram_unchanged`
- [ ] `test_today_events_use_logical_day_0100_belongs_to_previous`(Review Focus 1), `test_preamble_today_events_from_events`, `test_ui_events_catalog_entry`
- [ ] 앱: `AddTodoSheet.test`/`EditTodoSheet.test`에서 시각 칸 없음

**마무리**
- [ ] **Review + Commit** `feat(schedule): events, migration hook and tools (SP9-05)`

---

### 티켓 SP9-06: 알림 tick

**목표:** 스펙 5.3, 완료 조건 2·3.
**막는 티켓:** SP9-05

**Files:** Create `loop/reminders.py`. Modify `loop/runner.py`, `api/read.py`(`/today.missed_reminders`), `config.py`, `config.toml`. Test `tests/test_event_reminders.py`, `tests/test_runner.py`

**Interfaces**
- Consumes: `EventsRepo.occurrences`, `harness/delivery.py`의 주 통로 규칙(텔레그램 대체 포함).
- `harness/delivery.py`에 더한다: `reminder_payload(title: str, body: str, url: str) -> dict`(`type: "reminder"`, 지금 `notice_payload`의 고정 제목·주소 대신), `async Delivery.deliver_reminder(title, body, url) -> Channel | None`(지금 `deliver_notice`와 같은 통로 규칙, 못 보내면 None). Files에 `harness/delivery.py`, 앱 `public/sw.js`(알림 `type: reminder`면 `data.url`을 연다)를 더한다.
- 순서: tick(동기) 안에서 판정하고 `event_reminders` 행을 `outcome = 'sent'`(또는 `late_sent`)로 **먼저** 넣는다(같은 날 두 번 보내지 않기). 보내기는 `asyncio` 작업으로 넘기고, 결과가 None이면 그 행을 `failed`로 고친다. `missed`·`skipped`는 보내지 않고 행만.
- Produces: `remind_events(*, last_seen_at: datetime, now: datetime, events: EventsRepo, limits) -> list[PendingReminder]`(동기, 판정과 행 기록), `async send_reminders(pending, delivery, events)`(보내고 실패를 `failed`로). `ReminderOutcome(event_id, date, outcome: Literal["sent","late_sent","missed","failed","skipped"])`. `reminder_text(occ, now, late: bool) -> tuple[str, str]`(제목, 본문, 5.3 문구). 푸시 데이터 `{"url": "/schedule/?date=YYYY-MM-DD"}`.
- `runner.py`: `if not self.checkins` 조기 반환과 하트비트 기록보다 앞에서 부른다.

**Slices**
- [ ] `test_r1_on_time_gap_under_3m`, `test_gap_exactly_3m_is_not_wake`
- [ ] `test_r2_gap_25m_sends_15_min_left`, `test_r3_gap_50m_missed_no_push`, `test_r4_failed`, `test_r5_fourth_late_skipped`, `test_daily_cap_30_skipped`
- [ ] `test_one_day_before_late_says_hours`("2시간 남았어요"), `test_created_inside_gap_not_sent`(`updated_at` 규칙), `test_edit_just_before_remind_at_uses_new_time`(Review Focus 2)
- [ ] `test_nine_day_gap_judges_seven_days_pushes_at_most_three`(Review Focus 3), `test_sends_while_paused`, `test_not_counted_in_proactive_limit`, `test_no_double_send_same_day`
- [ ] `test_today_missed_reminders_only_today_and_not_dismissed`(outcome 셋), `test_send_failure_marks_failed`, `test_reminder_payload_has_title_and_schedule_url`
- [ ] `test_reminder_copy_has_no_banned_words`(5.3 문구, SP5 금지어 목록)

**마무리**
- [ ] **Review + Commit** `feat(schedule): reminder tick (SP9-06)`

---

### 티켓 SP9-07: 앱 스케줄 탭과 오늘 블록

**목표:** 스펙 9.1(탭 막대 최종), 9.2, 9.3, 완료 조건 1·2(앱)·4.
**막는 티켓:** SP9-05, SP9-04

**Files:** Create `screens/{Schedule,ScheduleWeek,MonthCalendar,EventSheet}.tsx`, `pages/schedule.tsx`, `ui/components/Events.tsx`, CSS 모듈. Modify `components/TabBar.tsx`(최종 `today/todos/schedule/memos`), `screens/Settings.tsx` 머리(이제 탭 밖: "‹ 더보기"), `screens/Today.tsx`(오늘 일정·놓친 알림 블록), `ui/registry.tsx`(`ui_events`), `api/actions.ts`, `lib/copy.ts`, `pages/_app.tsx`. Test `screens/Schedule.test.tsx`, `screens/EventSheet.test.tsx`, `screens/Today.test.tsx`, `components/TabBar.test.tsx`

**Interfaces**
- Consumes: `GET /events`, `/today.events`, `/today.missed_reminders`, 일정 동작(SP9-05).
- Produces: `weekOf(d: string) -> string[]`(월~일 현지 날짜), `monthGrid(month: string) -> string[][]`. 주소 `?date=YYYY-MM-DD`로 고른 날을 남긴다(푸시가 연다).

**Slices**
- [ ] `TabBar.test`: 최종 네 칸과 문구 `오늘/할 일/스케줄/메모`. `Settings.test`: "‹ 더보기"
- [ ] `Schedule.test`: 점은 일정 있는 날만, 좌우 밀기로 주 바뀜, 제목 눌러 달력 펼침·날 고르면 접힘, `?date=` 열기, 빈 날 문구, 하루 종일 먼저
- [ ] `EventSheet.test`: 기본 알림 10분 전, 하루 종일 켜면 10·30·60 숨김, 매주면 요일 토글, 반복 일정 상세의 세 버튼과 확인 시트, 한 번짜리는 "지우기"
- [ ] `Today.test`: 오늘 일정 5줄 + "스케줄에서 {n}개 더 보기", 놓친 알림 두 문구, 닫기 → `dismiss_missed_reminder`
- [ ] `Events.test`(`ui_events`). `npm run lint:copy && npm run check:csp` → 통과

**마무리**
- [ ] **Review + Commit** `feat(app): schedule tab and today block (SP9-07)`

---

### 티켓 SP9-08: 아이폰 캘린더 구독 주소

**목표:** 스펙 5.7, 9.7 "아이폰 캘린더에 구독", 완료 조건 5(클라우드 부분).
**막는 티켓:** SP9-05

**Files:** Create `api/calendar.py`, `screens/CalendarSubscribe.tsx`. Modify `api/{server,auth}.py`(이 경로만 Bearer 예외), `api/server.py`의 `access_log`(이 경로 쿼리 가림), `store/repos/state.py`, `tools/actions.py`(`calendar_key_create`, `calendar_key_rotate`, 내부 동작), `screens/Settings.tsx`, `lib/copy.ts`. Test `tests/test_calendar_ics.py`, `tests/test_api_auth.py`, `tests/test_api_logging.py`

**Interfaces**
- Consumes: `EventsRepo.live()`, `EventsRepo.skips()`(SP9-05).
- Produces: `render_ics(events: list[Event], skips: dict[int, set[date]], tz: str) -> str`(CRLF, 75바이트 접기). `GET /api/v1/calendar.ics?key=` (401 틀림, `Cache-Control: no-store`, `text/calendar; charset=utf-8`). `GET /settings/calendar` → `{"url": str | None}`, `POST /settings/calendar` `{"rotate": bool}` → `{"url"}`. 주소는 `{BE 기준 주소}/api/v1/calendar.ics?key=…`.

**Slices**
- [ ] `test_rrule_daily_weekly_monthly`, `test_monthly_31_bysetpos`, `test_exdate_for_skips`, `test_until_utc`, `test_all_day_value_date`, `test_tzid_and_vtimezone`, `test_no_note_no_area_no_valarm`
- [ ] `test_wrong_key_401_counts_limiter`, `test_calendar_key_not_accepted_elsewhere`, `test_api_token_not_needed_for_ics`, `test_access_log_masks_key`, `test_rotate_breaks_old_url`
- [ ] `Settings.test`: 만들기 → 주소·복사, 다시 만들기 확인 시트, 안내 문구. `npm run lint:copy` → 통과

**마무리**
- [ ] **Review + Commit** `feat(schedule): read-only iCalendar subscription (SP9-08)`

---

### 티켓 SP9-09: 대화 요약, 잇기, 말아 넣기, 지우기

**목표:** 스펙 7장, 완료 조건 8(BE)·9·10.
**막는 티켓:** SP9-05

**Files:** Create `store/migrations/018_conversation_summaries.sql`, `harness/summaries.py`, `tests/test_sp9_story.py`(클라우드 끝-끝), `harness/prompts/summarize.md`, `tools/conversations.py`. Modify `store/repos/conversations.py`, `store/transcripts.py`, `harness/{conversations,dispatcher,brain}.py`, `api/{chat,read,models,server}.py`, `loop/runner.py`(요약 큐, 하루 한 번 다시 해 보기), `config.py`, `config.toml`, `harness/prompts/channel_app.md`. Docs: SP3-4 스펙 7.2 표에 0번 규칙. Regenerate types. Test `tests/test_conversation_summaries.py`, `tests/test_dispatcher_conversations.py`, `tests/test_api_chat.py`, `tests/test_api_read.py`

**Interfaces**
- Produces:
- `ConversationsRepo`: `set_summary(id, title, summary, through)`, `bump_user_messages(id) -> int`, `reset_session(id)`, `add_session(id, session_id, at)`, `sessions(id) -> list[str]`, `reopen(id, at)`, `delete(id, at)`, `recent(channel, limit, q=None, before=None)`(지운 것 뺌).
- `summarize(conv, lines, prev_summary, brain) -> Summary | None`(`Summary(title: str, summary: str)`), 도구 없음, `max_turns=1`. 짧은 대화(사용자 1개 이하, 답 200자 미만)는 두뇌 없이 `fallback_title(lines)`. 상한·오류면 `None`.
- 라우터: `for_app_message(at, *, conversation_id, checkin_id, resume_conversation_id=None)`. 0번 규칙: `resume_conversation_id`가 앱 통로·지우지 않은 대화이고 `checkin_id`가 없으면 그 대화(7.3의 chat/plan/run 갈래). `checkin_id`가 있으면 1번 규칙.
- 말아 넣기: `bump_user_messages`가 `limits.rollup_user_messages + 1`(31) **이상**을 돌려주면 요약 → `reset_session` → 새 세션 입력 = 앞머리 + `## 이 대화의 지난 내용` + 최근 6줄. 요약 실패면 미룸.
- resume 실패 대체: 요약 있으면 요약 + 6줄, 없으면 `HISTORY_LINES = 20` 그대로.
- 요약 대상: `closed_at IS NOT NULL AND summary IS NULL AND title IS NULL AND deleted_at IS NULL AND channel = 'app'`. 닫힐 때 다음 tick이, 남은 것은 하루 한 번 작업이 최근 7일치를 다시 해 본다(`runner.register_daily`).
- `erase_conversation(transcripts_dir, conv_id, from_day, to_day)`: 그 대화의 줄을 `[지운 대화]` 한 줄로(파일마다 임시 파일 + `os.replace`).
- 두뇌 도구(`APP_ONLY_TOOLS`): `find_conversations(query=None, days=14, limit=5)` → `[{"id", "date", "title", "summary"}]`(원문 없음).
- API: `POST /chat` 본문에 `resume_conversation_id`, `GET /conversations`에 `title`·`summary`(120자)·`q`·`before`, `DELETE /conversations/{id}`, `POST /conversations/new` → `{"closed": [int]}`.

**Slices**
- [ ] `test_018_backfills_conversation_sessions`, `test_fts_on_title_summary`
- [ ] `test_close_queues_summary`, `test_daily_retry_summarizes_pending`, `test_summary_saved_title_20_summary_600`, `test_cap_15_and_error_fallback_title`, `test_short_conversation_no_brain_call`, `test_telegram_not_summarized`
- [ ] **`test_new_conversation_input_has_no_other_transcript`**(완료 조건 9: 대화 A 고유 문자열이 B 첫 입력에 없음)
- [ ] 라우터: `test_resume_chat_reopens_and_closes_others`, `test_resume_second_message_during_evening_window_stays`, `test_resume_plan_opens_new_chat_with_summary`, `test_resume_run_inside_window_goes_to_run`, `test_checkin_id_without_resume_goes_to_run_and_both_follow_rule_0`(Review Focus 5), `test_existing_conversation_id_keeps_30min_meaning`
- [ ] `test_resume_failure_uses_summary_plus_6`, `test_resume_failure_without_summary_uses_20_lines`
- [ ] `test_rollup_at_31st_message`, `test_rollup_deferred_when_summary_fails`(31번째 실패 → 32번째에 다시 해 보고 성공), `test_rollup_app_only`
- [ ] `test_delete_erases_lines_across_days`, `test_delete_removes_all_session_files`, `test_deleted_hidden_from_list_messages_and_tool`, `test_new_conversation_endpoint`
- [ ] `test_find_conversations_no_transcript`, `test_app_tools_plus_1`(`tests/test_dispatcher_tools.py`)
- [ ] `tests/test_sp9_story.py::test_sp9_story`(가짜 두뇌·가짜 시계): 메모 만들기·찾기 → 일정 만들기 → 알림 tick 보냄 → 공백 뒤 늦은 알림 → 체크인 시간 바꾸기 → 대화 닫힘·요약 → 목록에서 잇기 → 지우기. 완료 조건 2·3·6·7·8·9·13의 BE 쪽을 한 번에.

**마무리**
- [ ] **Review + Commit** `feat(chat): conversation summaries, resume, rollup and delete (SP9-09)`

---

### 티켓 SP9-10: 앱 대화 목록과 퀵 칩

**목표:** 스펙 9.5, 완료 조건 8(앱)·11.
**막는 티켓:** SP9-09, SP9-07

**Files:** Create `chat/{ConversationList,QuickChips}.tsx`, `chat/quickChips.ts`, CSS 모듈. Modify `chat/{ChatSheet,transport,history}.ts(x)`, `chat/sheetContext.ts`(고른 대화 상태), `lib/copy.ts`, `pages/_app.tsx`. Test `chat/ConversationList.test.tsx`, `chat/quickChips.test.ts`, `chat/QuickChips.test.tsx`, `chat/transport.test.ts`, `chat/ChatSheet.test.tsx`

**Interfaces**
- Consumes: `GET /conversations`, `DELETE /conversations/{id}`, `POST /conversations/new`, `POST /chat.resume_conversation_id`(SP9-09), `/today`(체크인·회고·일정).
- Produces: `frontChip(today: Today, now: Date) -> Chip | null`(체크인 > 회고 > 3시간 안 일정). `FIXED_CHIPS`(4개, 9.5 문장). 시트 상태 `pickedConversationId: number | null`(목록에서 고르면 설정, "새 대화"·시트 닫기에서 비움). `transport`는 `pickedConversationId`가 있으면 모든 요청에 `resume_conversation_id`, 체크인 칩은 `checkin_id`만.

**Slices**
- [ ] `ConversationList.test`: 날짜 묶음, 체크인 대화 "체크인" 머리, 검색, 밀어서 지우기 확인 시트 문구, "새 대화"
- [ ] `transport.test`: 고른 대화를 보는 동안 매 요청에 `resume_conversation_id`, 새 대화 뒤 없음, `test_checkin_chip_sends_checkin_id_not_resume`(Review Focus 5)
- [ ] `quickChips.test`: 앞 칩 규칙 세 가지와 없음, 일요일 회고 열림, 일정 2:59 뒤 있음·3:01 뒤 없음
- [ ] `QuickChips.test`: 고정 4개 순서, 누르면 정해진 문장이 내 말풍선, 읽기 전용이면 비활성
- [ ] `npm run lint:copy && npm run check:csp` → 통과

**마무리**
- [ ] **Review + Commit** `feat(app): conversation list and quick chips (SP9-10)`

---

### 티켓 SP9-11: 수용 시험 (노트북)

**목표:** 완료 조건 1~13을 실제 기기로. 스파이크 S2·S3의 노트북 부분.
**막는 티켓:** 전부

- [ ] 노트북 pull + 작업 재시작(먼저 노트북 HEAD 확인, 메모리 교훈). DB 백업 확인.
- [ ] 완료 조건 2: 2분 뒤 시작·정시 알림 일정 → 폰 푸시 "지금이에요".
- [ ] 완료 조건 3: 지금 T에 40분 뒤 시작·30분 전 알림 일정(알림 T+10)을 만들고 T+5부터 T+20까지 노트북 절전 → 깨어난 직후 "20분 남았어요" 한 번.
- [ ] 완료 조건 5: 설정에서 구독 주소 → 아이폰 캘린더 구독 → 일정 보임.
- [ ] 완료 조건 9·10: 앱 대화 두 개, 두 번째 첫 두뇌 입력 로그(길이·섹션 이름만)에 다른 대화 원문 없음. S12처럼 앱 도구 수(지금 + 9개)로 `max_turns=10` 안에 끝남.
- [ ] 완료 조건 13: 설정에서 평일 아침을 5분 뒤로 바꾸고(내일부터면 다음 날 확인) 노트북을 절전 → 바꾼 시각 5분 전에 깨어나고 브리핑이 그 시각에 온다(재시작 없음). `wake_updated: false`였다면 그 사실을 적는다.
- [ ] 완료 조건 1·4·6·7·8·11·12: 폰에서 눈으로 한 번씩(체크리스트).
- [ ] 결과를 `docs/acceptance/2026-10-xx-sp9.md`에 남긴다. 스파이크 S2·S4 노트북 결과도.

---

### 티켓 SP9-12: Dahun 확인

**목표:** 스펙 15장 13개와 10장 문구를 Dahun이 본다. "추천대로"면 통과. 바뀐 것은 스펙·이 계획·해당 티켓에 후속 PR로 옮긴다(앞 티켓을 막지 않는다).

## 변경 기록

- v1 (2026-10-25): 스펙 v2.1에서 티켓 13개로.
- v1.1 (2026-10-25): 문서 리뷰 반영. 깨우기 작업 갱신(S4, `update_wake_task.ps1`), 알림 보내기 순서와 `deliver_reminder`, 말아 넣기 `>=`, 수용 절차 시각, SP8 뒤 시작, 0번 규칙을 스펙대로, 돌아가기 담당 티켓, 완료 조건 표와 끝-끝 테스트, 빠진 Files·메서드, 문구 검사 명령.
