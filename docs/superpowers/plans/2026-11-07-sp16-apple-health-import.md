# SP16 애플 건강앱 이력 가져오기 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 건강앱 내보내기 파일(export.zip)의 운동을 노트북 CLI로 `health_workouts`에 가져와, 운동메이트·운동 화면·보너스가 함께 보게 한다.

**Architecture:** 새 패키지 `my_planner/health/`(종류 매핑, XML 스트리밍 파서, 가져오기)와 저장소 `store/repos/health.py`. 쓰는 곳은 BE를 멈춘 채 잠금을 잡는 CLI 하나(`standing import`와 같은 틀). 읽는 쪽(메이트 앞머리, `list_workouts`, `GET /workout`, 운동한 날)은 기존 코드에 건강앱 운동을 더한다. 노트북 스크립트가 작업 끄기 → 가져오기 → 켜기를 감싼다.

**Tech Stack:** Python 3.12, SQLite, `xml.etree.ElementTree.iterparse`, `zipfile`, aiohttp, pytest; Next.js 앱(vitest); PowerShell.

**Spec:** `docs/superpowers/specs/2026-11-07-sp16-apple-health-design.md` (v0.5). ADR 0023.

## Global Constraints

- 마이그레이션 번호 `025_health_import.sql`. 표·칸 이름과 CHECK는 스펙 6.1 그대로.
- 같은 운동: 같은 `activity`, `start_at` ±60초, `minutes` ±1(스펙 6.2). `minutes` = 초 ÷ 60 **버림**, 1 미만이면 건너뜀.
- 경로(`WorkoutRoute`), `Record`, 심박 시계열, 기기·앱 이름(`sourceName`, `device`), 메타데이터 원문은 저장하지 않는다. 로그에는 개수만(`health_import_done`).
- CLI 종료 코드: 0 끝남, 3 잠금 못 잡음, 6 못 읽음·형식 아님. 5는 쓰지 않는다.
- 다시 가져올 때 쓰기 범위: 처음이면 전부, 아니면 `last_workout_date − 14일`부터(`--since`가 이긴다). `exported_on`, `last_workout_date`는 늦은 쪽만 남긴다.
- X13: `source_kind='workout_log'`, `source_ref=workout_day_ref(date)`, `amount=XP_WORKOUT_LOG`, `label=LABEL_WORKOUT_LOG`, `area='health'`, `logical_date=date`. 가져온 순간의 논리적 날짜 기준 `date >= 오늘 − 6`이고 숨기지 않은 운동만.
- `list_workouts` `days` 최대 730. `health_workouts` 최대 60개.
- 금지어(SP12 9.4) 검사가 새 `mate.md` 줄과 새 고정 문구에도 돈다. 연속·빠진 날 수·비율 문구 없음.
- 앱 첫 로드 180KB 상한(`npm run size`). 새 화면·새 비동기 CSS 조각 없음.
- 고정 문구는 스펙 부록 A 그대로.

## Review Focus

1. 한국어 아이폰 내보내기(`apple_health_export/내보내기.xml`, `내보내기_cda.xml` 함께 있음): `_cda`가 아닌 본 파일을 골라야 한다 → Task 2 `test_picks_korean_member_not_cda`.
2. 수백 MB~GB 파일: 메모리가 늘지 않아야 한다(요소 `clear()`, 뿌리 자식 정리) → Task 2 `test_streaming_memory_bounded`(slow).
3. 날짜 경계: `2026-11-07 03:30:00 +0900`에 시작한 운동은 논리적 날짜 11-06이다(04:00 경계) → Task 2 `test_logical_date_before_boundary`.
4. 숨긴 운동을 다시 가져와도 숨김 그대로, 옛 zip을 골라도 "어디까지"가 뒤로 가지 않음 → Task 1 `test_upsert_keeps_hidden`, Task 3 `test_old_file_does_not_move_dates_back`.
5. 가져오기 도중 실패(형식 오류 파일, Ctrl+C): BE 작업이 꺼진 채 남지 않아야 한다 → Task 7 정적 검사 `test_enable_in_finally`.

---

### Task 1: 마이그레이션, 종류 매핑, 저장소

**Files:**
- Create: `src/my_planner/store/migrations/025_health_import.sql`
- Create: `src/my_planner/health/__init__.py`, `src/my_planner/health/activities.py`
- Create: `src/my_planner/store/repos/health.py`
- Modify: `tests/test_migrations.py:301,671,855,895,905`, `tests/test_photos_store.py:94,137`(최신 버전 24 → 25)
- Test: `tests/test_health_workouts_repo.py`, `tests/test_health_activities.py`

**Interfaces:**
- Produces:
  - `activities.ACTIVITY_MAP_VERSION: int = 1`, `activities.normalize(raw: str) -> str`(키, 모르면 `"other"`), `activities.label(key: str) -> str`(한국어, 모르면 "기타 운동"). 매핑은 스펙 부록 B. `raw`는 `HKWorkoutActivityType…` 이름과 영어 이름 둘 다 받는다.
  - `@dataclass(frozen=True) HealthWorkoutIn(activity_raw: str, start_at: datetime, end_at: datetime, minutes: int, energy_kcal: int | None, distance_km: float | None, hr_avg: int | None, hr_max: int | None, indoor: bool | None)`
  - `@dataclass(frozen=True) HealthWorkout(id: int, activity: str, date: date, start_at: datetime, minutes: int, energy_kcal: int | None, distance_km: float | None, hr_avg: int | None, hr_max: int | None, hidden: bool)`
  - `@dataclass(frozen=True) HealthSync(last_import_at: datetime | None, exported_on: date | None, last_workout_date: date | None, activity_map_version: int)`
  - `class HealthRepo(conn, clock)`: `find_same(w: HealthWorkoutIn, *, tz, boundary) -> HealthWorkout | None`(읽기만, 스펙 6.2 찾기), `upsert(w: HealthWorkoutIn, *, tz, boundary, now) -> tuple[int, bool]`(id, 새로 만듦 여부. 찾기는 `find_same`), `between(since: date, until: date, *, include_hidden=False, limit: int | None = None) -> list[HealthWorkout]`(날짜·시작 내림차순), `count_between(since, until) -> int`(숨김 제외), `get(id) -> HealthWorkout | None`, `hide(id, now) -> bool`, `unhide(id) -> bool`, `sync() -> HealthSync`, `record_import(*, now, exported_on: date | None, last_workout_date: date | None)`(늦은 쪽만), `reclassify_if_needed() -> int`(바뀐 줄 수, 버전 맞춤).
  - 모듈 함수 `exercise_days(conn, since: date, until: date) -> set[date]`: 지우지 않은 `workout_logs.date` ∪ 숨기지 않은 `health_workouts.date`.

- [ ] **Step 1: 실패하는 테스트 쓰기** — `tests/test_health_workouts_repo.py`
  - `test_find_same_read_only`: `find_same`은 줄 수를 바꾸지 않고, 퍼지 일치 줄을 돌려준다.
  - `test_upsert_new_then_same`: 같은 `HealthWorkoutIn`을 두 번 → 두 번째 `(id, False)`, 줄 1개.
  - `test_upsert_fuzzy_match`: 시작 09:12:59/45분과 09:13:00/46분 → 한 줄. 시작 09:12/45분과 09:12/47분 → 두 줄. 종류 다르면 두 줄.
  - `test_upsert_fills_empty_only_and_overwrites_given`: 처음 `hr_avg=None`, 다시 `hr_avg=128` → 128. 다시 `energy_kcal=None`이면 기존 값 유지.
  - `test_upsert_keeps_hidden`: 숨긴 뒤 같은 운동 upsert → `hidden is True`, `between`에 없음.
  - `test_date_is_logical`: `start_at` = 2026-11-06 18:30Z(11-07 03:30 KST) → `date == date(2026,11,6)`.
  - `test_record_import_keeps_later`: `exported_on` 11-09 뒤 11-02로 기록 → 11-09 그대로.
  - `test_exercise_days_union`: 운동 기록 11-03, 건강앱 11-03·11-05, 숨긴 건강앱 11-06 → `{11-03, 11-05}`.
  - `test_reclassify`: `activity_raw="HKWorkoutActivityTypeBoxing"`(v1에서 other) 줄이 있을 때, 테스트에서 매핑에 `boxing`을 더하고 버전을 2로 패치 → `reclassify_if_needed() == 1`, `activity == "boxing"`, 두 번째 호출은 0.
  - `tests/test_health_activities.py`: `normalize("HKWorkoutActivityTypeTraditionalStrengthTraining") == "strength"`, `normalize("Traditional Strength Training") == "strength"`, `normalize("HKWorkoutActivityTypeStairs") == "stairs"`, `normalize("Quidditch") == "other"`, `label("strength") == "근력 운동"`.
- [ ] **Step 2: 실행해 실패 확인** — `python -m pytest tests/test_health_workouts_repo.py tests/test_health_activities.py -q` → `ModuleNotFoundError`.
- [ ] **Step 3: 구현** — 날짜는 모듈 함수 `my_planner.clock.logical_date(dt, tz, boundary)`. 마이그레이션은 스펙 6.1 SQL 그대로(`health_sync`에 `exported_on`, `last_workout_date`, `activity_map_version` 포함, 한 줄 INSERT). `upsert`의 찾기는 `SELECT … WHERE activity=? AND start_at BETWEEN ? AND ? AND abs(minutes-?)<=1 ORDER BY abs(julianday(start_at)-julianday(?)) LIMIT 1`. 시각 저장은 `to_iso`.
- [ ] **Step 4: 통과 확인** — 같은 명령 → 모두 PASS. `python -m pytest tests/test_migrations.py tests/test_photos_store.py -q` → PASS(최신 버전 25).
- [ ] **Step 5: 커밋** — `feat(sp16): health_workouts 표, 종류 매핑, HealthRepo`

### Task 2: export.xml 스트리밍 파서

**Files:**
- Create: `src/my_planner/health/export_xml.py`
- Create: `tests/fixtures/health/export_ko.zip`(테스트가 만들어도 됨), `tests/fixtures/health/export_small.xml`
- Modify: `pyproject.toml`(`[tool.pytest.ini_options] markers`에 `slow`), `.github/workflows/ci.yml`의 두 `pytest -q`를 `pytest -q -m "not slow"`로(큰 파일 시험은 로컬·노트북에서 손으로)
- Test: `tests/test_health_export_xml.py`

**Interfaces:**
- Consumes: `HealthWorkoutIn` (Task 1).
- Produces:
  - `class NotHealthExport(Exception)`, `class UnreadableFile(Exception)`
  - `@dataclass ParsedExport(exported_at: datetime | None, workouts: Iterator[HealthWorkoutIn], skipped: Callable[[], int])` — `workouts`는 한 번만 도는 생성기, `skipped()`는 다 돈 뒤의 건너뛴 수.
  - `open_export(path: Path, *, now: datetime) -> ContextManager[ParsedExport]`: `.zip`이면 항목을 고르고(스펙 8.2: 이름이 `export.xml`·`내보내기.xml`로 끝나고 `_cda` 없음), `.xml`이면 그대로. 뿌리가 `HealthData`가 아니면 `NotHealthExport`, 열 수 없으면 `UnreadableFile`.

- [ ] **Step 1: 실패하는 테스트 쓰기** — 고정 XML에는 새 형식(`WorkoutStatistics`)과 옛 형식(`totalEnergyBurned`/`totalDistance`) 운동 하나씩, `Record` 3개, `WorkoutRoute` 하나, `<ExportDate value="2026-11-09 08:00:00 +0900"/>`, 미래 운동 하나, 0분 운동 하나, 범위 밖 운동 하나(평균 심박 300). 이 파일은 Task 2 전용이다.
  - `test_parses_new_and_old_format`: 운동 2개. 새 형식 = `activity_raw` 근력, `minutes=45`(2730초 → 45), `energy_kcal=320`, `hr_avg=128`, `hr_max=161`, `indoor=True`. 옛 형식 = 달리기, `distance_km≈5.0`(`3.107 mi` 변환).
  - `test_units`: `kJ` 1339 → 320 kcal, `m` 5000 → 5.0 km, `durationUnit="hr"` 0.75 → 45분.
  - `test_skips_future_zero_and_out_of_range`: `skipped() == 3`.
  - `test_exported_at`: `exported_at == 2026-11-08T23:00Z`.
  - `test_no_route_or_source_kept`: `HealthWorkoutIn` 필드에 경로·`sourceName` 없음(데이터클래스 필드 이름 목록 비교).
  - `test_picks_korean_member_not_cda`: zip 안 `apple_health_export/내보내기.xml`과 `apple_health_export/내보내기_cda.xml`(뿌리 `ClinicalDocument`) → 본 파일을 읽음.
  - `test_not_health_export`: 뿌리 `<foo/>` → `NotHealthExport`. zip에 맞는 항목 없음 → `NotHealthExport`. 깨진 zip → `UnreadableFile`.
  - `@pytest.mark.slow test_streaming_memory_bounded`: `Record` 수십만 줄로 50MB XML을 스트리밍으로 써서 만들고, `tracemalloc` 최고치 < 200MB.
- [ ] **Step 2: 실행해 실패 확인** — `python -m pytest tests/test_health_export_xml.py -q` → `ModuleNotFoundError`.
- [ ] **Step 3: 구현** — `iterparse(events=("start","end"))`. `Workout` end에서 자식(`WorkoutStatistics`, `MetadataEntry key="HKIndoorWorkout"`)을 읽고 `elem.clear()`. 뿌리 자식은 `Record`·`Workout` end마다 `root.clear()`로 비운다. 날짜 형식 `%Y-%m-%d %H:%M:%S %z`. 거리 통계는 `HKQuantityTypeIdentifierDistance` 로 시작하는 type 아무거나. `hr_max < hr_avg`면 둘 다 `None`.
- [ ] **Step 4: 통과 확인** — `python -m pytest tests/test_health_export_xml.py -q -m "not slow"` → PASS, `-m slow` → PASS.
- [ ] **Step 5: 커밋** — `feat(sp16): 건강앱 내보내기 XML 스트리밍 파서`

### Task 3: `health import` CLI

**Files:**
- Create: `src/my_planner/health/importer.py`
- Modify: `src/my_planner/cli.py`(`health import` 분기, USAGE 한 줄)
- Test: `tests/test_health_import.py`

**Interfaces:**
- Consumes: `open_export`, `NotHealthExport`, `UnreadableFile` (Task 2); `HealthRepo`, `exercise_days` (Task 1); `StatusRepo.grant`, `workout_day_ref`, `XP_WORKOUT_LOG`, `LABEL_WORKOUT_LOG`.
- Produces: `run_import(root: Path | str, file: Path | str, *, dry_run: bool, since: date | None, out: TextIO | None = None, lock_factory=SingleInstanceLock, clock: Clock | None = None) -> int`. 상수 `EXIT_OK=0`, `EXIT_RUNNING=3`, `EXIT_BAD_FILE=6`. 문구는 스펙 부록 A "CLI 출력/오류".

- [ ] **Step 1: 실패하는 테스트 쓰기** (가짜 시계 2026-11-09 12:00 KST, `standing import` 테스트의 잠금 가짜를 따라 씀. 고정 파일은 테스트 안에서 만든다: 기본 파일 = 운동 11-07·11-03 둘과 건너뛸 운동 둘(미래, 0분), `ExportDate` 2026-11-09 08:00 +0900. 다른 테스트는 필요한 운동만 담은 작은 파일을 따로 만든다)
  - `test_first_import_all`: 출력 `운동 2개 가져옴, 0개 이미 있음, 2개 건너뜀 · 마지막 운동 11-07`, 코드 0, `sync().exported_on == 11-09`(논리적 날짜), `last_workout_date == 11-07`.
  - `test_second_import_same_file`: `운동 0개 가져옴, 2개 이미 있음, …`.
  - `test_default_range_after_first`: 첫 가져오기 뒤 `last_workout_date`가 11-07일 때 10-20 운동이 든 새 파일 → 10-24 이전은 쓰지 않음(개수에 안 셈). `--since 2026-10-01`이면 씀.
  - `test_old_file_does_not_move_dates_back`: 11-09 파일 뒤 11-02 파일 → `exported_on` 11-09 그대로.
  - `test_xp_only_within_7_days`: 운동 11-03(오늘−6)과 11-02(오늘−7) → 원장에 `workout_day:2026-11-03`만, 숨긴 운동은 없음, 같은 날 운동 기록 X13이 이미 있으면 그대로 하나.
  - `test_dry_run_writes_nothing_and_no_db`: DB 없는 루트에서 `--dry-run` → 코드 0, DB 파일 없음. `migrate(upto=24)`로 만든 025 이전 DB → 코드 0, 모두 "가져옴"으로 셈. 있는 DB에서 → 줄 수 그대로, 이미 있는 운동은 "이미 있음"으로 셈.
  - `test_running_exit_3`: 잠금 가짜가 `AlreadyRunning` → 코드 3, 문구 "BE가 돌고 있어요. 멈춘 뒤 다시 해 주세요."
  - `test_bad_file_exit_6`: 뿌리 `<foo/>` 파일, 없는 파일 → 코드 6.
  - `test_reclassify_before_write`: 매핑 버전을 올린 상태에서 가져오면 기존 `other` 줄이 먼저 바뀌어 같은 운동을 찾음(새 줄 없음).
  - `test_log_counts_only`: `caplog`의 `health_import_done` 레코드의 `extra` 키가 `imported`, `existing`, `skipped`, `xp` 넷뿐이고 운동 종류·날짜 값이 없음.
  - `test_bad_since_usage`: `cli.main(["health","import",str(f),"--since","2026/10/01"])` → 2.
  - `test_cli_dispatch`: `cli.main(["health","import",str(f),"--dry-run"])` → 0.
- [ ] **Step 2: 실행해 실패 확인** — `python -m pytest tests/test_health_import.py -q` → 실패.
- [ ] **Step 3: 구현** — `standing/importer.run_import`의 틀(잠금 → 파일 → dry-run이면 `open_ro`, 아니면 `open_db`+`migrate`)을 따른다. dry-run은 `HealthRepo.find_same`으로 "이미 있음"을 세고, DB가 없거나 025 이전이라 `sqlite3.Error`가 나면 모두 새 운동으로 센다(`standing/importer.py:137-142`와 같은 갈래). `--since` 파싱과 형식 오류(USAGE, 코드 2 `EXIT_USAGE`)는 `cli.py`의 `health import` 분기에서 한다. `run_import`는 `date | None`만 받는다. 쓰기는 1,000개마다 `transaction`. X13은 같은 트랜잭션에서 `StatusRepo.grant`(`gain=None`). 오늘 = `logical_date(now, TZ, BOUNDARY)`.
- [ ] **Step 4: 통과 확인** — 같은 명령 → PASS.
- [ ] **Step 5: 커밋** — `feat(sp16): health import CLI`

### Task 4: 운동한 날을 한 곳으로

**Files:**
- Modify: `src/my_planner/store/repos/status.py:90-128`(`activity_rows`의 운동 날 쿼리 → `exercise_days`, docstring)
- Modify: `src/my_planner/panel/pace.py:221`(`WorkoutRepo.log_days` → `exercise_days`, 습관 체크 합침은 그대로)
- Modify: `src/my_planner/standing/service.py:47-53`(`with_derived`: `exercise_days`로 56일 확인과 28일 셈)
- Modify: `docs/superpowers/specs/2026-11-01-sp13-objective-standing-design.md` 변경 기록 한 줄(`exercise_days_week`에 건강앱 운동 셈, SP16 10장)
- Test: `tests/test_status_activity.py`, `tests/test_panel_pace.py`, `tests/test_standing_drift.py`

**Interfaces:**
- Consumes: `exercise_days(conn, since, until)` (Task 1).
- Produces: 동작만 바뀜(시그니처 그대로). `with_derived(values, workout, today)`는 `workout.conn`으로 `exercise_days`를 부른다.

- [ ] **Step 1: 실패하는 테스트 쓰기**
  - `test_status_activity.py::test_health_workout_day_counts_once`: 건강앱 운동만 있는 날 건강 0.5, 운동 기록 + 건강앱 같은 날 0.5, `workout_days` 개수에 합친 날.
  - `test_panel_pace.py::test_pace_counts_health_workouts`: 건강앱 운동 4일 + 건강 습관 체크 다른 2일 → 운동한 날 6일 기준 주 평균.
  - `test_standing_drift.py::test_exercise_days_week_from_health`: 운동 기록 없이 건강앱 운동 28일 중 8일 → `exercise_days_week == 2.0`.
- [ ] **Step 2: 실패 확인** — `python -m pytest tests/test_status_activity.py tests/test_panel_pace.py tests/test_standing_drift.py -q` → 새 테스트 3개 FAIL.
- [ ] **Step 3: 구현** — 세 곳의 질의를 `exercise_days`로 바꾼다.
- [ ] **Step 4: 통과 확인** — 같은 명령 → 모두 PASS(기존 테스트 포함).
- [ ] **Step 5: 커밋** — `feat(sp16): 운동한 날에 건강앱 운동 합침`

### Task 5: 운동메이트 연결

**Files:**
- Modify: `src/my_planner/harness/mate_context.py`(`## 최근 기록` 첫 줄, 두 표 합치기, `_health_line`)
- Modify: `src/my_planner/tools/workout.py`(`list_workouts`, `LIST_DAYS_MAX=730`, `MSG_DAYS`, docstring, `LIST_HEALTH_MAX=60`)
- Modify: `src/my_planner/tools/mcp_adapter.py:843-852`(설명, `maximum: 730`)
- Modify: `src/my_planner/harness/prompts/mate.md`(스펙 9.3 줄, #244 줄 고침)
- Modify: `src/my_planner/tools/core.py:239-260`(`Tools.__init__`의 `health` 인자), `src/my_planner/harness/dispatcher.py:_mate_preamble`, `src/my_planner/tools/workout.py:339 get_mate_context`(둘 다 `health=`를 넘김), `src/my_planner/app.py`(`HealthRepo(conn, clock)`를 `Tools`에 넘김)
- Modify: `docs/superpowers/specs/2026-10-31-sp12-workout-mate-design.md` 변경 기록(10장 운동한 날, `days` 최대 730, 앞머리 건강앱 줄)
- Test: `tests/test_tools_workout.py`, `tests/test_mate_prompts.py`, `tests/test_mate_context.py`(새로 만든다)

**Interfaces:**
- Consumes: `HealthRepo.between`, `count_between`, `sync`, `activities.label` (Task 1).
- Produces: `build_mate_preamble(..., health: HealthRepo | None = None)`; `Tools.health: HealthRepo | None`(`tools/core.py` `Tools.__init__`에 `health: HealthRepo | None = None` 인자, `WorkoutTools` 믹스인에 `health` 선언); `list_workouts` 결과 키 `logs`, `traces`, `health_workouts`, `health_imported_through`, (넘칠 때) `health_truncated`, `health_total`. `health_workout_dict(w: HealthWorkout) -> dict` = 스펙 9.2 키들.

- [ ] **Step 1: 실패하는 테스트 쓰기**
  - `test_preamble_merges_health`: 운동 기록 11-05, 건강앱 11-07(근력 45분 320kcal 심박 128) → `## 최근 기록` 다음 줄이 `건강앱: 11-09까지 가져옴`, 그다음 `- 11-07 (토) 건강앱 · 근력 운동 45분 · 320kcal · 평균 심박 128 (h#1)`, 그다음 운동 기록 줄. 거리 0은 안 나옴.
  - `test_preamble_never_imported`: `건강앱: 아직 가져온 적 없음`.
  - `test_get_mate_context_includes_health`: `get_mate_context` 결과 `text`에도 건강앱 줄이 있다(가짜 시계 2026-11-09 12:00 KST, 모든 메이트 테스트에서 같은 시계).
  - `test_preamble_cap_8_combined`: 두 표 합쳐 10개 → 8줄.
  - `test_list_workouts_health`: `days=730` 허용, `731` → `MSG_DAYS`, 61개면 60개 + `health_truncated: True`, `health_total: 61`, 숨긴 운동 없음, `name="근력"`이 `activity_label`에 걸림, `health_imported_through == "2026-11-09"`.
  - `test_mcp_schema_max_730`: `mcp_adapter` 도구 스키마 `days.maximum == 730`, 설명에 "730"과 "건강앱".
  - `test_mate_prompts.py`: 금지어 검사 통과, `mate.md`에 "건강앱" 줄이 있고 "둘 다 없을 때만"이 "모두 없을 때만"으로 바뀜.
- [ ] **Step 2: 실패 확인** — `python -m pytest tests/test_tools_workout.py tests/test_mate_prompts.py tests/test_mate_context.py -q` → 새 테스트 FAIL.
- [ ] **Step 3: 구현** — 줄 형식·문구는 스펙 9.1·9.3·부록 A. 앞머리 날짜 표기 `MM-DD`.
- [ ] **Step 4: 통과 확인** — 같은 명령 → PASS.
- [ ] **Step 5: 커밋** — `feat(sp16): 운동메이트가 건강앱 운동을 읽음`

### Task 6: API와 앱 운동 화면

**Files:**
- Modify: `src/my_planner/api/workout.py`, `src/my_planner/api/models.py:1673`(`Workout`에 `health_workouts: list[HealthWorkoutOut]`, `health_imported_through: str | None`; 새 `HealthWorkoutOut`)
- Modify: `src/my_planner/api/health.py:155`(`features`에 `"apple_health"`), `tests/test_api_health.py:314`(목록 전체 비교에 `"apple_health"` 추가)
- Modify: `src/my_planner/tools/actions.py:717` 부근(`"hide_health_workout": ActionSpec(...)`), `src/my_planner/tools/workout.py`(`hide_health_workout` 도구 메서드 + `_undo_health_workout_hidden`, `drop_body_note`·`_undo_body_note_dropped`와 같은 틀), `src/my_planner/tools/confirmations.py`(`WORKOUT_KINDS`에 `health_workout_hidden`, 확인 문구 "✓ 건강앱 운동 숨김")
- Modify: `docs/superpowers/specs/2026-10-24-sp3-4-life-curve-dashboard-design.md` 6장(`GET /workout` 새 필드, `/actions` `hide_health_workout`)과 변경 기록
- Modify: `web/app/src/api/types.gen.ts`(`python -m my_planner schema`로 다시 만듦), `web/app/src/screens/Workout.tsx`, `Workout.module.css`, `web/app/src/lib/copy.ts`
- Test: `tests/test_api_workout.py`, `tests/test_api_actions.py`, `web/app/src/screens/Workout.test.tsx`

**Interfaces:**
- Consumes: `HealthRepo.between/hide/unhide/sync`, `health_workout_dict` (Task 1, 5).
- Produces: `GET /workout` 새 필드, `/actions` `hide_health_workout {id}` → 활동 `health_workout_hidden`(대상 `health_workout:<id>`), 되돌리기는 `POST /activity/{id}/undo`. 대상 함수 `_health_workout_target`은 `actions.py:281 _body_note_target`을 본뜬다. 되돌리기 함수는 `workout.py`의 되돌리기 등록 루프(644행 부근)에 넣고, `unhide`가 False면 `SUPERSEDED`. 이 동작은 두뇌 도구가 아니다(`MATE_TOOLS`·`APP_ONLY_TOOLS`에 넣지 않음). `HealthWorkoutOut`을 `models.MODELS`에 등록.

- [ ] **Step 1: 실패하는 테스트 쓰기**
  - `test_api_workout.py::test_health_fields`: 28일 안 건강앱 2개(하나 숨김) → `health_workouts` 1개, `health_imported_through` 날짜. 가져온 적 없으면 `[]`와 `null`.
  - `test_api_actions.py::test_hide_health_workout_and_undo`: 숨기기 → 200·활동 생김 → `/activity/{id}/undo` → 다시 보임. 숨기기 전후 경험치 원장 합계 같음. 없는 id → 오류 문구.
  - `test_api_health.py`(있는 파일)에 `"apple_health" in features`.
  - `Workout.test.tsx`: 건강앱 줄에 태그 "건강앱"과 `45분 · 320kcal · 평균 심박 128`, 보조 글 "건강앱 11/9까지", 숨기기 → 알림 줄, `features`에 없으면 건강앱 줄·보조 글 없음.
- [ ] **Step 2: 실패 확인** — `python -m pytest tests/test_api_workout.py tests/test_api_actions.py tests/test_api_health.py -q`; `cd web/app && npm test -- Workout` → 새 테스트 FAIL.
- [ ] **Step 3: 구현** — 앱은 기존 기록 줄 컴포넌트에 변형을 더하고 새 CSS 파일을 만들지 않는다.
- [ ] **Step 4: 통과 확인** — 위 명령 → PASS; `cd web/app && npm run build && npm run size` → 180KB 안; `python -m pytest tests/test_api_schema.py -q` PASS.
- [ ] **Step 5: 커밋** — `feat(sp16): 운동 화면에 건강앱 운동, 숨기기`

### Task 7: 노트북 스크립트, README, 체크리스트

**Files:**
- Create: `scripts/health_import.ps1`
- Modify: `scripts/task_common.ps1`(`Stop-MedicProcesses -Root <경로>`로 인자를 받게 해서 `register_task.ps1`에서 옮김), `scripts/register_task.ps1`(`Stop-MedicProcesses -Root $Root`로 부름), `tests/test_task_templates.py:140`(PSScriptRoot 검사 목록에 `health_import.ps1`)
- Modify: `README.md`("애플 건강앱" 절: 내보내기 → 노트북 `data\import\` → 스크립트, 얼마나 자주, iCloud 사본 지우기)
- Create: `docs/sp16/laptop-checklist.md`
- Test: `tests/test_health_import_script.py`

**Interfaces:**
- Consumes: `python -m my_planner health import <파일>`와 종료 코드 (Task 3).
- Produces: `scripts\health_import.ps1 [-TaskName my-planner] [-MedicTaskName my-planner-medic] [-DryRun]`.

- [ ] **Step 1: 실패하는 테스트 쓰기** — `tests/test_task_templates.py`처럼 본문을 읽어 검사:
  - `test_params`: `-TaskName`, `-MedicTaskName` 기본값 `my-planner`, `my-planner-medic`, `-DryRun` 스위치.
  - `test_disable_before_import`: 두 작업 `Disable-ScheduledTask`·`Stop-ScheduledTask`와 `Stop-MedicProcesses`가 `health import` 줄보다 앞.
  - `test_enable_in_finally`: `finally` 블록 안에 두 작업 `Enable-ScheduledTask`·`Start-ScheduledTask`.
  - `test_retry_on_exit_3`: 종료 코드 3 비교와 6번 재시도.
  - `test_no_zip_no_task_change`: zip이 없을 때의 `return`이 `Disable-ScheduledTask`보다 앞.
  - `test_register_task_uses_common`: `register_task.ps1`에 `function Stop-MedicProcesses` 정의가 없고, `task_common.ps1`의 정의는 `param(` 안에 `$Root`를 받는다. 두 스크립트 모두 `Stop-MedicProcesses -Root`로 부른다.
  - `test_utf8_bom`: `health_import.ps1`, `task_common.ps1`이 `ef bb bf`로 시작(Windows PowerShell 5.1이 한국어를 CP949로 잘못 읽지 않게).
  - `test_picks_any_zip`: zip 고르기가 `data\import\*.zip` 중 가장 최근(`LastWriteTime`)이다(한국어 아이폰은 `내보내기.zip`일 수 있다).
  - `test_delete_prompt_not_on_dry_run`: 지우기 물음이 `-DryRun`이 아닐 때만.
- [ ] **Step 2: 실패 확인** — `python -m pytest tests/test_health_import_script.py -q` → FAIL.
- [ ] **Step 3: 구현** — 순서는 스펙 8.3. 끝 물음 문구는 부록 A. BOM 붙인 UTF-8로 저장한다. python 출력은 변수로 받지 않고 그대로 콘솔에 보인다(한국어가 깨지지 않게, 종료 코드는 `$LASTEXITCODE`). README와 체크리스트(S0 `workout_logs` 개수, S2 실제 zip 이름 확인과 `-DryRun` 시간·운동 종류 목록, 실제 가져오기, 메이트 질문 2개)를 쓴다.
- [ ] **Step 4: 통과 확인** — `python -m pytest tests/test_health_import_script.py tests/test_task_templates.py -q` → PASS.
- [ ] **Step 5: 커밋** — `feat(sp16): 건강앱 가져오기 노트북 스크립트, README, 체크리스트`

### 마무리

- [ ] 전체: `python -m pytest -q`(slow 포함 한 번) → 모두 PASS. `cd web/app && npm test && npm run build && npm run size` → PASS.
- [ ] repo `code-reviewer` 서브에이전트로 브랜치 리뷰, BLOCKER/SHOULD 반영 후 develop에 머지.
- [ ] 노트북 수용은 Dahun: `docs/sp16/laptop-checklist.md`. S2에서 부록 B 밖의 종류가 나오면 매핑을 더하고 `ACTIVITY_MAP_VERSION`을 올린다.
