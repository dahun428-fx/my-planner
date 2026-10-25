# SP8 상태창 기록 · 인생 히스토리 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan ticket-by-ticket. Steps use checkbox (`- [ ]`) syntax for tracking. 티켓 하나를 끝낼 때마다 `.claude/agents/code-reviewer.md`로 리뷰하고, 지적을 반영한 뒤 다음 티켓으로 간다.

**Goal:** 상태창에 세 가지 기록(영역 활동 → 스탯 보너스, 하루 끝 이룬 순간, 아이폰 몸 기록)을 쌓고, 대시보드 인생 곡선에 히스토리 탭을 더하고, 두 웹 앱이 함께 쓰는 픽토그램 28개를 둔다.

**Architecture:**
- 보너스는 저장하지 않는다. `status/activity.py`의 순수 함수가 `StatusRepo.activity_rows`(지난 28일)에서 읽을 때마다 계산하고, `status_snapshot`이 `stats[]`에 `bonus`·`effective_score`·`activity`를 더한다. `GET /status`와 두뇌 `get_status`가 같은 스냅샷을 쓰고 텔레그램 `/status` 글은 바뀌지 않는다.
- 이룬 순간: 하루 한 번 작업 `queue_moments`가 정리할 날을 골라 디스패처에 가장 낮은 차례의 `_MomentsJob`을 넣는다. 작업은 새 세션·세션 저장 없음·도구 `save_moments` 하나로 두뇌를 부르고, 결과는 호출 뒤 `status_moment_days.state`로 정한다(`harness/moments.py`). 숨기기·다시 보이기·지우기는 `/actions`의 새 동작이다.
- 몸 기록: `POST /api/v1/body`는 `BODY_TOKEN`만 받는 좁은 경로이고, 즉시 갈래의 내부 동작 `record_body_days`(`endpoint="body"`)로 `body_days`에 쓴다.
- 히스토리: `015`가 사건 `area`, 챕터 `ladder_remembered`를 더하고, `curve/history.py`가 `GET /curve/history` 모양을 만든다. 대시보드 곡선 화면에 탭 `곡선 | 히스토리`.
- 픽토그램: 원본 `web/shared/pictograms.svg` 하나, 두 앱의 `sync:design`이 `src/components/pictograms.gen.tsx`를 만든다.

**Tech Stack:** SP3-4·SP5·SP7과 같다(Python 3.12, aiohttp, claude-agent-sdk 0.2.173, SQLite, hypothesis / Next.js 15 Pages Router 정적 내보내기, Vitest, Playwright). 새 의존성 없음.

**Spec:** [`docs/superpowers/specs/2026-10-25-sp8-status-records-history-design.md`](../specs/2026-10-25-sp8-status-records-history-design.md) (v3, develop `c17081c`), 결정 [ADR 0013](../../adr/0013-moments-saved-without-confirmation.md). 상위: [SP3-4 스펙](../specs/2026-10-24-sp3-4-life-curve-dashboard-design.md)(API 계약 정본), [SP5](../specs/2026-10-24-sp5-ops-app-design.md), [SP7](../specs/2026-10-24-sp7-habits-design.md), [`DESIGN.md`](../../../DESIGN.md), [`GLOSSARY.md`](../../../GLOSSARY.md), [ADR 0005](../../adr/0005-brain-only-reaches-planner-tools.md), [ADR 0006](../../adr/0006-no-punishing-game-mechanics.md), [ADR 0012](../../adr/0012-develop-staging-auto-promote-to-main.md).
- 스펙과 이 계획이 다르면 스펙이 맞다. 다만 아래 "스펙과 코드가 맞지 않는 곳" 표의 결정은 이 계획이 정했고, 해당 티켓이 스펙의 그 절을 함께 고친다.

## Global Constraints

- (5.3) `w(d) = (28 − d) / 28`, 창 `d = 0..27`, `bonus = round_half_up(min(2, S/5), 1)`, `effective_score = min(10, base + bonus)`, base 없으면 `null`. `S`는 `fractions.Fraction`, 반올림은 `(Decimal(x.numerator) / Decimal(x.denominator)).quantize(Decimal("0.1"), ROUND_HALF_UP)`.
- (5.3) 상수 `WINDOW_DAYS = 28`, `TASK_POINT = 1`, `HABIT_POINT = 0.5`, `BODY_STEPS_MIN = 6000`, `BODY_SLEEP_MIN = 420`, `BODY_POINT = 0.5`, `DAY_CAP = 3`, `BONUS_FULL = 10`, `BONUS_MAX = 2`. `config.toml`로 바꾸지 않는다.
- (5.3, 12장) 보너스가 줄어드는 것을 알리는 문구·표시(아래 화살표, "−0.3", "줄었어요"), 지난 보너스 비교, 남은 날 수, 비율(%)은 어디에도 없다. 보너스는 디버프를 만들지도 지우지도 않는다.
- (6.6) 이룬 순간은 경험치·칭호를 주지 않는다. `status_xp_ledger`의 `source_kind`는 그대로다.
- (1장 조건 7, 11장) 이룬 순간의 글은 SQLite `status_moments`에만: 로그, `data/exports/`, 원문 기록, 활동 `summary`, 순간 호출의 SDK 세션 파일, 텔레그램, 웹 푸시, `/client-errors`에 없다. 텔레그램 통로 두뇌는 날짜와 개수만.
- (6.3) 순간 호출: `session_id = None`, `RunContext(kind="moments")`, 지시문 `moments.md` + 금지어 블록만, `max_turns = 3`, 입력 중 표시 없음, 도구 `mcp__planner__save_moments` 하나, `extra_args = {"no-session-persistence": None}`. `save_moments`는 대화 도구 목록에 없다(텔레그램 28, 앱 35 그대로).
- (6.2) `MOMENTS_LOOKBACK_DAYS = 7`, 상한 여유 `daily_brain_calls − 10`, 실패 2회 → `failed`, 사용자 메시지 6,000자, 끝낸 할 일 20개.
- (7.2) `BODY_TOKEN`은 `POST /api/v1/body`만, 43자 이상, `API_TOKEN`과 다를 때만 열린다. 본문 4KB, CORS 없음, `client_msg_id` 없음, 활동 기록·경험치 없음. 걸음·잠 숫자는 로그에 없다.
- (9장) 픽토그램 24px 격자, 선 1.75(16px에서 2), 둥근 끝·이음, `currentColor`, 이모지 없음. 늘 이름 글자와 함께. 조작 아이콘은 `icons.tsx` 그대로.
- (14장) 마이그레이션 번호: SP8은 **013(순간), 014(몸 기록), 015(히스토리)**, SP9("앱 탭·메모·일정")는 **016부터**. SP8 안에서 이 순서로 머지한다(SP8-03 → SP8-06 → SP8-08).
- (14장, ADR 0012) 티켓마다 가지 `sp8/<번호>-<이름>`을 `develop`에서 만들고 **PR은 `develop`으로**.
- 새 고정 문구는 스펙 부록 A 그대로. 부록 A에 없는 문구는 끝의 "문구 표"에만 있다.
- SP1·SP3-4·SP7 Global Constraints(단일 작성자, `mode=ro` 읽기, 시각 UTC, 논리적 날짜 04:00, 영역 6개, 하루 3회 상한)는 그대로다.

## 작업 방식

- TDD 주기와 명령은 SP3-4 계획 "작업 방식" 그대로다: 슬라이스마다 테스트 → `python -m pytest <노드 id> -v` FAIL(새 이름은 `ImportError`/`AttributeError`, 새 동작은 `AssertionError`) → 구현 → 같은 명령 PASS.
- **BE 티켓 끝 검증:** `python -m pytest -q` → `0 failed`, `ruff check src tests .github/scripts` → `All checks passed!`.
- **앱 티켓 끝 검증:** `cd web/app && npm run typecheck && npm run lint:copy && npm test && npm run test:tz && npm run build && npm run check:csp && npm run sync:design && git diff --exit-code` → 모두 통과, 마지막 diff 빈 출력.
- **대시보드 티켓 끝 검증:** `cd web/dashboard && npm run typecheck && npm test && npm run build && npm run check:csp && npm run sync:design && git diff --exit-code` → 모두 통과, 마지막 diff 빈 출력.
- **스키마가 바뀐 티켓:** `cd web/app && npm run gen:types`, `cd web/dashboard && npm run gen:types` 뒤 커밋. `python -m pytest tests/test_dashboard_fixtures.py --update-dashboard-fixtures`로 대시보드 고정 자료를 다시 쓰고, `python -m pytest tests/test_dashboard_fixtures.py tests/test_api_schema.py -q` → `passed`.
- 생성자 새 인자는 키워드 전용, 기본값 `None`(앞 SP 시험이 그대로 돈다): `Tools(moments=…, body=…)`, `status_snapshot(moments=…, body=…)`, `ApiDeps(body_token=…)`.
- 시험 날짜: 오늘 = 2026-10-25(일), 시각은 `kst(y, mo, d, h, mi)`(`tests/test_dispatcher_messages.py`). 순간 작업의 tick은 10/26(월) 04:01.
- 시험 자료는 꾸며 낸 것만(`tests/fixtures/`, 11장).

## Review Focus

1. **BE가 멈출 때 대기열에 남은 순간 작업**: `Dispatcher.stop`은 "큐에 든 것까지 처리"하므로, 노트북을 끄는 순간 따라잡기 7일이 남아 있으면 두뇌를 7번 부르며 종료가 30초 상한에 걸린다. 멈추는 중에는 순간 작업을 건너뛰고(행은 `pending` 그대로) 다음 날 다시 고른다. → SP8-03 `test_stop_skips_queued_moments_jobs`
2. **단축어가 보내는 숫자 모양**: 단축어의 합계는 `8123.0`이나 `true`처럼 올 수 있다. 파이썬에서 `True`는 `int`라 그대로 받으면 걸음 1로 저장된다. `bool`과 소수는 400("걸음 수는 0~100,000, 잠은 0~1,440분이에요."), README 단축어 순서에 "숫자 반올림" 단계를 둔다. → SP8-06 `test_body_rejects_bool_and_float_values`
3. **순간 글의 길이와 공백**: 앞뒤 공백은 빼고 60자는 코드포인트로 센다(SQLite `length()`와 같다). 한글 60자는 저장, 61자·줄바꿈·제어 문자는 M2 오류. → SP8-03 `test_moment_text_strip_codepoints_and_newline`
4. **숨긴 순간을 지운 뒤 "되돌리기"**: 알림 줄의 되돌리기는 24시간 남아 있다. 지운 뒤 누르면 U3로 막혀 `409 superseded`이고 행은 다시 생기지 않는다. → SP8-04 `test_undo_hide_after_delete_superseded`
5. **새벽 00:00~03:59에 한 일**: 10/25 02:30에 끝낸 할 일과 01:40의 사용자 메시지는 10/24의 순간 입력에 들어가고 10/25에는 없다(원문 기록 파일도 논리적 날짜). → SP8-03 `test_moments_input_uses_logical_day_for_0230_completion`

---

## File Structure

```
src/my_planner/
  status/activity.py                        # SP8-00: 공식·상수·순수 함수
  status/snapshot.py                        # SP8-00(stats), SP8-04(moments), SP8-06(body)
  store/repos/status.py                     # SP8-00: ActivityRows, activity_rows (SP8-06이 몸 기록 질의)
  store/migrations/013_moments.sql          # SP8-03
  store/migrations/014_body.sql             # SP8-06
  store/migrations/015_curve_history.sql    # SP8-08
  store/repos/moments.py                    # SP8-03: Moment, MomentDay, MomentsRepo
  store/repos/body.py                       # SP8-06: BodyDay, BodyRepo
  store/repos/curve.py, store/repos/conditions.py  # SP8-08: area, ladder_remembered, earliest_*
  store/transcripts.py                      # SP8-03: user_lines(day)
  store/views.py                            # SP8-04: moment_dict, moment_counts
  domain.py                                 # SP8-03: RunContext.kind, moments_date, moments_refs
  harness/brain.py                          # SP8-03: Brain.run 새 인자, build_options(extra_args)
  harness/moments.py                        # SP8-03: 고르기, 입력, 지시문, 판정
  harness/dispatcher.py                     # SP8-03: _MomentsJob, _PRIORITY_MOMENTS. SP8-04: 회고 앞머리
  harness/context.py                        # SP8-04: moments_week_block, recent_areas_block
  harness/prompts/{moments,system,review_week,review_year}.md
  loop/runner.py                            # SP8-03: queue_moments_daily, prune_records_daily
  tools/mcp_adapter.py                      # SP8-03: tool_names_for(ctx), save_moments 스키마
  tools/moments.py                          # SP8-03·04: MomentTools(save/hide/unhide/delete)
  tools/body.py                             # SP8-06: BodyTools.record_body_days
  tools/{core,actions,activity,confirmations}.py
  curve/history.py                          # SP8-08: curve_history()
  curve/model.py, curve/seed.py, cli.py     # SP8-08
  api/{read,models,server,auth,cors}.py, api/body.py(SP8-06), app.py, config.py
web/shared/pictograms.svg                   # SP8-01
web/{app,dashboard}/scripts/sync-design.mjs(+test), src/components/pictograms.gen.tsx, src/pages/_document.tsx
web/dashboard/src/
  components/{StatBar,RecentAreas,MomentsPanel,BodyLine,Nav}.tsx
  screens/{StatusScreen,CurveScreen}.tsx, screens/HistoryView.tsx, components/{HistoryChapter,HistoryFilters,GlanceStrip,HistorySummary}.tsx
  lib/{labels,history,api}.ts
web/app/src/
  pages/status.tsx, screens/Status.tsx(+.module.css), screens/StatusMoments.tsx, lib/copy.ts, api/actions.ts
tests/test_status_activity.py, test_moments_job.py, test_moments_tools.py, test_api_moments.py,
      test_api_body.py, test_curve_history.py, test_sp8_story.py (새) + 기존 파일에 시험 추가
docs/spikes/2026-11-sp8.md                  # 사람 관문 H1
```

## 티켓 지도

| # | 티켓 | 막는 티켓 | 라벨 |
|---|---|---|---|
| SP8-00 | 1단계 BE: 스탯 보너스 | 없음 | `ready-for-agent` |
| SP8-01 | 픽토그램 | 없음 | `ready-for-agent` |
| SP8-02 | 1단계 화면 | SP8-00, SP8-01 | `ready-for-agent` |
| SP8-03 | 2단계 BE: 순간 만들기 (013) | SP8-00 | `ready-for-agent` (노트북 부분은 사람 관문 H1로 뺐다, 머지를 막지 않는다) |
| SP8-04 | 2단계 API | SP8-03 | `ready-for-agent` |
| SP8-05 | 2단계 화면 | SP8-04, SP8-02 | `ready-for-agent` |
| SP8-06 | 3단계 BE: 몸 기록 (014) | SP8-03(번호 순서), SP8-00 | `ready-for-agent` |
| SP8-07 | 3단계 화면과 안내 | SP8-06, SP8-02 | `ready-for-agent` (README 실제 단축어 순서는 사람 관문 H2) |
| SP8-08 | 히스토리 BE (015) | SP8-06(번호 순서) | `ready-for-agent` |
| SP8-09 | 히스토리 화면 1 | SP8-08, SP8-01 | `ready-for-agent` |
| SP8-10 | 히스토리 화면 2 | SP8-09 | `ready-for-agent` |
| SP8-11 | 수용 | SP8-05, SP8-07, SP8-10 | `ready-for-agent` (노트북 확인은 사람 관문 H3) |

- BE 줄: SP8-00 → SP8-03 → SP8-04 → SP8-06 → SP8-08. 화면 줄: SP8-01 → SP8-02 → SP8-05 → SP8-07 → SP8-09 → SP8-10. 두 줄은 위 표의 막는 티켓에서만 만난다.
- **노트북·Dahun이 필요한 일은 맨 뒤 "사람 관문"(H1~H4)에 모았다.** 어느 것도 클라우드 티켓의 머지를 막지 않고, H1·H2·H3은 SP8 완료(스펙 상태 "확정")만 막는다.

---

### 티켓 SP8-00: 1단계 BE — 스탯 보너스

**목표:** 스펙 5장 전부, 1장 조건 1·2·6, 13장 "보너스 공식·보너스 성질·스냅샷" 묶음.
**막는 티켓:** 없음

**Files:** Create `src/my_planner/status/activity.py`, `tests/test_status_activity.py`. Modify `store/repos/status.py`, `status/snapshot.py`, `api/models.py`(`StatusStat`, `StatActivity`), `tests/test_status_property.py`, `tests/test_status_snapshot.py`, `tests/test_status_command.py`, `tests/dashboard_seed.py`(4주 할 일·습관 체크를 더해 보너스가 보이게), `docs/superpowers/specs/2026-10-24-sp3-4-life-curve-dashboard-design.md` 6.3.6(새 필드). Regenerate `web/{app,dashboard}/src/api/{schema.json,types.gen.ts}`, `web/dashboard/src/test/fixtures/status*.json`.

**Interfaces**
- Consumes: `clock.logical_date(dt, tz, boundary)`, `CurveRepo.latest_area_scores`, `domain.Area`.
- Produces (`status/activity.py`):
  - `@dataclass(frozen=True) class DoneTask: id: int; completed_at: datetime; areas: tuple[str, ...]`
  - `@dataclass(frozen=True) class HabitCheckRow: habit_id: int; area: str; date: date`
  - `@dataclass(frozen=True) class BodyDayRow: date: date; steps: int | None; sleep_minutes: int | None`
  - `@dataclass(frozen=True) class ActivityCounts: tasks: int; habit_checks: int; body_days: int`
  - `@dataclass(frozen=True) class Bonus: score_s: Fraction; bonus: Decimal; counts: ActivityCounts`
  - `area_points(tasks, checks, body, today, *, tz, boundary) -> dict[str, dict[date, Fraction]]`: 5.2 표, 하루 상한 3을 적용한 값. 할 일 날짜는 `logical_date(completed_at)`, 영역이 없는 할 일은 뺀다. 몸 기록은 `health`만.
  - `activity_counts(tasks, checks, body, today, *, tz, boundary) -> dict[str, ActivityCounts]`: 창 안의 가중하지 않은 개수(5.6).
  - `area_bonus(points, today, counts) -> dict[str, Bonus]`: 영역 6개 모두.
  - `round_bonus(s: Fraction) -> Decimal`, `effective_score(base: int | None, bonus: Decimal) -> Decimal | None`.
- Produces (`store/repos/status.py`): `@dataclass(frozen=True) class ActivityRows: tasks: list[DoneTask]; checks: list[HabitCheckRow]; body: list[BodyDayRow]`, `StatusRepo.activity_rows(from_utc: datetime, to_day: date) -> ActivityRows`. 할 일은 `status='done' AND deleted_at IS NULL AND completed_at >= from_utc`와 `task_areas`, 습관 체크는 `habits.deleted_at IS NULL`(쉬는·그만둔 습관 포함)이고 `date <= to_day`. 이 티켓에서 `body`는 늘 `[]`(5.6). `from_utc`는 호출 쪽이 `T − 28`의 04:00(한국)으로 넘긴다(하루 넉넉히, 파이썬이 거른다).
- Produces (`status/snapshot.py`): `stats[]` 행마다 `bonus: float`, `effective_score: float | None`, `activity: {"tasks", "habit_checks", "body_days"}`. 바탕 `score`·디버프 계산은 그대로.
- `api/models.py`: `class StatActivity(_Model): tasks: int; habit_checks: int; body_days: int`, `StatusStat`에 `bonus: float`, `effective_score: float | None`, `activity: StatActivity`.

**Slices**
- [ ] `tests/test_status_activity.py`(가짜 행으로 순수 함수만):
  - `test_example_1_career_mwf_12_tasks`: `S == Fraction(162, 28)`, `bonus == Decimal("1.2")`, base 6 → `Decimal("7.2")`
  - `test_example_2_habit_daily_28_days_rounds_half_up`: `S == Fraction(29, 4)`(7.25), `bonus == Decimal("1.5")`, base 4 → 5.5
  - `test_example_2a_decay_dates`(parametrize 10/28, 11/1, 11/8, 11/17, 11/18, 11/22 → 1.2, 0.8, 0.4, 0.1, 0.0, 0.0, 보이는 스탯 5.2 … 4.0)
  - `test_example_2prime_and_3_cap_and_decay`(10/25 2.0, 10/28 2.0, 11/1 1.7, 11/8 0.8, 11/15 0.2, 11/21 0.0, 11/22 0.0)
  - `test_day_cap_3_ten_health_tasks_today`: `p == 3`, `bonus == Decimal("0.6")`
  - `test_task_with_two_areas_splits_half`: 각 영역 `p == Fraction(1, 2)`, `bonus == Decimal("0.1")`
  - `test_0230_completion_is_previous_logical_day`: 10/25 02:30 KST 완료 → `points["career"]` 열쇠 `date(2026,10,24)`, 무게 27/28
  - `test_window_27_days_in_28_days_out`: `d=27` 들어가고 `d=28` 빠진다
  - `test_task_without_area_ignored`, `test_bonus_never_negative_and_effective_at_most_10`(base 9 + 1.5 → `Decimal("10.0")`, `bonus` 1.5 그대로), `test_no_base_effective_null_bonus_kept`
- [ ] `tests/test_status_snapshot.py`(DB로):
  - `test_reopened_and_soft_deleted_tasks_not_counted`, `test_deleted_habit_checks_excluded_paused_and_archived_included`
  - `test_stats_have_bonus_fields_and_counts`: 건강 28일 체크 → `{"score": 4, "bonus": 1.5, "effective_score": 5.5, "activity": {"tasks": 0, "habit_checks": 28, "body_days": 0}}`
  - `test_debuff_ignores_bonus`: 바탕 Q3 6 → Q4 4, 보너스 2.0 → `debuff is True`(보이는 6.0이어도). 바탕이 오른 영역에 보너스가 있어도 `debuff is False`
- [ ] `tests/test_status_property.py`에 속성 시험 셋(hypothesis, 활동 묶음 = 날짜·영역·출처 무작위):
  - `test_effective_between_base_and_base_plus_2`: `base ≤ effective ≤ min(10, base + 2)`
  - `test_no_new_activity_bonus_never_rises`: 하루 지나고 새 활동이 없으면 `bonus(T+1) ≤ bonus(T)`
  - `test_daily_change_at_most_0_7`: `|bonus(T+1) − bonus(T)| ≤ 0.7`
- [ ] `tests/test_status_command.py::test_telegram_status_text_unchanged_by_bonus`: 같은 DB에서 보너스 필드가 있는 스냅샷의 `status_text`가 SP7 기준 글(시험 안에 박은 문자열)과 같고 "요즘", "+1.5"가 없다(D7).
- [ ] `tests/test_curve_tools.py::test_get_status_equals_snapshot`가 새 필드로도 같다(고치지 않고 통과).
- [ ] 스키마 재생성, 대시보드 고정 자료 다시 쓰기. `tests/test_dashboard_fixtures.py::test_seeded_status_is_level_six_with_one_debuff`는 그대로 통과.

**검증**
- [ ] `python -m pytest tests/test_status_activity.py tests/test_status_property.py tests/test_status_snapshot.py tests/test_status_command.py -q` → `passed`, 실패 0
- [ ] BE 티켓 끝 검증 → `0 failed`, `All checks passed!`
- [ ] `cd web/app && npm run typecheck && npm test` · `cd web/dashboard && npm run typecheck && npm test` → 통과(필드 추가만)

**마무리**
- [ ] **Review + Commit** `feat(status): activity bonus on stats, computed on read`

---

### 티켓 SP8-01: 픽토그램

**목표:** 스펙 9장, 1장 조건 10.
**막는 티켓:** 없음

**Files:** Create `web/shared/pictograms.svg`, `web/app/src/components/pictograms.gen.tsx`, `web/dashboard/src/components/pictograms.gen.tsx`. Modify `web/{app,dashboard}/scripts/sync-design.mjs`, `scripts/sync-design.test.mjs`, `src/pages/_document.tsx`(두 앱), `web/shared/global.css`(`.pictogram-sprite`, `.pictogram` 크기 클래스) → 두 앱 `src/styles/global.css` 사본, `DESIGN.md`("Pictograms" 절, 대시보드 절 282행 문장).

**Interfaces**
- 원본 모양: 캔버스 [인생 히스토리 초안](https://claude.ai/artifact/FeapQVZFNFC5Y1sgZw4MqR) `Pictograms` 보드의 생성기 `ICONS` 사전(Artifact `read`로 읽는다). 열쇠 `life` → `quality_of_life`, `turn` → `turning_point`.
- `pictograms.svg`: `<svg xmlns="http://www.w3.org/2000/svg">` 안에 `<symbol id="p-<id>" viewBox="0 0 24 24">` 28개, 자식은 `path`·`circle`·`rect`만, `fill`·`stroke` 색 속성·`style` 없음(점 표시만 `stroke-width`).
- `sync-design.mjs`(두 앱 같은 함수, 머리 주석만 다름) 새 내보내기: `PICTO_SOURCE`, `PICTO_TARGET`, `parseSymbols(svg: string) -> {id: string, children: string}[]`, `pictogramsModule(svg: string) -> string`, `syncDesign()`은 CSS 사본과 픽토그램 파일을 둘 다 쓰고 둘 중 하나라도 바뀌면 `true`.
- `pictograms.gen.tsx`(생성 파일 머리말 `// GENERATED by \`npm run sync:design\` from web/shared/pictograms.svg`): `export type PictogramName = "career" | … (28개)`, `export const PICTOGRAM_NAMES: readonly PictogramName[]`, `export function PictogramSprite()`(숨긴 `<svg className="pictogram-sprite" aria-hidden="true">` 안에 JSX `<symbol>`, 속성은 camelCase), `export function Pictogram({ name, size = 24, label }: { name: PictogramName; size?: 16 | 20 | 24; label?: string })`(`<svg … fill="none" stroke="currentColor" strokeWidth={size === 16 ? 2 : 1.75} strokeLinecap="round" strokeLinejoin="round"><use href="#p-<name>"/></svg>`, `label`이 있으면 `role="img" aria-label`, 없으면 `aria-hidden="true"`).
- `_document.tsx`: `<body>`의 첫 요소 `<PictogramSprite />`.

**Slices**
- [ ] 두 앱 `scripts/sync-design.test.mjs`에:
  - `the pictogram copy matches web/shared/pictograms.svg`: `readFileSync(PICTO_TARGET) === pictogramsModule(readFileSync(PICTO_SOURCE))`
  - `ids are exactly the spec 9.1 table`: 시험 안의 28개 목록(9.1 표 순서)과 `parseSymbols(...).map(s => s.id)`가 같다(개수를 따로 박지 않는다, 9.2)
  - `source has no style, colour fill, script or foreignObject`: `/style=|fill="(?!none)|<script|foreignObject/` 없음, 자식 태그는 `path|circle|rect`뿐
  - `module exports the sprite and the component`: 생성 글에 `export function PictogramSprite`, `strokeWidth`, `#p-` 있음, `stroke-width` 없음
- [ ] 두 앱 `src/components/frame.test.tsx`(앱) / `src/test/app.test.tsx`(대시보드)에 `sprite_rendered_once_first_in_body`: 문서에 `.pictogram-sprite`가 정확히 1개
- [ ] `Pictogram` 렌더 시험(두 앱 `src/components/Pictogram.test.tsx`): `label` 없으면 `aria-hidden="true"`, 있으면 `role="img"`와 이름, 16px에서 `stroke-width="2"`
- [ ] `check:csp` 통과(인라인 스크립트·`style=` 없음). DESIGN.md "Pictograms" 절(9.3 규칙 1~5 그대로), 282행 문장을 "히스토리는 영역 태그와 '비서가 만듦' 표시를 쓴다(곡선 차트의 점은 그대로 ▲▼◆, 종류는 높은 때·힘든 때·전환점)"로.

**검증**
- [ ] `cd web/app && npx vitest run scripts/sync-design.test.mjs` · `cd web/dashboard && npx vitest run scripts/sync-design.test.mjs` → passed
- [ ] 앱·대시보드 티켓 끝 검증 → 통과, `git diff --exit-code` 빈 출력

**마무리**
- [ ] **Review + Commit** `feat(design): 28 pictograms from one sprite, synced into both apps`

---

### 티켓 SP8-02: 1단계 화면

**목표:** 스펙 10.1(보너스 칸, "요즘 손이 간 영역", 내비게이션), 10.2(앱 `/status/`의 레벨·스탯·요즘 손이 간 영역·뒤로 링크), 부록 A 금지 구.
**막는 티켓:** SP8-00, SP8-01

**Files:**
- 대시보드: Modify `components/StatBar.tsx`, `screens/StatusScreen.tsx`, `components/Nav.tsx`, `lib/labels.ts`(`STATUS_TEXT` 새 문구, `PICTOGRAM_LABELS`), `src/test/banned-words.test.ts`. Create `components/RecentAreas.tsx`, `components/StatBar.test.tsx`. Test `screens/StatusScreen.test.tsx`.
- 앱: Create `pages/status.tsx`, `screens/Status.tsx`, `screens/Status.module.css`, `screens/Status.test.tsx`, `src/test/fixtures/status.json`. Modify `pages/_app.tsx`(CSS import), `lib/copy.ts`(`copy.status`), `lib/copy.test.ts`(`APP_BANNED`), `api/fixtures.test.ts`(표에 `["status.json", "Status"]`), `e2e/routes.ts`(`GET /status`), `e2e/screens.spec.ts`(화면 `status`).

**Interfaces**
- Consumes: `Status`, `StatusStat`(`bonus`, `effective_score`, `activity`)(SP8-00), `Pictogram`(SP8-01).
- 대시보드 `StatBar({ label, score, bonus = 0, max = 10 })`: 바탕 칸은 지금처럼 `stat-fill`(`--primary`), 보너스 칸은 `min(10 − score, ceil(bonus))`칸을 채우지 않은 1px `--text` 테두리 `rect.stat-bonus`로 이어 그린다. `score === null`이면 보너스 칸을 그리지 않는다. `aria-label`은 `T.statBar(label, score)` 그대로.
- `STATUS_TEXT`: `statSub(base: number, bonus: number) -> "바탕 {n} · 요즘 +{b}"`(보너스 0이면 `"바탕 {n}"`), `statSubNoBase(bonus) -> "요즘 +{b} · 분기 회고에서 점수를 정하면 더해져요"`, `recentHeading`, `recentLine(b)`, `recentCounts({tasks, habit_checks, body_days}) -> "4주 동안 할 일 {n}개 · 습관 {m}번 · 몸 기록 {k}일"`(0인 항목 뺌), `recentEmpty`. 숫자는 `toFixed(1)`.
- `RecentAreas({ stats }: { stats: StatusStat[] })`: `bonus > 0`인 영역을 큰 순서로(같으면 `Area` 순서), 줄마다 영역 픽토그램(영역색) + 이름 + `+{b}` + 둘째 줄.
- `Nav`: 링크마다 픽토그램 `home`(`/`), `todo`(`/tasks/`), `curve`(`/curve/`), `status`(`/status/`), `settings`(`/settings/`), `aria-hidden`.
- 앱 `Status()` 화면(`/status/`): `LargeTitle` "상태창", 레벨 줄(`level` 픽토그램, "Lv. {n}", 6px XP 막대, "{into} / {next} XP"), 스탯 그룹(영역 픽토그램 + 이름, 오른쪽 `effective_score` 또는 "—", 둘째 줄 `statSub`), 요즘 손이 간 영역, 뒤로 링크 `copy.status.back`. `usePolling(() => apiGet<Status>("/status", "Status"))`. 오프라인이면 `OfflineNotice` + `copy.status.offline`.
- `copy.status`: `heading: "상태창"`, `back: BACK_TODAY`(SP9 더보기 머지 때 "‹ 더보기"로, 10.2), `offline: "연결되면 상태창을 보여 드릴게요."`, 스탯·요즘 손이 간 영역 문구는 대시보드와 같은 글.

**Slices**
- [ ] 대시보드 `StatBar.test.tsx`: `bonus_cells_are_outlined_after_base`(6, 1.2 → `.stat-bonus` 2칸 너비 20), `no_bonus_cells_without_base`, `bonus_clipped_at_10`(9, 1.5 → 1칸)
- [ ] `StatusScreen.test.tsx`: `stat_line_shows_effective_and_base_and_bonus`("5.5", "바탕 4 · 요즘 +1.5"), `zero_bonus_shows_base_only`, `no_base_shows_dash_and_hint`, `recent_areas_sorted_and_counts`, `recent_areas_empty_copy`, `debuff_unchanged_with_bonus`, `no_decline_marks`(본문에 "−", "%", "줄었", "↓"는 디버프 줄 밖에 없음)
- [ ] `banned-words.test.ts`: `BANNED`에 "보너스가 줄", "스탯이 떨어"(이스케이프로) 더하고 개수 시험 14개로. 앱 `copy.test.ts` `APP_BANNED`에 같은 둘.
- [ ] `Nav` 시험(`src/test/app.test.tsx`): `nav_links_have_pictograms_hidden_from_screen_readers`
- [ ] 앱 `Status.test.tsx`: `renders_level_stats_and_recent_areas`, `back_link_is_today_until_sp9`(`‹ 오늘`, `href="/"`), `today_screen_has_no_status_link`(`Today` 렌더에 `/status/` 링크 없음), `offline_shows_notice`, `css_module_imported_in_app`(SP7 9장 규칙: `_app.tsx`에 `../screens/Status` import)
- [ ] `e2e/screens.spec.ts`의 `SCREENS`에 `status`(라이트·다크), 폭 ≤ 390.

**검증**
- [ ] 대시보드·앱 티켓 끝 검증 → 통과
- [ ] `cd web/app && npm run e2e -- --grep status` → `status (light)`, `status (dark)` passed, `e2e/__screens__/status-*.png` 생김

**마무리**
- [ ] **Review + Commit** `feat(web): stat bonus cells, recent areas and the app status screen`

---

### 티켓 SP8-03: 2단계 BE — 순간 만들기 (013)

**목표:** 스펙 6.1~6.3, 6.8, 1장 조건 3·4·6·7(로그·세션 쪽). 노트북 스파이크 S-SP8-1은 사람 관문 H1(이 티켓은 그 결과를 기다리지 않는다).
**막는 티켓:** SP8-00

**Files:** Create `store/migrations/013_moments.sql`(6.1 그대로), `store/repos/moments.py`, `harness/moments.py`, `harness/prompts/moments.md`, `tools/moments.py`, `tests/test_moments_job.py`, `tests/test_moments_tools.py`. Modify `domain.py`, `harness/brain.py`, `harness/dispatcher.py`, `tools/mcp_adapter.py`, `tools/core.py`(`Tools(MomentTools, HabitTools)`, `moments=`), `tools/actions.py`(`prune_records`), `loop/runner.py`, `app.py`, `store/transcripts.py`, `tests/fakes.py`, `tests/test_write_paths.py`, `tests/test_migrations.py`, `tests/test_brain_options.py`, 그리고 `tool_names_for("…")`를 부르는 시험 6개(`test_brain_options`, `test_curve_tools`, `test_ui_catalog`, `test_ui_tools`, `test_dispatcher_app_channel`, `test_habit_tools`)를 `tool_names_for(RunContext(None, None, channel="…"))`로.

**Interfaces**
- `domain.RunContext`에 `kind: Literal["chat", "run", "moments"] = "chat"`, `moments_date: date | None = None`(M1의 그 날짜), `moments_refs: frozenset[str] = frozenset()`(입력에 나온 `task:<id>`, `habit:<id>`, `condition`, `chat`). `Dispatcher._run_brain`은 `kind="run"`.
- `harness/brain.py`:
  - `Brain.run(prompt, *, session_id, run_ctx, fork_session=False, system_prompt: str | None = None, max_turns: int | None = None, persist_session: bool = True) -> BrainResult`. `tests/fakes.FakeBrain.run`도 같은 인자를 받고 `calls[i]`에 기록한다.
  - `build_options(…, extra_args: dict[str, str | None] | None = None)` → `ClaudeAgentOptions(extra_args=extra_args or {})`. `ClaudeBrain.run`: `persist_session=False`면 `{"no-session-persistence": None}`.
- `tools/mcp_adapter.py`: `tool_names_for(ctx: RunContext) -> list[str]`: `ctx.kind == "moments"`면 `["save_moments"]`, 아니면 지금 규칙(채널). `build_planner_tools`가 이것만 싣는다. `_SPECS["save_moments"]`: `date`(문자열), `moments`(배열 `maxItems 3`, 항목 `{text: string maxLength 60, area: enum|null, sources: array 1..5}`). `TOOL_NAMES`·`APP_ONLY_TOOLS`에는 넣지 않는다.
- `store/repos/moments.py`:
  - `@dataclass(frozen=True) class Moment: id: int; date: date; slot: int; text: str; area: str | None; sources: list[str]; hidden_at: datetime | None`
  - `@dataclass(frozen=True) class MomentDay: date: date; state: Literal["pending", "done", "empty", "failed"]; saved: int; attempts: int`
  - `MomentsRepo(conn, clock)`: `day(d) -> MomentDay | None`, `days_since(from_: date) -> dict[date, MomentDay]`, `save_day(d, items: list[tuple[str, str | None, list[str]]], now) -> list[Moment]`(slot 1..n, 날 행 `done`·`saved=n`), `mark(d, state, now, *, saved=0)`, `bump_attempt(d, now, max_attempts) -> str`(`pending` 행만, 2회면 `UPDATE … SET state='failed' WHERE state='pending'`), `prune_days(older_than: date) -> int`. 읽기(`between`, `get`, `hide` …)는 SP8-04.
- `store/transcripts.py`: `TranscriptStore.user_lines(day: date) -> list[tuple[str, str]]`: 그날 파일의 `사용자` 줄 `(HH:MM, 본문)`, 오래된 것부터(이미 가린 글).
- `harness/moments.py`: 상수 `MOMENTS_LOOKBACK_DAYS = 7`, `MOMENTS_MAX_TURNS = 3`, `MOMENTS_RESERVE_CALLS = 10`, `MOMENTS_MAX_ATTEMPTS = 2`, `MOMENTS_TASKS_MAX = 20`, `MOMENTS_CHAT_MAX_CHARS = 6000`, `MOMENT_DAYS_KEEP = 60`, `MOMENTS_SINCE_KEY = "moments_since"`, `MOMENTS_PAUSED_KEY = "moments_paused"`.
  - `days_to_queue(repo, state, today: date) -> list[date]`: 6.2-2. `moments_since`가 없으면 `today − 1`로 적는다. `moments_paused == "1"`이면 `[]`. 오래된 날부터.
  - `@dataclass(frozen=True) class MomentsInput: text: str; refs: frozenset[str]; has_data: bool`
  - `build_moments_input(day, *, tasks: TasksRepo, habits: HabitsRepo | None, conditions: ConditionsRepo | None, transcripts: TranscriptStore, tz, boundary) -> MomentsInput`: 6.3 입력 모양 그대로(머리 `## 날짜` … `## 사용자 메시지 (두 통로, 오래된 것부터)`), 할 일 20개, 메시지 6,000자(넘으면 오래된 줄부터 뺀다). `has_data`는 끝낸 할 일·습관 체크·사용자 메시지 가운데 하나라도 있을 때(컨디션만이면 거짓). 메모(SP9)는 읽지 않는다.
  - `moments_system_prompt() -> str`: `prompts.load("moments.md")` + 빈 줄 + `system.md`의 `<!-- banned-words:start -->…<!-- banned-words:end -->` 블록과 그 앞 한 줄.
  - `settle(repo, day, result: BrainResult, called: bool, now) -> Literal["done", "pending", "failed"]`: 6.2-6 그대로. 도구를 안 부르고 `ok`면 `mark(day, "done", saved=0)`.
- `harness/dispatcher.py`: `@dataclass class _MomentsJob: date: date`, `_PRIORITY_MOMENTS = 2`, `Dispatcher.submit_moments(day: date) -> None`, `_handle_moments(job)`: (1) 멈추는 중이면 아무것도 하지 않는다(Review Focus 1) (2) `repo.day(d)`가 `done|empty|failed`면 끝 (3) 입력이 비면 `mark(d, "empty")` (4) 그날 `brain_calls ≥ daily_brain_calls − 10`, `brain.auth ∈ {login, billing}`, `limited_until`이 지금 뒤면 그대로 둔다 (5) `_call_brain(prompt=입력, session_id=None, run_ctx=RunContext(None, None, kind="moments", actor="secretary", activity_channel="scheduler", moments_date=d, moments_refs=…), system_prompt=moments_system_prompt(), max_turns=3, persist_session=False)`, 입력 중 표시 없음 (6) `rate_limited`면 `_set_limited`, (7) `settle`. 원문 기록에 쓰지 않는다. 로그 `moments_job {date, state, saved, rejected, duration_ms}`만.
  - `_call_brain`은 새 세 인자를 받고 기본값이 아닐 때만 `brain.run`에 넘긴다(SP1 시험 두뇌가 그대로 돈다). `run_ctx.kind == "moments"`면 `_typing_loop`를 띄우지 않는다.
- `tools/moments.py`: `class MomentTools`(mixin, `self.moments: MomentsRepo | None`): `save_moments(ctx, date=None, moments=None) -> dict`(`@_tool`). M1~M5(6.3) 그대로, `ctx.kind != "moments"`면 `{"error": "쓸 수 없는 도구예요."}`. 성공 `{"saved": n, "rejected": k}`, M4 `{"already": True}`. 저장·날 행·활동 `moments_saved`(`target="moments:<date>"`, summary "이룬 순간 {n}개 정리 ({M}/{D})", `undo=None`)를 한 `transaction`. `ctx.events.append(ToolEvent("moments_saved", None, {"date", "saved", "rejected"}))`(글 없음).
- `tools/actions.py`: 내부 동작 `prune_records`(`public=False`): `status_moment_days`를 60일 전보다 오래된 행 지움. `loop/runner.py`: `queue_moments_daily(target: MomentsSubmitter, moments: MomentsRepo, state: StateRepo) -> Callable[[date], None]`(`__name__ = "queue_moments"`), `prune_records_daily(target) -> Callable[[date], None]`. `app.py`가 둘을 `register_daily`.
- `moments.md`: 6.3 규칙 1~6을 해요체 지시문으로. 예시 문장은 "포트폴리오 사례 하나를 끝까지 다듬었어요".
- `tests/test_write_paths.py`: `TOOLS`에 `"my_planner.tools.moments"`, `ALLOWED`에 `"status_moments": set(TOOLS)`, `"status_moment_days": {*TOOLS, "my_planner.harness.moments"}`.

**Slices**
- [ ] `tests/test_migrations.py`: `test_013_moment_checks`(text 61자·0자, slot 0·4, 틀린 area, 날짜 `2026-1-1` 모두 `IntegrityError`, `UNIQUE(date, slot)`), `test_013_day_state_check`, `test_013_ledger_untouched`(012 원장 행 그대로), `test_latest_version_is_013`(이 티켓 머지 시점 `LATEST_VERSION == 13`. SP8-06·SP8-08이 14·15로 고친다)
- [ ] `tests/test_brain_options.py`: `test_moments_options_disable_session_persistence`(`extra_args == {"no-session-persistence": None}`), `test_chat_options_keep_session`(`extra_args == {}`), `test_claude_brain_uses_given_system_prompt_and_max_turns`(가로챈 `build_options` 인자 `max_turns == 3`, `system_prompt`가 `moments.md`로 시작하고 `system.md` 첫 줄이 없음)
- [ ] `tests/test_moments_tools.py`:
  - `test_tool_names_moments_kind_only_save_moments`(서버에 실린 이름 `["save_moments"]`), `test_chat_and_run_tool_lists_have_no_save_moments`(28·35 그대로)
  - `test_save_moments_rejected_outside_moments_kind`
  - `test_m1_other_date_error`, `test_m2_more_than_3_error_saves_nothing`, `test_m2_source_not_in_input_error`, `test_moment_text_strip_codepoints_and_newline`(Review Focus 3)
  - `test_m3_banned_item_dropped_others_saved`(`rejected == 1`, 오류 아님), `test_m3_does_not_drop_good_phrases`("지출이 줄었어요"는 저장)
  - `test_m4_second_call_already`, `test_m5_one_transaction`(활동 쓰기에서 예외 → 순간·날 행·활동 모두 없음)
  - `test_moments_activity_summary_has_date_only`(summary == "이룬 순간 2개 정리 (10/24)", 글 없음), `test_no_xp_from_moments`(원장 합계 그대로)
- [ ] `tests/test_moments_job.py`(`BeEnv` + `FakeBrain`, tick 10/26 04:01):
  - `test_picks_yesterday_back_7_days_since_moments_since_oldest_first`, `test_days_older_than_7_not_picked_no_row`, `test_moments_paused_picks_nothing`
  - `test_empty_day_no_brain_call`(컨디션만 있는 날도 `empty`), `test_empty_day_with_later_check_not_redone`
  - `test_reread_before_call_done_skips_brain`, `test_reserve_10_calls_stops_and_keeps_pending`(`attempts` 그대로), `test_auth_login_stops`, `test_limited_until_stops`
  - `test_rate_limited_sets_limited_and_keeps_attempts`, `test_auth_error_records_brain_auth`
  - `test_judged_by_state_after_call`(1번째 `save_moments` M2 오류 → 2번째 저장 → `status="max_turns"` → `done`, `attempts == 0`)
  - `test_two_failures_become_failed`, `test_failed_never_overwrites_done`, `test_ok_without_tool_call_done_zero`
  - `test_user_message_and_run_go_first`(대기열에 메시지·회차·순간 → 처리 순서), `test_runs_while_paused_and_not_counted_as_proactive`
  - `test_call_shape`(`session_id is None`, `max_turns == 3`, `persist_session is False`, 입력 중 표시 0회, `brain_calls` +1)
  - `test_moments_input_uses_logical_day_for_0230_completion`(Review Focus 5), `test_input_has_user_lines_only_and_6000_chars`(비서 줄 없음, 오래된 줄부터 잘림), `test_input_does_not_read_memos`
  - `test_stop_skips_queued_moments_jobs`(Review Focus 1: 3일 대기 → `stop()` → 두뇌 호출 0, 세 날 `pending`)
  - `test_three_days_off_catches_up_in_order`(1장 조건 4)
  - `test_logs_and_transcripts_have_no_moment_text`(시험 글 "꾸며 낸 순간 글"이 `state/logs/*.log`와 `data/transcripts/` 어디에도 없음, `moments_job` 줄 키는 `date, state, saved, rejected, duration_ms`뿐)
  - `test_prune_moment_days_60`
- [ ] `tests/test_prompts.py::test_moments_prompt_rules`: 규칙 1~6의 핵심 구("해낸 일", "60자", "0개", "병명", "sources", "save_moments")가 있고 금지어 없음, `moments_system_prompt()`에 금지어 블록이 있고 `system.md`의 대화 원칙(`## 할 일을 다루는 방식`)은 없음.

**검증**
- [ ] `python -m pytest tests/test_moments_job.py tests/test_moments_tools.py tests/test_brain_options.py tests/test_migrations.py tests/test_write_paths.py -q` → `passed`
- [ ] BE 티켓 끝 검증 → `0 failed`, `All checks passed!`

**마무리**
- [ ] ADR 0013 끝에 이 계획 링크 한 줄. **Review + Commit** `feat(moments): end-of-day moments job with save_moments only`

---

### 티켓 SP8-04: 2단계 API

**목표:** 스펙 6.4, 6.5, 6.7, 10.3, 1장 조건 5·7(통로 쪽).
**막는 티켓:** SP8-03

**Files:** Modify `store/repos/moments.py`(읽기·숨기기), `store/views.py`, `status/snapshot.py`, `tools/moments.py`, `tools/core.py`(`get_status`), `tools/actions.py`, `tools/activity.py`(`moment_target`), `api/read.py`, `api/models.py`, `api/server.py`, `harness/context.py`, `harness/dispatcher.py`, `harness/prompts/{system,review_week}.md`, `docs/superpowers/specs/2026-10-24-sp3-4-life-curve-dashboard-design.md`(6.2 경로표 `GET /moments`, 6.4.2 동작표 셋, 6.4.3 되돌리기 표 넷). Regenerate schema/types. Test `tests/test_api_moments.py`(새), `tests/test_api_undo.py`, `tests/test_moments_tools.py`, `tests/test_prompts.py`, `tests/test_habit_context.py`.

**Interfaces**
- `MomentsRepo`: `between(from_: date, to: date, *, include_hidden: bool) -> list[Moment]`(최근 날짜부터, 같은 날 `slot` 순), `hidden_count(from_, to) -> int`, `get(id) -> Moment | None`, `hide(id, at) -> str | None`(이전 `hidden_at`, 이미 숨김이면 그대로), `unhide(id) -> str | None`, `restore_hidden(id, hidden_at: str | None)`, `delete(id) -> Moment | None`.
- `store/views.py`: `moment_dict(m: Moment) -> dict`(6.5 `Moment` 모양, `sources`는 `task`·`habit`·`condition`·`chat` 종류만 중복 없이, `hidden`), `moment_counts(ms: list[Moment]) -> list[dict]`(`[{"date", "count"}]`, 최근부터).
- `status_snapshot(…, moments: MomentsRepo | None = None)`: `moments`(지난 14일, 숨기지 않은 것, 최대 20)와 `moments_hidden`. 저장소가 없으면 `[]`, `0`.
- `api/models.py`: `class Moment(_Model): id: int; date: str; text: str; area: AreaName | None; sources: list[Literal["task", "habit", "condition", "chat"]]; hidden: bool`, `class MomentsList(_Model): from_ (alias "from"); to: str; items: list[Moment]`, `Status`에 `moments: list[Moment]`, `moments_hidden: int`. `MODELS`에 `Moment`, `MomentsList`.
- `api/read.py`: `get_moments(conn, deps, request)`: `before`(`YYYY-MM-DD` fullmatch), `days`(1~60, 기본 14), `include_hidden`(`true|false`), 틀리면 `400 invalid_request`. 경로 `("/moments", get_moments)`.
- `MomentTools`: `hide_moment(ctx, id)`, `unhide_moment(ctx, id)`, `delete_moment(ctx, id)`: 없는 id는 `{"error": "없는 순간이에요.", "error_code": "not_found"}`, 이미 숨김은 `{"already": True}`. 활동 6.4 표 그대로(`target = moment_target(id) = "moment:<id>"`, summary는 날짜만), 숨기기 `undo={"moment_id", "hidden_at": None}`, 다시 보이기 `undo={"moment_id", "hidden_at": <이전 값>}`, 지우기 `undo=None`. `register_undo("moment_hidden", …)`, `register_undo("moment_unhidden", …)`(행이 없으면 `SUPERSEDED`).
- `tools/actions.py`: `ACTIONS`에 `hide_moment`, `unhide_moment`(`target=_moment_target`), `delete_moment`(`needs_confirm=moment_delete_needs_confirm`: 순간이 있으면 "이 순간을 지울까요? 되돌릴 수 없어요.", `target=_moment_target`). `_call`은 결과의 `error_code == "not_found"`를 `404 not_found`로.
- `Tools.get_status(ctx)`: 스냅샷의 `moments`를 지난 7일로 바꾸고, `ctx.channel == "app"`이면 `[moment_dict]`, 아니면 `moment_counts`(글 없음). 하네스가 고른다.
- `harness/context.py`: `moments_week_block(moments: MomentsRepo, review_day: date, *, with_text: bool) -> str`(`## 이번 주 이룬 순간`, 앱이면 `- 10/24 포트폴리오 사례 하나를 …`, 텔레그램이면 `- 10/24 2개`. 없으면 빈 문자열), `recent_areas_block(stats: list[dict]) -> str`(`## 요즘 손이 간 영역`, `- 건강 +1.5`, `bonus > 0`만). `Dispatcher`는 주간 회고 회차에서 둘을 붙이고, `with_text = (self.delivery.effective() == "app" if self.delivery else False)`.
- `system.md`: `## 이룬 순간` 절에 원칙 15·16(10.3 문장 그대로). `review_week.md`: 10.3의 한 줄.

**Slices**
- [ ] `tests/test_api_moments.py`:
  - `test_status_moments_14_days_not_hidden_max_20_order`, `test_status_moments_hidden_count`
  - `test_get_moments_range_from_to`(`before=2026-10-25&days=14` → `from` 10/11, `to` 10/24), `test_get_moments_include_hidden_marks_hidden`, `test_get_moments_bad_query_400`(`before=2026-13-01`, `days=0`, `days=61`, `include_hidden=yes`)
  - `test_sources_are_kinds_only`(`["task:12", "task:15", "chat"]` → `["task", "chat"]`)
  - `test_hide_then_undo_visible_again`, `test_unhide_then_undo_hidden_again`, `test_hide_twice_already`
  - `test_delete_needs_confirm_then_row_gone_not_undoable`, `test_deleted_moment_actions_404`, `test_deleted_day_not_reorganized`(날 행 `done` 그대로, 다음 날 tick에도 두뇌 안 부름)
  - `test_dashboard_reads_only`(`GET /status`만, 쓰기 경로 없음 — `tests/test_api_readonly.py`에 줄 추가)
- [ ] `tests/test_api_undo.py`: `test_undo_hide_after_delete_superseded`(Review Focus 4, `409 superseded`, 행 없음), `test_hide_and_unhide_block_each_other_u3`
- [ ] `tests/test_moments_tools.py`: `test_get_status_telegram_has_dates_and_counts_only`(결과 JSON 문자열에 시험 글 없음), `test_get_status_app_has_text_last_7_days`
- [ ] `tests/test_habit_context.py`(회고 앞머리): `test_review_preamble_moments_text_when_app`, `test_review_preamble_moments_counts_when_telegram`, `test_review_preamble_recent_areas_block`, `test_no_blocks_when_empty`
- [ ] `tests/test_prompts.py`: `test_system_prompt_has_principles_15_16`, `test_review_week_asks_one_moment_only_with_text`, 금지어 검사 통과
- [ ] 스키마 재생성, 대시보드 고정 자료 다시 쓰기.

**검증**
- [ ] `python -m pytest tests/test_api_moments.py tests/test_api_undo.py tests/test_moments_tools.py tests/test_habit_context.py tests/test_prompts.py -q` → `passed`
- [ ] BE 티켓 끝 검증 → `0 failed`

**마무리**
- [ ] **Review + Commit** `feat(api): moments on /status, GET /moments and hide/unhide/delete actions`

---

### 티켓 SP8-05: 2단계 화면

**목표:** 스펙 10.1 "이룬 순간" 패널(대시보드), 10.2 이룬 순간 블록·숨긴 순간·지난 순간(앱), 1장 조건 5.
**막는 티켓:** SP8-04, SP8-02

**Files:** 앱 Create `screens/StatusMoments.tsx`, `screens/StatusMoments.test.tsx`. Modify `screens/Status.tsx`, `screens/Status.module.css`, `lib/copy.ts`, `api/actions.ts`(`ActionName`에 `hide_moment`, `unhide_moment`, `delete_moment`), `src/test/fixtures/status.json`(순간 3개·숨김 1), `src/test/handlers.ts`, `e2e/routes.ts`(`GET /moments`). 대시보드 Create `components/MomentsPanel.tsx`. Modify `screens/StatusScreen.tsx`, `lib/labels.ts`, `screens/StatusScreen.test.tsx`.

**Interfaces**
- Consumes: `Status.moments`, `Status.moments_hidden`, `MomentsList`, `GET /moments`(SP8-04), `SwipeRow`, `ConfirmSheet`, `useAction`, `useToast`, `useUndo`(SP5).
- 공통 날짜 머리 `momentDay(date: string) -> "{M}월 {D}일 ({요일})"`(앱 `lib/copy.ts`, 대시보드 `lib/labels.ts`).
- 앱 `StatusMoments({ moments, hiddenCount, onChanged })`: 날짜 머리로 묶고 줄마다 영역 픽토그램(영역 없으면 `memory`) + 글. `SwipeRow` 동작 "숨기기", "지우기"(빨강 글자), 줄 끝 44px "더 보기" 버튼이 같은 두 동작의 시트. 숨기기 → 줄 접힘(200ms) + 토스트 "숨겼어요"/"되돌리기"(`undo_id`). 지우기 → `needs_confirm`이면 `ConfirmSheet`("이 순간을 지울까요? 되돌릴 수 없어요." / "지우기" / "그대로 두기") → 확인 토큰으로 다시 보낸다. 숨긴 순간 묶음 "숨긴 순간 {n}개"(접힘, 펼칠 때 `GET /moments?include_hidden=true`) 줄마다 "다시 보이기" → 토스트 "다시 보여요". "지난 순간 더 보기" → `GET /moments?before=<가장 이른 날짜>&days=14`를 이어 붙인다. 빈 상태 부록 A.
- 대시보드 `MomentsPanel({ moments })`: 읽기만, 끝 줄 "숨기거나 지우는 것은 운영 앱 상태창에서 할 수 있어요.", 빈 상태.

**Slices**
- [ ] 앱 `StatusMoments.test.tsx`: `groups_by_day_header`, `swipe_hide_collapses_and_toast_undo`, `more_button_opens_sheet_with_two_actions`, `delete_asks_confirm_then_sends_token`, `keep_closes_sheet_sends_nothing`, `hidden_group_lists_and_unhide`, `older_loads_14_more_days`, `empty_copy`, `offline_read_only`(동작 버튼 없음)
- [ ] 대시보드 `StatusScreen.test.tsx`: `moments_panel_groups_and_footer`, `moments_panel_empty_copy`, `dashboard_has_no_hide_or_delete`
- [ ] 앱 `copy.test.ts` 새 문구 검사 통과, `e2e/screens.spec.ts`의 `status`가 순간 블록까지(라이트·다크).

**검증**
- [ ] 앱·대시보드 티켓 끝 검증 → 통과. `cd web/app && npm run e2e -- --grep status` → passed

**마무리**
- [ ] **Review + Commit** `feat(web): moments block with hide/delete in the app, read-only panel on the dashboard`

---

### 티켓 SP8-06: 3단계 BE — 몸 기록 (014)

**목표:** 스펙 7.1~7.5, 1장 조건 8, 11장 `BODY_TOKEN` 줄.
**막는 티켓:** SP8-03(마이그레이션 번호 순서), SP8-00

**Files:** Create `store/migrations/014_body.sql`(7.1 그대로), `store/repos/body.py`, `tools/body.py`, `api/body.py`, `tests/test_api_body.py`. Modify `config.py`(`Settings.body_token`, `_Secrets.body_token` ← `BODY_TOKEN`, `load_settings`의 금지 열쇠에 `body_token`), `app.py`(`_body_token`), `api/server.py`(`ApiDeps.body_token`, 경로 등록, `auth`, `body_limit_middleware`), `api/cors.py`, `api/models.py`(`StatusBody`, `BodyPostBody`, `BodySaved`), `tools/actions.py`(`record_body_days`, `prune_records`에 56일), `tools/core.py`(`Tools(BodyTools, …)`, `body=`), `store/repos/status.py`(몸 기록 질의), `status/snapshot.py`(`body`), `tests/be_env.py`(`BeEnv.start(body_token=…)`), `tests/test_api_auth.py`, `tests/test_api_logging.py`, `tests/test_write_paths.py`, `tests/test_migrations.py`, `docs/superpowers/specs/2026-10-24-sp3-4-life-curve-dashboard-design.md` 6.2(`POST /body`).

**Interfaces**
- `store/repos/body.py`: `@dataclass(frozen=True) class BodyDay: date: date; steps: int | None; sleep_minutes: int | None`, `BodyRepo(conn, clock)`: `upsert(days: list[BodyDay], now)`(날짜마다 `INSERT … ON CONFLICT(date) DO UPDATE SET` 보낸 값만), `between(from_, to) -> list[BodyDay]`, `summary(today: date) -> dict | None`(7.5: 56일에 행이 없으면 `None`, `last_date`, `days_7`, `steps_avg_7`, `sleep_avg_7` 정수 평균), `prune(older_than: date) -> int`.
- `api/body.py`: `BODY_PATH = "/api/v1/body"`, `BODY_MAX_BYTES = 4096`, `parse_body_days(payload: Any, today: date) -> list[BodyDay] | str`(7.3 검증, 문구는 부록 A "몸 기록 API 오류" 여섯. `bool`과 `float`는 범위 오류 문구, Review Focus 2), `post_body(request, deps) -> web.Response`: 본문을 읽어 4KB를 넘으면 413, JSON 아니면 400, `today = local(now, tz).date()`(한국 달력), `deps.dispatcher.apply_action(ActionRequest("record_body_days", {"days": [...]}, actor="user", channel="app", endpoint="body"))`, `200 {"saved": n}`. 로그 `body_received {days: n}`.
- `tools/actions.py`: `RequestEndpoint`에 `"body"`, `ACTIONS["record_body_days"] = ActionSpec("record_body_days", public=False, endpoint="body")`(그래서 `/actions`에서는 `400 invalid_request`). `api_idempotency`에 쓰지 않는다(`client_msg_id` 없음).
- `tools/body.py`: `class BodyTools`: `record_body_days(ctx, days: list[dict]) -> dict`: `BodyRepo.upsert`, 활동·경험치 없음, `{"saved": n}`.
- `api/server.py`: `auth`는 `expected = deps.body_token if route_template(request) == BODY_PATH else deps.token`. `build_app`은 `deps.body_token`이 있을 때만 `POST BODY_PATH` 등록. `body_limit_middleware`는 경로 틀이 `BODY_PATH`면 4KB.
- `api/cors.py`: `request.path == BODY_PATH`면 헤더 없이 `call_json(handler, request)`(사전 요청도 204로 끝내지 않는다).
- `app._body_token(settings: Settings, api_token: str) -> str | None`: 없거나 43자 미만이거나 `api_token`과 같으면 `None`과 경고 `body_token_missing {reason: missing|too_short|same_as_api}`(값 없음).
- `StatusRepo.activity_rows`가 `body_days`를 읽는다. `status_snapshot(…, body: BodyRepo | None = None)` → `body`. `Status.body: StatusBody | None`. 건강 `activity.body_days`는 7.4.

**Slices**
- [ ] `tests/test_migrations.py`: `test_014_body_checks`(걸음 −1·100001, 잠 1441, 둘 다 NULL 거절), `test_latest_version_is_014`
- [ ] `tests/test_api_body.py`:
  - `test_saves_three_days_returns_saved_only`(응답 `{"saved": 3}`)
  - `test_validation`(parametrize: 모르는 최상위 키, 항목의 모르는 키, 8일, 겹친 날짜, 미래, 14일 밖, 범위 밖, `null`, 둘 다 없음 → 400과 부록 A 문구, 아무것도 안 씀)
  - `test_body_rejects_bool_and_float_values`(Review Focus 2)
  - `test_today_calendar_date_accepted_at_0230`(10/26 02:30에 `2026-10-26` 받음, 보너스 셈에서는 04:00 전 `d = −1`이라 빠지고 04:00 뒤 들어감)
  - `test_overwrite_only_sent_values`(잠만 보내면 걸음 그대로)
  - `test_api_token_on_body_401`, `test_body_token_on_status_401`, `test_actions_record_body_days_rejected_400`
  - `test_route_closed_when_token_missing_short_or_same`(parametrize 셋: `API_TOKEN`으로 `/body` → 404, `BODY_TOKEN`만 → 401, 경고 한 줄)
  - `test_over_4kb_413_other_routes_keep_limit`(`/actions` 10KB는 413 아님)
  - `test_no_cors_headers_and_no_preflight`(허용 출처 `Origin`으로 `POST`·`OPTIONS` → `Access-Control-Allow-Origin` 없음, `OPTIONS`는 204 아님)
  - `test_auth_failures_shared_limit`(`/body`와 `/status` 실패가 함께 10회 → 429)
  - `test_prune_56_days`, `test_health_bonus_from_body`(걸음 ≥ 6000 28일 + 습관 28일 → 2.0, `activity.body_days == 28`), `test_status_body_summary_and_null`
  - `test_no_activity_no_xp_for_body`
- [ ] `tests/test_api_logging.py::test_body_logs_have_no_numbers_or_token`(걸음 `8123`, 잠 `412`, `BODY_TOKEN` 값이 로그에 없음, `body_received` 줄은 `days`만)
- [ ] `tests/test_write_paths.py`: `TOOLS`에 `"my_planner.tools.body"`, `ENTRIES`에 `"my_planner.api.body"`, `ALLOWED`에 `"body_days": set(TOOLS)`
- [ ] 스키마 재생성, 대시보드 고정 자료 다시 쓰기.

**검증**
- [ ] `python -m pytest tests/test_api_body.py tests/test_api_auth.py tests/test_api_logging.py tests/test_migrations.py -q` → `passed`
- [ ] BE 티켓 끝 검증 → `0 failed`

**마무리**
- [ ] **Review + Commit** `feat(body): POST /body with its own token, body_days and health bonus`

---

### 티켓 SP8-07: 3단계 화면과 안내

**목표:** 스펙 7.5 화면, 7.6, 10.1 건강 근거 줄, 10.2 몸 기록 줄. 실제 아이폰으로 단축어 순서를 확인하는 일은 사람 관문 H2.
**막는 티켓:** SP8-06, SP8-02

**Files:** 대시보드 Create `components/BodyLine.tsx`. Modify `screens/StatusScreen.tsx`, `lib/labels.ts`, `screens/StatusScreen.test.tsx`. 앱 Modify `screens/Status.tsx`, `lib/copy.ts`, `screens/Status.test.tsx`, `src/test/fixtures/status.json`. 문서 Modify `README.md`("iPhone 단축어" 절), `.env.example`(`BODY_TOKEN=` 한 줄과 설명), `README.md`에 `moments_paused` 한 줄(16장).

**Interfaces**
- Consumes: `Status.body`(SP8-06).
- `bodyLine(body: StatusBody) -> string`(두 앱, 같은 글): "몸 기록 · 지난 7일 걸음 평균 {n} · 잠 평균 {h}시간 {m}분"(값이 `null`인 부분은 뺀다, 걸음은 `toLocaleString("ko-KR")`), `bodyLast(date) -> "마지막 기록 {M}/{D}"`.
- 대시보드 `BodyLine({ body })`: 건강 줄 아래 `caption`, `body === null`이면 그리지 않는다.
- 앱: 건강 줄 아래 `bodyLine` + `bodyLast`, `null`이면 연결 안내(부록 A).
- README "iPhone 단축어": 7.6 1~6 순서의 뼈대, "숫자 반올림" 단계(Review Focus 2), 공유 금지·토큰 바꾸기 두 문장. 화면 이름은 H2에서 실제 순서로 고친다.

**Slices**
- [ ] 대시보드 `StatusScreen.test.tsx`: `body_line_under_health`, `body_line_omits_missing_values`, `no_body_line_when_null`, `no_warning_when_old`(오래된 기록에도 경고 문구 없음)
- [ ] 앱 `Status.test.tsx`: `body_line_and_last_date`, `connect_hint_when_null`
- [ ] `copy.test.ts`·`banned-words.test.ts` 통과("부족", "목표" 없음: 7.4, 12장)

**검증**
- [ ] 앱·대시보드 티켓 끝 검증 → 통과
- [ ] `grep -n "BODY_TOKEN" .env.example README.md` → 각 1줄 이상

**마무리**
- [ ] **Review + Commit** `feat(web): body line on both status screens, README iPhone shortcut skeleton`

---

### 티켓 SP8-08: 히스토리 BE (015)

**목표:** 스펙 8.1, 8.2, 8.7의 BE·텔레그램·프롬프트 쪽.
**막는 티켓:** SP8-06(마이그레이션 번호 순서)

**Files:** Create `store/migrations/015_curve_history.sql`(8.1 그대로), `curve/history.py`, `tests/test_curve_history.py`. Modify `store/repos/curve.py`, `store/repos/conditions.py`, `curve/model.py`, `curve/seed.py`, `cli.py`, `tools/core.py`(`add_milestone`, `propose_chapter`, `confirm_milestones`), `tools/mcp_adapter.py`(두 도구 스키마·설명), `tools/confirmations.py`(`KIND_LABELS`, `milestone_confirmed_line`, `_SAVE_TAIL`), `store/exports.py`(`_KIND`), `harness/prompts/{system,review_year}.md`(예시 말 "높은 때"), `api/read.py`, `api/models.py`, `api/server.py`, `docs/superpowers/specs/2026-10-24-sp3-4-life-curve-dashboard-design.md` 6.2(`GET /curve/history`), `GLOSSARY.md`(사건 종류 화면 이름). Regenerate schema/types, 대시보드 고정 자료(+ `curve-history.json`, `curve-history-empty.json` 새 `CASES`). Test `tests/test_api_curve_status.py`, `tests/test_seed_life.py`, `tests/test_curve_tools.py`, `tests/test_telegram_curve.py`, `tests/test_migrations.py`.

**Interfaces**
- `Milestone.area: str | None`, `Chapter.ladder_remembered: int | None`. `CurveRepo.add_milestone(…, area: str | None = None)`, `add_chapter(…, ladder_remembered: int | None = None)`, `fill_history(milestone_areas: dict[int, str], chapter_ladders: dict[int, int]) -> tuple[int, int]`(`NULL`인 칸만), `earliest_ladder_period() -> str | None`. `ConditionsRepo.earliest() -> date | None`.
- `curve_view`의 사건에 `area`, `origin`, `kind_certainty`, 챕터에 `ladder_remembered`. `CurveMilestone`·`CurveChapter` 모델 필드 추가.
- `curve/history.py`: `curve_history(curve: CurveRepo, conditions: ConditionsRepo, *, today: date, include_sensitive: bool) -> dict`(8.2 모양 그대로). 규칙: 확정만, 챕터 `start` 최근부터, 사건 `sort_date` 최근부터, `ladder` 기억 → 그 기간 월별 `now` 평균(소수 한 자리) → `null`, 민감 사건은 `include_sensitive=false`면 `hidden_sensitive {count, years(오름차순, 중복 없음)}`만(제목·메모가 본문에 없다), `summary`(8.2의 각 값, `longest.years = round_half_up(달 차 / 12)`, 끝나지 않은 챕터는 오늘 달까지).
- `api/models.py`: `HistoryLadder(value: float, source: Literal["remembered", "recorded"])`, `HiddenSensitive(count: int, years: list[int])`, `HistoryEvent`, `HistoryChapter`, `HistoryUnassigned`, `HistoryHighest`, `HistoryTurningPoints`, `HistoryLongest`, `HistorySummary`, `CurveHistory`. `MODELS`에 `CurveHistory`. 경로 `("/curve/history", get_curve_history)`.
- `Tools.add_milestone(…, area=None)`: 6개 영역 코드가 아니면 오류. `Tools.propose_chapter(…, ladder=None)`: 정수 0~10이 아니면 오류. `confirm_milestones` 이벤트 데이터에 `area`.
- `confirmations.KIND_LABELS = {"high": "높은 때", "low": "힘든 때", "turning_point": "전환점"}`, `milestone_confirmed_line(title, date_text, kind, area: str | None = None)` → `"✓ 저장: 제주 여행 (2019, 높은 때, 삶의 질)"`(영역 없으면 지금 모양), `_SAVE_TAIL`은 새 이름과 영역 꼬리를 받는다. `exports._KIND`도 같은 이름.
- `curve/seed.py`: `SeedChapter.ladder: int | None`, `SeedEvent.area: str | None`(틀리면 그 항목 `invalid`), `apply_seed`가 쓴다. `SkipReason`에 `"ambiguous"`. `plan_history_update(seed, curve: CurveRepo) -> HistoryPlan`(`milestone_areas`, `chapter_ladders`, `skipped`), `run_update_history(root, file, *, dry_run, out=None, lock_factory=SingleInstanceLock, clock=None) -> int`: 잠금(코드 3) → 파일(6) → 검토(5) → 시드를 아직 안 가져왔으면 코드 7 → `life_seed_history_updated_at`가 있으면 "이미 채웠어요." 코드 4 → 계획 출력 "채울 것: 사건 영역 {n}, 챕터 사다리 {m}", "건너뛸 것: {k} (sensitive_unconfirmed …, storage_unconfirmed …, invalid …, ambiguous …)" → 쓰기 → 키 적기. `EXIT_NOT_IMPORTED = 7`.
- `cli.py`: `seed-life [--update-history] <파일> [--dry-run]`, `USAGE` 고침.

**Slices**
- [ ] `tests/test_migrations.py`: `test_015_area_and_ladder_checks`(틀린 area, ladder 11 거절), `test_015_keeps_curve_rows`(기존 행 그대로, 새 칸 NULL), `test_schema_version_15`(`LATEST_VERSION == 15`, 원장 그대로)
- [ ] `tests/test_curve_history.py`: `test_chapters_recent_first_events_inside_recent_first`, `test_unassigned_group`, `test_ladder_source_remembered_then_recorded_avg_then_null`(기록 평균 6.25 → 6.3), `test_sensitive_hidden_count_years_and_title_absent_from_body`(본문 JSON 문자열에 시험 제목 없음), `test_include_sensitive_true_marks_and_zero_hidden`, `test_summary_values`(highest 같으면 최근, turning_points 해, longest 반올림, records_since, since_year), `test_empty_db_shape`, `test_drafts_excluded`
- [ ] `tests/test_api_curve_status.py`: `test_curve_has_area_origin_kind_certainty_and_ladder_remembered`, `test_curve_history_route_and_schema`
- [ ] `tests/test_seed_life.py`: `test_event_area_and_chapter_ladder_imported`, `test_bad_area_or_ladder_invalid`, `test_update_history_fills_empty_only`, `test_update_history_confirm_rules`, `test_update_history_ambiguous_counted`, `test_update_history_output_has_no_content`, `test_update_history_second_run_code_4`, `test_update_history_lock_code_3`, `test_update_history_before_import_code_7`, `test_update_history_dry_run_writes_nothing`
- [ ] `tests/test_curve_tools.py`: `test_add_milestone_area_validated`, `test_propose_chapter_ladder_validated`
- [ ] `tests/test_telegram_curve.py`: `test_confirmed_line_with_area`("✓ 저장: 제주 여행 (2019, 높은 때, 삶의 질)"), `test_confirmed_line_without_area`("(2019, 힘든 때)"), `test_button_text_unchanged`("✓ 저장: {제목}"), `test_undo_summary_strips_new_tail`
- [ ] `tests/test_prompts.py::test_prompts_use_new_kind_names`(프롬프트·도구 설명에 "고점", "저점" 없음)

**검증**
- [ ] `python -m pytest tests/test_curve_history.py tests/test_api_curve_status.py tests/test_seed_life.py tests/test_curve_tools.py tests/test_telegram_curve.py tests/test_migrations.py -q` → `passed`
- [ ] `grep -rn "고점\|저점" src/my_planner --include=*.py --include=*.md` → 빈 출력(주석 포함, 8.7)
- [ ] BE 티켓 끝 검증 → `0 failed`

**마무리**
- [ ] **Review + Commit** `feat(curve): history columns, GET /curve/history, seed --update-history, kind names`

---

### 티켓 SP8-09: 히스토리 화면 1

**목표:** 스펙 8.3, 8.4, 8.7의 화면 쪽.
**막는 티켓:** SP8-08, SP8-01

**Files:** Create `web/dashboard/src/screens/HistoryView.tsx`, `components/HistoryChapter.tsx`, `components/HistoryFilters.tsx`, `lib/history.ts`, `lib/history.test.ts`, `screens/HistoryView.test.tsx`. Modify `screens/CurveScreen.tsx`(탭), `lib/labels.ts`(`HISTORY_TEXT`, `CURVE_TEXT.kinds` → 높은 때·힘든 때, `STATUS_TEXT.titlesEmpty`의 "고점"), `lib/api.ts`(`isCurveHistory`), `components/MilestonePopover.tsx`(종류 이름은 labels에서), `screens/CurveScreen.test.tsx`.

**Interfaces**
- Consumes: `CurveHistory`(SP8-08), `Pictogram`, `MilestonePopover`.
- `lib/history.ts`(순수): `type HistoryFilter = "all" | "high" | "low" | "turning_point"`, `filterEvents(events, f)`, `orderChapters(h: CurveHistory, order: "recent" | "oldest") -> Array<HistoryChapter | "unassigned">`(`unassigned`는 최근부터면 끝, 오래된 것부터면 앞), `collapsedOnPhone(chapters, expanded: Set<number>) -> Set<number>`(최근 4개만 펼침), `yearsText(start, end) -> "2019 – 2022" | "2026 –"`, `eventDateText(date, precision) -> "2019.03" | "2018"`.
- `CurveScreen`: 머리 아래 분할 버튼 `곡선 | 히스토리`(픽토그램 `curve`, `list`), 고른 탭은 `router.replace({ query: { tab } }, undefined, { shallow: true })`, 기본 곡선. 히스토리 탭은 `GET /curve/history`를 읽는다.
- `HistoryView({ history, isPhone })`: 부제(8.3), 거르기 알약 넷(44px, `aria-pressed`), 정렬 글자 버튼, 챕터 목록, 빈 상태. 거르기·정렬·펼침은 모듈 메모리(`memory`, `resetCurveMemory()`가 함께 비운다), `localStorage` 없음.
- `HistoryChapter`: 머리 줄(`chapter`, 제목, 해, 추정 태그 `estimate`), 둘째 줄(`ladder` + "그때 사다리 6" | "사다리 평균 6.3", " · 사건 {n}개"), 메모 줄(없고 추정이면 "기억으로 그린 시기예요."), 사건 줄(52px 이상, 36px 원 `--raised` 안 종류 픽토그램, 제목, 날짜(추정이면 앞에 "추정"), 메모, 태그: 종류 이름(종류 추정이면 "높은 때 · 추정"), 영역 태그(영역 픽토그램 영역색 + 이름 `--text-2`), `origin = chat`이면 `assistant` + "비서가 만듦"(`--hue`)). 줄을 누르면 `MilestonePopover`. 고른 종류가 없는 챕터는 "이 시기에는 고른 종류의 사건이 없어요."

**Slices**
- [ ] `lib/history.test.ts`: `filter_by_kind`, `unassigned_last_when_recent_first_and_first_when_oldest`, `phone_expands_recent_4`, `years_text_open_end`, `event_date_text_month_and_year`
- [ ] `HistoryView.test.tsx`: `tab_in_url_survives_reload`(`?tab=history`로 열면 히스토리), `default_tab_is_curve`, `chapter_rows_and_tags`, `assistant_tag_only_for_chat_origin`, `estimate_marks`, `empty_kind_message_keeps_chapter_header`, `sort_toggle`, `phone_folded_chapter_expands`, `empty_state_copy`, `row_opens_popover`, `no_local_storage_writes`(`Storage.prototype.setItem` 0회)
- [ ] `CurveScreen.test.tsx`: `kind_names_are_new`(팝오버에 "높은 때"), 기존 시험 그대로 통과. `grep -rn "고점\|저점" web/dashboard/src web/app/src --include=*.ts --include=*.tsx` → 빈 출력

**검증**
- [ ] 대시보드 티켓 끝 검증 → 통과

**마무리**
- [ ] **Review + Commit** `feat(dashboard): history tab with chapters, events, filters and sort`

---

### 티켓 SP8-10: 히스토리 화면 2

**목표:** 스펙 8.5, 8.6.
**막는 티켓:** SP8-09

**Files:** Create `web/dashboard/src/components/GlanceStrip.tsx`, `components/HistorySummary.tsx`, `components/GlanceStrip.test.tsx`. Modify `screens/HistoryView.tsx`, `components/HistoryChapter.tsx`, `screens/CurveScreen.tsx`(민감 상태 공유), `lib/labels.ts`, `lib/history.ts`(`glanceLayout`), `screens/HistoryView.test.tsx`.

**Interfaces**
- 민감 상태는 곡선 탭의 `memory.sensitive` 하나다: 히스토리 토글 "민감한 사건 가림"의 켜짐 = `!memory.sensitive`. 챕터별 펼침은 `Set<number>`(그 탭 메모리). "보기"를 처음 누르면 `GET /curve/history?include_sensitive=true`를 한 번 받아 그 챕터의 민감 사건만 펼친다(태그 `eye` "민감", 줄 끝 "가리기"). 가려 둔 줄: `eyeoff` + "가려 둔 사건 {n}개 · {해들}" + "보기".
- `lib/history.ts`: `glanceLayout(h: CurveHistory, width: number, today: string) -> { ticks: {x, label}[]; bands: {chapterId, x, w, dashed, ladderY: number | null}[]; marks: {eventId, x, kind}[] }`(x축 `since_year` → 오늘, 눈금 첫 해·10년 단위·올해, 사다리 0~10 → 띠 높이).
- `GlanceStrip({ history, width })`: 맨 SVG(`viewBox` 폭 = 실제 폭), 띠 `--raised` + 1px `--rule`(추정은 점선), 사다리 가로선 2px `--text`, 사건 16px 종류 픽토그램(`role="img"`, `aria-label` = 종류 이름 + 제목), 곡선 아래 칠하기·영역색 면 없음. 같은 내용의 화면 읽기용 표(챕터, 해, 사다리, 사건 수). 가린 사건은 그리지 않는다.
- `HistorySummary({ summary })`: 8.6 네 줄(값이 `null`이면 뺌), 도움 상자(`assistant`, 부록 A).

**Slices**
- [ ] `HistoryView.test.tsx`: `hidden_line_counts_years`, `show_fetches_once_and_expands_that_chapter_only`, `hide_folds_again`, `toggle_off_expands_all_and_matches_curve_tab`(곡선 탭 "민감한 사건 보기"가 켜져 있으면 히스토리 토글은 꺼짐), `sensitive_title_not_in_dom_before_show`
- [ ] `GlanceStrip.test.tsx`: `ticks_first_decades_and_this_year`, `estimate_band_dashed`, `ladder_line_height_or_none`, `marks_have_labels_and_table_matches`, `hidden_events_not_drawn`, `no_area_fill_or_area_under_curve`
- [ ] `HistoryView.test.tsx`: `summary_lines_omit_null`, `no_ratio_rank_or_lowest_words`("%", "순위", "가장 낮았던" 없음), `help_box_copy`, `desktop_side_summary_and_phone_order`(720px 기준)

**검증**
- [ ] 대시보드 티켓 끝 검증 → 통과

**마무리**
- [ ] **Review + Commit** `feat(dashboard): sensitive events, glance strip with table, side summary`

---

### 티켓 SP8-11: 수용

**목표:** 스펙 1장 완료 조건 1~12, 13장 "이야기", "로그·개인정보". 노트북 확인은 사람 관문 H3.
**막는 티켓:** SP8-05, SP8-07, SP8-10

**Files:** Create `tests/test_sp8_story.py`. Modify `tests/test_write_paths.py`(시나리오에 `test_sp8_story` 흐름), `tests/test_api_logging.py`.

**Slices**
- [ ] `test_sp8_story`(`BeEnv`, 가짜 두뇌·시계, 꾸며 낸 4주, `start=kst(2026, 9, 28, 12, 0)`):
  - 건강 영역 점수 4(Q4), 매일 습관 체크 28일, 커리어 할 일 월·수·금 → 10/25 `GET /status`의 건강 `bonus == 1.5`, `effective_score == 5.5`, 커리어 `bonus == 1.2`
  - 10/26 04:01 tick → 10/25 순간 작업: FakeBrain `save_moments` 2개 → `GET /status.moments` 2개. 앱 `/actions hide_moment` 하나, `delete_moment` 하나(`needs_confirm` → 토큰) → `moments == []`, `moments_hidden == 1`
  - `POST /body`(`BODY_TOKEN`) 3일 → `body.days_7 == 3`
  - 시계를 사흘 넘기고(tick 없음) 10/29 04:01 tick → 10/26~10/28 차례로 정리(두뇌 호출 순서 = 날짜 순)
  - 텔레그램 `/status` 글이 같은 DB의 SP7 기준 글과 같다(새 줄 없음), 텔레그램 대화에서 `get_status`를 부른 결과 JSON에 순간 글이 없다
  - `GET /curve/history` 200, 스키마에 맞음
  - → `passed`
- [ ] `test_sp8_logs_exports_and_summaries_clean`: 위 흐름 뒤 `state/logs/`, `data/exports/`, `data/transcripts/`, `activity.summary`에 시험 순간 글·걸음 숫자·`BODY_TOKEN`이 없다. `data/exports/`에 순간 파일 없음 → `passed`
- [ ] `test_sp8_write_paths`: `tests/test_write_paths.py`의 감시가 SP8 흐름에서도 통과(새 표는 `ALLOWED`의 모듈만 씀) → `passed`
- [ ] 앱 `npm run e2e` → 모든 화면(라이트·다크·프리셋) passed, `status` 화면 포함
- [ ] BE·앱·대시보드 티켓 끝 검증 전부 → 통과

**마무리**
- [ ] **Review + Commit** `test: SP8 end-to-end story and privacy checks`

---

## 사람 관문 (노트북·Dahun, 티켓 머지를 막지 않는다)

맨 뒤에 따로 둔다. H1~H3이 끝나야 스펙 상태를 "확정"으로 바꾼다.

### H1: 스파이크 S-SP8-1 (`needs-laptop`, 스펙 6.3, SP8-03의 첫 단계)

- [ ] 노트북에서 `~/.claude/projects` 아래 파일 목록을 적어 둔다(`Get-ChildItem -Recurse ~/.claude/projects | Measure-Object` 개수와 가장 최근 시각).
- [ ] SP8-03이 들어간 BE로 순간 작업 한 번(데이터가 있는 어제, `moments_since`를 그 전날로)을 돌린다. `status_moment_days` 그날 `done`.
- [ ] 다시 목록을 본다 → **새 `.jsonl`이 없다**. 결과 한 단락을 `docs/spikes/2026-11-sp8.md`에(파일 개수, 시각만. 경로·내용 없음).
- [ ] 실패하면(새 파일이 생김): 스펙 6.3의 대안("호출 뒤 그 `session_id`의 jsonl을 지운다")으로 바꾸는 작은 티켓을 만들고 스펙 6.3을 고친다. **Commit** `docs: SP8 spike S-SP8-1 session persistence`

### H2: iPhone 단축어 설정 (`needs-Dahun`, 스펙 7.6, SP8-07)

- [ ] Dahun이 `gen-token` → `.env`의 `BODY_TOKEN` → BE 다시 시작 → `/health` `ok`.
- [ ] 7.6-3의 단축어를 실제 아이폰에서 만든다. 동작 이름과 수면 합산 순서를 화면 순서대로 README "iPhone 단축어"에 고쳐 적는다(스크린숏 없음, 토큰 값 없음).
- [ ] 손으로 한 번 실행 → `{"saved": n}`, 운영 앱 상태창 몸 기록 줄이 바뀜. 자동화 매일 09:00 "바로 실행".
- [ ] **Commit** `docs: README iPhone shortcut, verified on device`

### H3: 노트북 수용 (`needs-laptop`, 스펙 13장 "노트북 수용", SP8-11)

- [ ] H1 단락이 있다.
- [ ] 실제 두뇌로 하루 끝 순간이 한 번 생긴다(텔레그램 메시지 없음, 웹 푸시 없음). 운영 앱 상태창에서 숨기기 → 되돌리기, 지우기(확인 시트).
- [ ] 실제 단축어 한 번 → 대시보드 건강 근거 줄.
- [ ] 대시보드 `/status/`, `/curve/?tab=history`를 라이트·다크로 연다(대시보드에는 Playwright가 없다: 눈으로 확인, 결과 한 줄을 `docs/spikes/2026-11-sp8.md`에).
- [ ] 스펙 상태를 "확정"으로, 변경 기록 한 줄. **Commit** `docs: SP8 accepted on the laptop`

### H4: Dahun 검토 (`needs-Dahun`, 스펙 17장·부록 A·아래 문구 표)

- [ ] 한 번에 묻는다. "추천대로"면 통과. 바뀐 숫자는 `status/activity.py`·`harness/moments.py` 상수와 스펙 표를, 바뀐 문구는 `lib/copy.ts`·`lib/labels.ts`·`confirmations.py`와 부록 A를 같은 PR에서 고친다.

---

## 문구 표 (Dahun 확인 H4)

스펙 부록 A 밖에서 이 계획이 더한 문구다.

| 자리 | 문구 |
|---|---|
| `/actions` 없는 순간(404) | "없는 순간이에요." |
| `GET /moments` 오류(400) | "before는 YYYY-MM-DD 형식이에요.", "days는 1~60 사이예요.", "include_hidden은 true나 false예요." |
| `add_milestone` 영역 오류 | "area는 career, finance, health, relationships, learning, quality_of_life 가운데 하나예요." |
| `propose_chapter` 사다리 오류 | "ladder는 0~10 사이의 정수예요." |
| `seed-life --update-history` 시드 없음(코드 7) | "아직 가져온 시드가 없어요. 먼저 seed-life로 가져와 주세요." |
| 대시보드 `titlesEmpty`(8.7로 바뀜) | "높은 때나 전환점을 곡선에 남기면 칭호가 생겨요." |

## 스펙과 코드가 맞지 않는 곳 (이 계획의 결정)

| # | 스펙 자리 | 맞지 않는 곳 | 결정 (티켓) |
|---|---|---|---|
| 1 | 7.2 "요청 `channel = "body"`" | `ActionRequest.channel`은 `ActivityChannel`(`app`·`telegram`·`scheduler`)이고 `activity.channel` CHECK도 셋뿐이다. "그 경로에서만" 규칙은 이미 `ActionSpec.endpoint` + `_callable_from`이 한다 | `endpoint="body"`(`RequestEndpoint`에 더함), `channel="app"`, `actor="user"`. `/actions`에서는 `400 invalid_request` (SP8-06). 스펙 7.2를 "endpoint = body"로 고친다 |
| 2 | 6.3 `tool_names_for`를 `RunContext`를 받게 | 시험 6개 파일이 `tool_names_for("telegram")`을 부른다 | 스펙대로 `tool_names_for(ctx: RunContext)`, 그 시험들을 `RunContext(None, None, channel=…)`로 고친다 (SP8-03) |
| 3 | 6.3 `RunContext(kind="moments", …)`, M1 "이 작업의 날짜", sources "입력에 나온 참조" | 도구가 작업 날짜와 참조 목록을 받을 자리가 없다 | `RunContext.moments_date`, `RunContext.moments_refs`를 더한다 (SP8-03) |
| 4 | 5.6 `area_points(tasks, checks, body, today)`, `area_bonus(points, today)`가 `counts`를 담음 | 할 일의 논리적 날짜에는 `tz`·`boundary`가 필요하고, 상한을 적용한 점수에서는 가중하지 않은 개수를 다시 셀 수 없다 | 키워드 `tz`, `boundary`를 더하고 `activity_counts(...)`를 따로 두어 `area_bonus(points, today, counts)`로 넘긴다 (SP8-00) |
| 5 | 6.2-5 "`brain.auth`가 `ok`가 아님"이면 멈춤 | 설치 직후 두뇌를 한 번도 안 불렀으면 값이 없다(`unknown`). 그대로면 대화가 한 번 있기 전까지 순간이 영영 안 생긴다 | `login`·`billing`일 때만 멈춘다 (SP8-03) |
| 6 | 6.2-5 "안전 모드"면 멈춤 | 안전 모드에서는 러너·디스패처를 만들지 않는다(`app.py`): 작업이 돌 일이 없다 | 따로 검사하지 않는다 (SP8-03) |
| 7 | 6.2-4 "디스패처의 직렬 작업자", `Dispatcher.stop`은 "큐에 든 것까지" | 멈출 때 순간 작업 7개가 남으면 두뇌를 7번 부른다 | 멈추는 중에는 순간 작업을 건너뛴다(`pending` 그대로) (SP8-03, Review Focus 1) |
| 8 | 6.3 입력 "`TranscriptStore.read_range`의 사용자 줄만" | `read_range`는 머리글이 섞인 원문 문자열을 돌려준다 | `TranscriptStore.user_lines(day)`를 더해 같은 파일의 `사용자` 줄만 읽는다 (SP8-03) |
| 9 | 6.4 "이미 지운 순간을 가리키는 동작은 `404`" | 즉시 갈래는 도구 오류를 늘 `422 rejected`로 바꾼다 | 도구 결과 `error_code == "not_found"`를 `_call`이 `404 not_found`로 (SP8-04) |
| 10 | 6.7·10.3 "앱 통로(`RunContext.channel == "app"`)" | 회차 차례의 `RunContext.channel`은 전달 통로와 상관없이 늘 `telegram`이다 | 회고 앞머리 블록은 실제 전달 통로(`delivery.effective()`)로 고르고, 회차 차례의 `get_status`는 `ctx.channel` 그대로(=개수만, 더 좁은 쪽) (SP8-04) |
| 11 | 8.7 "앱 사건 초안 카드"의 종류 이름 | 앱 `MilestoneDraft`는 종류 이름을 보이지 않는다 | 앱은 고칠 곳이 없다. 대시보드 `labels.ts`(`kinds`, `titlesEmpty`)와 BE `confirmations.py`, `exports.py`, 프롬프트·도구 설명을 고친다 (SP8-08, SP8-09) |
| 12 | 10.1 "한눈에 홈(`index`, `HomePhone2`)의 칸 머리 픽토그램과 '히스토리 보기' 링크" | 대시보드 `/`는 `HealthScreen`("비서 상태")이고 컨디션·사다리·챕터 칸이 있는 홈이 없다(`HomePhone2`는 캔버스 초안) | 이번에는 내비게이션 픽토그램만 더한다(`/`에 `home`). 홈 칸 머리와 링크는 홈 화면이 생기는 티켓으로 미룬다. 스펙 10.1을 그렇게 고친다 (SP8-02) |
| 13 | 13장 대시보드 "라이트·다크 스냅샷" | 대시보드에는 Playwright·스크린숏 장치가 없다(앱만 `e2e/`) | 새 의존성을 넣지 않고 H3에서 눈으로 확인한다. 앱은 지금처럼 `npm run e2e` (SP8-11, H3) |
| 14 | 9.3-6 DESIGN.md 문장 | 지금 문장은 종류를 "높은 때·**낮은 때**·전환점"이라 부른다(8.7은 "힘든 때") | "힘든 때"로 맞춘다 (SP8-01) |
| 15 | 8.1 `--update-history`, `life_seed_imported_at`이 없을 때 | 스펙은 "이미 가져온 시드"만 말한다. 그대로 돌면 아무것도 안 채우고 `life_seed_history_updated_at`만 적혀 나중에 채울 수 없다 | 코드 7과 안내 한 줄(문구 표), 아무것도 쓰지 않는다 (SP8-08) |
| 16 | 8.2 `ladder.value` 예시 `6` | 기억 값은 정수, 기록 평균은 소수다 | 모델은 `float` 하나, 화면은 정수면 "6", 아니면 소수 한 자리 (SP8-08, SP8-09) |
| 17 | 6.4 60일 정리, 7.1 56일 정리 "하루 한 번 작업" | 하루 한 번 작업의 표 쓰기는 즉시 갈래로 한다(SP3-4 4.3) | 내부 동작 `prune_records`(`public=False`) 하나로 둘 다 지운다 (SP8-03, SP8-06) |

## 스펙 대비 확인 (셀프 리뷰)

| 스펙 | 티켓 |
|---|---|
| 1장 조건 1·2 | SP8-00, SP8-02, SP8-11 |
| 1장 조건 3·4 | SP8-03(`test_moments_job.py`), SP8-11 |
| 1장 조건 5 | SP8-04, SP8-05, H3 |
| 1장 조건 6 | SP8-03 `test_no_xp_from_moments` |
| 1장 조건 7 | SP8-03 로그·원문 기록, SP8-04 통로, SP8-11 `test_sp8_logs_exports_and_summaries_clean`, H1 세션 파일 |
| 1장 조건 8 | SP8-06 |
| 1장 조건 9 | SP8-08, SP8-09, SP8-10 |
| 1장 조건 10 | SP8-01 |
| 1장 조건 11 | SP8-02(금지 구), 각 화면 티켓의 `no_decline_marks`·`no_ratio_*`, SP8-03 M3 |
| 1장 조건 12 | 각 티켓 검증, SP8-11 |
| 5장 | SP8-00(BE), SP8-02(화면) |
| 6.1~6.3, 6.8 | SP8-03 |
| 6.4~6.7 | SP8-04, SP8-05 |
| 7.1~7.5 | SP8-06, SP8-07 |
| 7.6 | SP8-07(뼈대), H2 |
| 8.1, 8.2, 8.7(BE) | SP8-08 |
| 8.3, 8.4, 8.7(화면) | SP8-09 |
| 8.5, 8.6 | SP8-10 |
| 9장 | SP8-01 |
| 10.1 | SP8-02, SP8-05, SP8-07(홈 칸은 표 12로 미룸) |
| 10.2 | SP8-02, SP8-05, SP8-07 |
| 10.3 | SP8-04(텔레그램 `/status` 그대로: SP8-00 `test_telegram_status_text_unchanged_by_bonus`) |
| 11장 | SP8-03, SP8-06, SP8-11 |
| 13장 표 | 각 티켓 Slices(표의 파일 이름 그대로), 노트북 수용은 H3 |
| 14장 티켓·순서·마이그레이션 013~015 | 티켓 지도, Global Constraints |
| 15장 설정(`BODY_TOKEN`, `app_state` 세 열쇠) | SP8-06, SP8-07, SP8-03(`moments_since`, `moments_paused`), SP8-08(`life_seed_history_updated_at`) |
| 16장 되돌림·끄기 | SP8-03(`moments_paused`), SP8-07(README 한 줄), SP8-06(토큰 빼면 404) |
| 17장·부록 A | H4 |
