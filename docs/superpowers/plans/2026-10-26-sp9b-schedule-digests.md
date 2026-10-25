# SP9b 일정 정리 알림 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 일정 정리 알림(`digest`)을 만든다. 아침 알림(`morning`)은 오늘 일정, 밤 알림(`night`)은 내일 일정을 하루 한 번씩 푸시하고, 두 시각과 켜기/끄기를 앱 설정에서 바꾼다.

**Architecture:** 1분 tick에서 `_remind` 바로 다음에 `_digest`가 `loop/digests.py`의 `judge_digests`를 따로 감싸 부르고, `send_digests`를 `reminder_tasks`에 띄운다. 설정과 마지막 슬롯 날짜는 `app_state` 두 키에 둔다(마이그레이션 없음). 쓰기는 체크인 시간처럼 `PUT /settings/digests` → 즉시 갈래 `set_digest_settings` → 활동 `digest_set`(되돌리기 있음) → `refresh_wake`로 잇는다. 깨우기 작업은 `wake_times`가 `daily HH:MM` 줄을 더 내보내고, ps1 세 곳이 그 줄을 받는다. 앱은 설정 칸 하나와 sw 태그 하나를 더하고 BE보다 먼저 배포한다.

**Tech Stack:** Python 3.12, aiohttp, SQLite, pydantic; Next.js 15 정적 PWA, Vitest; PowerShell(작업 스케줄러).

**Spec:** `docs/superpowers/specs/2026-10-26-sp9b-schedule-digests-design.md` (v1.1)

## Global Constraints

- 문구는 스펙 7장 그대로 쓴다. 새 문구는 금지어 시험에 더한다(BE 문구는 `tests/test_digests.py`, 앱 문구는 `copy.ts`라 `copy.test.ts`가 훑는다).
- 로그에 일정 제목을 남기지 않는다.
- 문서와 코드에서 "정리"를 혼자 쓰지 않는다. 기능 이름은 일정 정리 알림, 코드는 `digest`다(정리 루프 `consolidation`과 다르다).
- 앱 첫 로드 180KB 상한을 지킨다(지금 약 172.9KB).
- 텔레그램 UI는 더하지 않는다.
- `npm run gen:types`로 schema.json/types.gen.ts를 만든다. 손으로 고치지 않는다.
- 배포 순서: D2(앱, sw 포함)를 Vercel에 먼저 배포한 뒤 D1a~D1c가 든 BE를 노트북에 올린다(스펙 2.2). 옛 sw는 `type: "digest"`를 `notice` 태그로 보여 다른 안내와 덮어쓰기 때문이다.

## Review Focus

1. 깨우기 실패(배터리, 깨우기 타이머 꺼짐)를 가정한다. 노트북이 21:25 전에 잠들어 21:25에 깨지 못하고 22:40에 깨어남 → 늦게 보냄(70분 < 2시간). 23:40에 깨어남 → 안 보냄(130분 > 2시간).
2. 밤 23:00 설정, 22:50 잠듦, 00:30 깨어남 → d - 1 슬롯으로 늦게 보냄(담는 날 d, `digest_last` = d - 1).
3. 같은 분에 tick이 두 번 돔(재시작 직후) → `digest_last`로 한 번만.
4. 시각을 지금보다 뒤로 바꿈 → 오늘 새 시각에 보냄. 이미 판정한 날 다시 바꿈 → 안 보냄.
5. 일정이 모두 건너뛴 회 → 안 보냄.
6. `digest_settings` JSON이 깨짐 → config 값으로, 예외 없이(러너, API, `wake_times` 세 곳 모두).
7. `digest_set`을 되돌림 → 깨우기 작업이 다시 등록된다(`post_undo`의 `WAKE_KINDS`).

## Interfaces (D1a~D1c 공통)

- `loop/digests.py`
  - `DigestKind = Literal["morning", "night"]`, `DIGEST_KINDS: tuple[DigestKind, ...] = ("morning", "night")`
  - `@dataclass(frozen=True) class DigestSetting: on: bool; time: time`
  - `RANGES: dict[DigestKind, tuple[time, time]] = {"morning": (time(4, 0), time(11, 50)), "night": (time(18, 0), time(23, 50))}`, `STEP_MIN = 10`
  - `DIGEST_LATE_MAX = timedelta(hours=2)`
  - `validate_digest_time(kind: DigestKind, v: Any) -> time | None` (`HH:MM`, 범위 안, 10분 단위)
  - `parse_digest_settings(raw: str | None, defaults: DigestConfig) -> dict[DigestKind, DigestSetting]` (깨진 JSON, 잘못된 칸 → config 값)
  - `digest_text(kind: DigestKind, day: date, occs: list[Occurrence], *, now: datetime, late: bool, tz: str | tzinfo) -> tuple[str, str] | None` (담을 일정이 없으면 None. `{n}` = 담은 개수)
  - `@dataclass(frozen=True) class PendingDigest: kind: DigestKind; date: date; title: str; body: str; url: str; until: datetime` (`date`는 담은 날, `until`은 판정한 `now`의 다음 `day_boundary`, UTC)
  - `judge_digests(*, last_seen_at: datetime, now: datetime, settings: dict[DigestKind, DigestSetting], events: EventsRepo, state: StateRepo, tz: str, day_boundary: time) -> list[PendingDigest]`
  - `async send_digests(pending: list[PendingDigest], delivery: Delivery, *, sleep: Callable[[float], Awaitable[None]] = asyncio.sleep, delays: tuple[float, ...] = RETRY_DELAYS_S) -> None` (지금 시각은 `delivery.clock.now()`, `ttl_s = max(TTL_MIN_S, min(TTL_MAX_S, until - now))`)
- `harness/delivery.py`
  - `digest_payload(kind: str, day: date, title: str, body: str, url: str) -> dict[str, Any]` (`type: "digest"`, `checkin_id: None`, `tag: f"digest:{kind}:{day.isoformat()}"`, `body` 줄바꿈 유지)
  - `Delivery.deliver_digest(self, kind: str, day: date, title: str, body: str, url: str, *, ttl_s: int) -> Channel | None` (텔레그램 대체 `f"{title}\n{body}"`)
- `config.py`: `class DigestConfig(_Model): morning: time = time(7, 30); night: time = time(21, 30); morning_on: bool = True; night_on: bool = True` (범위·10분 단위 검사), `ScheduleConfig.digest: DigestConfig = DigestConfig()`
- `store/repos/state.py`: `DIGEST_SETTINGS_KEY = "digest_settings"`, `DIGEST_LAST_KEY = "digest_last"`
  - `StateRepo.get_digest_settings(defaults: DigestConfig) -> dict[DigestKind, DigestSetting]`
  - `StateRepo.set_digest_settings(settings: dict[DigestKind, DigestSetting]) -> None`
  - `StateRepo.get_digest_last() -> dict[DigestKind, date | None]` (없는 종류는 None)
  - `StateRepo.set_digest_last(kind: DigestKind, d: date) -> None`
- `loop/runner.py`: `Runner._digest(self, last_seen: datetime | None, now: datetime) -> None`
- `tools/digest_settings.py`: `ACTION = "set_digest_settings"`, `KIND = "digest_set"`, `MSG_INVALID`(스펙 7장 오류 문구), `class DigestSettingTools` 의 `apply_digest_settings(self, ctx, kind=None, on=None, time=None) -> dict[str, Any]` (같은 값이면 `{"unchanged": True}`, 아니면 `{"kind", "on", "time", "applies"}`), `_undo_digest_settings`, `register_undo(KIND, _undo_digest_settings)`
- `tools/actions.py`: `"set_digest_settings": ActionSpec("apply_digest_settings", public=False, endpoint="push")`
- `tools/confirmations.py`: `digest_set_line(kind, before: DigestSetting, after: DigestSetting) -> str`, `undo_summary`에 `_DIGEST_SET` 규칙
- `api/models.py`: `DigestSlot { on: bool, time: str }`, `DigestSettings { morning: DigestSlot, night: DigestSlot, wake_updated: bool }`, `DigestSettingPutBody { kind: Literal["morning","night"], on: bool, time: str }`, `DigestSettingsUpdated(DigestSettings) { applies: Literal["today","tomorrow"] | None, activity_id: int | None, undo_id: int | None }`, 오류 코드 `digest_time_invalid`, 스키마 묶음에 넷 모두 등록
- `api/push.py`: `digest_settings_view(conn, deps)`, `get_digest_settings`, `put_digest_settings`
- `api/actions.py`: `WAKE_KINDS = frozenset({CHECKIN_KIND, DIGEST_KIND})`, `_undid_checkin_time` → `_undid_wake_change`
- `wake_times.py`: `DayKind = Literal["weekday", "weekend", "daily"]`, `load_digest_settings(root: Path) -> dict[DigestKind, DigestSetting]`, `wake_times(schedule, overrides=None, today=None, digests=None)`

---

### Task D0: 문서 갱신

**Files:**
- Modify: `GLOSSARY.md`(스케줄 묶음, `놓친 알림` 다음), `docs/adr/0015-schedule-is-not-a-task.md`(덧붙임 한 문단), `docs/superpowers/specs/2026-10-25-sp9-app-tabs-memo-schedule-design.md`(15장 14번, 변경 기록 v2.5)

- [ ] 스펙 9장의 GLOSSARY 항목, ADR 덧붙임, SP9 스펙 두 줄을 그대로 옮긴다
- [ ] `grep -n "일정 정리 알림" GLOSSARY.md docs/adr/0015-schedule-is-not-a-task.md docs/superpowers/specs/2026-10-25-sp9-app-tabs-memo-schedule-design.md` → 세 파일 모두 한 줄 이상 나온다
- [ ] 커밋 `docs(schedule): 일정 정리 알림 용어·ADR 0015 덧붙임 (SP9b-00)`

### Task D1a: 판정, 보내기, 러너

**Files:**
- Create: `src/my_planner/loop/digests.py`, `tests/test_digests.py`
- Modify: `src/my_planner/config.py`(`DigestConfig`, `ScheduleConfig.digest`), `config.toml`(`[schedule.digest]`, 같은 커밋), `src/my_planner/store/repos/state.py`(두 키), `src/my_planner/harness/delivery.py`(`digest_payload`, `deliver_digest`), `src/my_planner/loop/runner.py`(`_digest`), `tests/test_delivery.py`, `tests/test_runner.py`

**Notes:**
- `_digest`는 `tick`에서 `self._remind(last_seen, now)` 바로 다음 줄이다. `if not self.checkins` 조기 반환과 하트비트보다 앞이고, `_remind`와 같이 `self.events is None or last_seen is None`이면 돌아간다. 그래서 `role = "dev"`에서도 돈다.
- 판정 전체를 `try/except Exception`으로 감싸 `log.exception("digest_error")`. `_remind`와 따로 감싼다.
- 보내기 작업은 `self.reminder_tasks`에 넣는다(`drain_reminders`가 함께 기다림). 이벤트 루프 밖이거나 `reminder_delivery`가 없으면 `digests_no_loop` 로그만.
- `send_digests`의 재시도는 `delivery.clock.now() >= until`이면 그만둔다. 취소되면 다시 올린다(적을 행이 없다).

- [ ] 시험을 먼저 쓴다: 스펙 8장 판정·보내기·본문·저장 줄 전부, Review Focus 1~6, `config.toml`을 읽은 `Settings`에 `schedule.digest`가 있는지
- [ ] `pytest -q tests/test_digests.py tests/test_delivery.py tests/test_runner.py` → 새 시험이 실패한다(`ImportError` 또는 `failed`), 이미 있던 시험은 통과
- [ ] 구현한다
- [ ] `pytest -q` → `N passed`, `failed` 0
- [ ] `ruff check src tests` → `All checks passed!`
- [ ] 커밋 `feat(schedule): 일정 정리 알림 판정·보내기 (SP9b-01a)`

### Task D1b: API, 되돌리기, 활동

**Files:**
- Create: `src/my_planner/tools/digest_settings.py`, `tests/test_api_digests.py`
- Modify: `src/my_planner/tools/core.py`(`Tools`가 `DigestSettingTools`를 상속), `src/my_planner/tools/actions.py`(`ActionSpec`), `src/my_planner/tools/confirmations.py`(`digest_set_line`, `undo_summary`), `src/my_planner/api/push.py`(GET/PUT), `src/my_planner/api/server.py`(읽기 경로 `("/settings/digests", get_digest_settings)`, `app.router.add_put(API_PREFIX + "/settings/digests", write_handler(put_digest_settings))`), `src/my_planner/api/actions.py`(`WAKE_KINDS`, `_undid_wake_change`), `src/my_planner/api/models.py`(모델 넷, 오류 코드, 스키마 묶음), `web/app/src/api/schema.json`·`types.gen.ts`, 대시보드 같은 두 파일(재생성)

**Notes:**
- `put_digest_settings`: 본문 검사(400) → `validate_digest_time`(422 `digest_time_invalid`) → `dispatcher.apply_action(_request("set_digest_settings", {"kind", "on", "time"}))`. 결과가 `unchanged`이면 `refresh_wake`를 부르지 않고 `applies`, `activity_id`, `undo_id`를 null로 답한다. 바뀌었으면 `await refresh_wake(deps)` 뒤 `digest_settings_view`에 `applies`, `activity_id`, `undo_id`를 붙여 답한다.
- `apply_digest_settings`는 `self.tasks.transaction()` 안에서 `state.set_digest_settings`와 `record_activity(self.activity, ctx, kind="digest_set", target=f"digest:{kind}", summary=digest_set_line(...), risk="low", undo={"kind": kind, "setting": {"on", "time"}})`를 한다.
- `applies`: 논리적 오늘의 그 종류 슬롯이 아직 판정 전(`digest_last`가 그 슬롯 날짜보다 앞)이고 새 설정의 보낼 시각이 지금보다 뒤면 `today`, 아니면 `tomorrow`. 끄기는 옛 시각으로 같은 규칙을 쓴다.
- `_undo_digest_settings`는 바꾸기 전 값을 다시 적기만 한다(`digest_last`는 그대로).

- [ ] 시험을 먼저 쓴다: 스펙 8장 API 줄 전부(GET 기본값, PUT 한 종류, 422 세 가지, 같은 값은 활동·되돌리기·`refresh_wake` 없음, 활동 한 줄, 되돌리기가 이전 값을 되살리고 `refresh_wake`를 부름, `applies`), 활동·되돌림·오류 문구 금지어 검사(`test_checkin_time_and_conversation_copy_has_no_banned_words`와 같은 모양)
- [ ] `pytest -q tests/test_api_digests.py` → 새 시험이 실패한다
- [ ] 구현하고 `npm run gen:types`(`web/app`, `web/dashboard`)
- [ ] `pytest -q` → `N passed`, `failed` 0
- [ ] `ruff check src tests` → `All checks passed!`
- [ ] `git diff --stat web/app/src/api web/dashboard/src/api` → 재생성한 파일만 바뀌었다
- [ ] 커밋 `feat(schedule): 일정 정리 알림 설정 API·되돌리기 (SP9b-01b)`

### Task D1c: 깨우기 시각과 ps1

**Files:**
- Modify: `src/my_planner/wake_times.py`(`DayKind`, `load_digest_settings`, `wake_times`, 모듈 설명의 줄 모양), `scripts/task_common.ps1`(`$DaysXml`의 `daily`, `Get-WakeTimes` 정규식), `scripts/check_tasks.ps1`(`$DaysMask`의 `daily = 127`), `tests/test_wake_times.py`, `tests/test_task_templates.py`

**Notes:**
- `load_digest_settings(root)`는 `load_overrides`처럼 `state/planner.db`를 `mode=ro`로 열어 `digest_settings` 한 줄을 읽고 `parse_digest_settings(raw, load_schedule(root).digest)`를 돌려준다. DB가 없거나 `sqlite3.Error`면 config 값이다. 두 로더가 함께 쓰는 `_read_state_value(root, key) -> str | None`으로 묶어도 된다.
- `wake_lines`는 `wake_times(load_schedule(root), load_overrides(root), _today(root), load_digest_settings(root))`. 출력 순서는 `weekday`, `weekend`, `daily`이고 겹침은 같은 `(종류, 시각)`만 하나로 둔다.

- [ ] 시험을 먼저 쓴다: 스펙 8장 wake_times·스크립트 줄 전부(켜진 시각이 `daily` 줄, 꺼지면 빠짐, `daily`와 `weekday`의 같은 시각은 둘 다, DB JSON 깨짐 → config, ps1 텍스트에 `daily`가 세 곳)
- [ ] `pytest -q tests/test_wake_times.py tests/test_task_templates.py` → 새 시험이 실패한다
- [ ] 구현한다
- [ ] `pytest -q` → `N passed`, `failed` 0
- [ ] `ruff check src tests` → `All checks passed!`
- [ ] 커밋 `feat(schedule): 일정 정리 알림 깨우기 시각 (SP9b-01c)`

### Task D2: 앱 설정 칸과 sw

**Files:**
- Create: `web/app/src/screens/DigestSettings.tsx`, `web/app/src/test/fixtures/digest-settings.json`
- Modify: `web/app/src/screens/Settings.tsx`(`<CheckinTimes>` 아래), `web/app/src/lib/copy.ts`(`copy.digests`), `web/app/src/screens/Settings.test.tsx`, `web/app/src/api/fixtures.test.ts`(`["digest-settings.json", "DigestSettings"]`), `web/app/public/sw.js`(`type === "digest"`이면 payload `tag`), `web/app/public/sw.test.ts`

**Interfaces:**
- Consumes: D1b의 `GET/PUT /settings/digests`, 모델 `DigestSettings`, `DigestSettingsUpdated`
- `copy.digests = { heading: "일정 정리 알림", morning: "아침에 오늘 일정", night: "밤에 내일 일정", note: "일정이 있는 날만 보내요.", fromToday: "오늘부터 적용돼요", fromTomorrow: "내일부터 적용돼요", wakeStale: copy.checkinTimes.wakeStale와 같은 문장 }`
- `digestOptions(kind)`: `CheckinTimes.checkinOptions`처럼 10분 단위(아침 04:00~11:50, 밤 18:00~23:50)
- 스위치는 새 부품 없이 `<input type="checkbox" role="switch">`로 둔다. 끄면 `<select>`가 `disabled`이고 흐리다
- `CheckinTimes`의 저장 잠금(`lock`), 토스트 되돌리기(`undoId`), `toast.onUndone` 뒤 다시 읽기, `wake_updated` 안내 줄을 그대로 따른다. `applies`가 null이면 토스트를 띄우지 않는다
- GET이 404면 칸을 그리지 않는다(앱을 먼저 배포한 사이)

- [ ] 시험을 먼저 쓴다: 렌더, 스위치 PUT, 시간 바꾸기 PUT, 토스트와 되돌리기, 끄면 시간 흐림, `wake_updated: false` 안내, 404면 칸 없음, `일정이 있는 날만 보내요.`, sw의 `digest` 태그와 `tag` 없을 때 `notice`
- [ ] `npm run test` → `Tests  N passed`, 실패 0
- [ ] `npm run typecheck` → 출력 없이 끝남(종료 코드 0)
- [ ] `npm run lint:copy` → 한글 리터럴 보고 0건(종료 코드 0)
- [ ] `npm run build` → 성공(종료 코드 0)
- [ ] `npm run size` → 첫 로드 180KB 이하
- [ ] `npm run check:csp` → 통과(종료 코드 0)
- [ ] 커밋 `feat(app): 일정 정리 알림 설정·sw 태그 (SP9b-02)`

### Task D3: 노트북 확인 (Dahun과 함께, SP9-11에 붙임)

순서: D2 앱 배포 → BE 올림 → 아래 확인.

- [ ] `update_wake_task.ps1 -DryRun`의 트리거 수가 켜진 종류 수(기본 2)만큼 늘었다
- [ ] `check_tasks.ps1` → `OK   all checks passed`
- [ ] 21:25에 깨어나 21:30에 밤 알림이 온다
- [ ] 잠든 상태에서 07:25에 깨어나 07:30에 아침 알림이 정시로 온다. 로그 `digest_judged`의 `outcome`이 `sent`다. `late`면 실패이고, 후속으로 `DIGEST_WAKE_LEAD`를 1분으로 줄인다(스펙 3.2)
- [ ] 폰에서 일정 정리 알림이 다른 안내 알림(`notice`)을 덮어쓰지 않는다
