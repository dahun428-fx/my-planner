# SP13 객관적 위치 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 상태창 영역 줄에 "만족 n · 위치 n"을, 그 아래 타고난 스탯을, 그리고 객관적 위치 상세 화면과 측정값 확인 카드를 더한다.

**Architecture:** 측정값은 `022_standing.sql`의 `standing_measures`(DB), 통계 기준표는 `src/my_planner/standing/benchmarks/2026.toml`(저장소), 점수는 읽을 때 순수 함수(`standing/score.py`)로 계산한다. 분기 스냅숏(`standing_snapshots`)이 하락 이유(내 변화 / 세상 변화)를 나눈다. 두뇌는 `propose_measures` 도구로 확인 카드(하네스 조각 `ui_measure_confirm`)만 내고, 저장은 앱의 `/actions save_measures`가 한다.

**Tech Stack:** Python 3.12, SQLite, `tomllib`, aiohttp, pydantic / Next.js(정적 PWA), vitest, Playwright.

**Spec:** `docs/superpowers/specs/2026-11-01-sp13-objective-standing-design.md` v1.2 (Dahun 승인 2026-11-01, 맨 위 "v1.2 정정" 포함). 이하 "스펙 N.N"은 이 문서의 절. ADR 0020. 채점 숫자의 출처는 프로젝트 폴더 `/mnt/project-files/social-level/benchmarks/` 세 문서(공개 통계, 개인 값 없음).

## Global Constraints

- 브랜치는 `origin/develop`에서, PR base는 `develop`.
- **개인 값은 저장소·로그·활동 `summary`·테스트 고정 자료에 넣지 않는다.** 테스트 자료는 이 계획의 가짜 사람(Task 3 고정 자료)만 쓴다. 로그에는 지표 이름·개수·id만(스펙 12장).
- 대시보드 기기(`devices.client = 'dashboard'`)는 `/standing*`에 `403 forbidden`("이 화면에서는 볼 수 없어요."), `/status`에는 `standing`·`innate` 키가 없다(값이 null이 아니라 키가 없음).
- 경험치는 오르기만(ADR 0006). X14 = 20, `source_kind` `standing`, `source_ref` `standing:<YYYY-Qn>`, `label` "측정값 기록". 분기마다 한 번, 지워도 남는다.
- 화면 문구는 "위치 59"만. "상위 n%", "100명 중", "등수", "패배", "뒤처짐", "실패"를 쓰지 않는다. 정본 금지어 목록은 `harness/prompts/system.md`의 `banned-words` 블록이다("실패"는 이미 있다): `등수`, `패배`, `뒤처짐`을 그 블록에 더한다. 앱 `scripts/lint-copy.mjs`의 목록에도 같은 넷을 더한다.
- 하락 표시 경계 ±5(스펙 9.2, D4). 디버프는 영역 단위 `Δm ≤ −5`일 때만.
- 상수와 자리: `MEASURES_PER_SAVE_MAX = 30`(`tools/standing.py`), `XP_STANDING = 20`·`LABEL_STANDING = "측정값 기록"`(`status/xp.py`), `HEALTH_AREA_WEIGHTS = (60, 40)`·`ERR_BASE = 5`·`ERR_ESTIMATE = 8`(`standing/score.py`), `DRIFT_MIN = 5`(`standing/drift.py`). X14의 분기는 저장한 순간의 논리적 날짜(`logical_date`)가 든 분기.
- 점수 반올림: 축 점수와 시장 점수는 `floor(x + 0.5)`(반올림 half-up), 0~100으로 자른다. 시장 점수는 반올림한 축 점수로 계산한다.
- BE 검사: `python -m pytest -q`, `ruff check src tests`, `mypy src`(저장소 설정 그대로). 앱: `cd web/app && npm test && npm run typecheck && npm run lint:copy`, e2e `npm run e2e`(POSIX 환경변수 문법이라 Git Bash·CI에서). 앱·대시보드 타입은 각 폴더의 `npm run gen:types`(스키마를 스스로 만든다. PowerShell `>` 리다이렉트는 UTF-16이 되므로 쓰지 않는다).
- **모든 Task의 Step 2 기대 출력**: 새 테스트가 `ImportError`/`ModuleNotFoundError` 또는 `AssertionError`로 FAIL(그 밖의 오류로 깨지면 테스트부터 고친다). **모든 Task의 Step 4**: 그 Task의 테스트 파일 PASS, 그 뒤 `python -m pytest -q`·`ruff check src tests`·`mypy src`가 모두 종료 코드 0.
- 파일 읽기는 늘 `encoding="utf-8"`(노트북 기본 cp949).
- 새 화면은 앱 전용. 텔레그램·대시보드 화면은 바꾸지 않는다.

## Review Focus

1. **단위를 잘못 말한 값**("연봉 5500"을 원 단위로): `salary_krw`는 1,000,000 미만이면 거절해 확인 카드가 고치게 한다. Task 1 `test_salary_in_manwon_is_rejected`.
2. **태어난 해가 없는 상태**: 축 점수는 나이 구간이 필요하다. 프로필이 없으면 키·학벌·집안만 점수가 있고 영역은 "위치 —", 안내는 "태어난 해를 넣으면 생겨요". Task 3 `test_profile_missing_scores_only_innate`.
3. **스냅숏 뒤에 그 측정값을 지움**: 하락 계산은 스냅숏의 `inputs_json` 값으로 다시 계산하므로 지운 id가 있어도 깨지지 않는다. Task 4 `test_drift_survives_deleted_snapshot_measure`.
4. **아직 유효하지 않은 다음 해 기준표**(`2027.toml`, `effective_from = 2027-11-01`)가 미리 들어와 있을 때 오늘 계산은 2026 표를 쓴다. Task 2 `test_future_bench_not_used_yet`.
5. **같은 자격을 두 번**(`toeic:825` 뒤 `toeic:900`): 자격은 `:` 앞 키마다 최신 한 줄만 센다. Task 3 `test_cert_same_key_latest_only`.

---

### Task 1: 마이그레이션 022, 지표 목록, `StandingRepo` (SP13-01)

**Files:**
- Create: `src/my_planner/store/migrations/022_standing.sql`
- Create: `src/my_planner/standing/__init__.py`, `src/my_planner/standing/metrics.py`
- Create: `src/my_planner/store/repos/standing.py`
- Test: `tests/test_migrations.py`(더함), `tests/test_standing_repo.py`(새)

**Interfaces:**
- Produces:
  - SQL: 스펙 6.1의 두 표 그대로 + `status_xp_ledger` 옮기기(021 63~80줄 복사, `source_kind` 목록 끝에 `'standing'`).
  - `metrics.py`:
    - `MetricKind = Literal["num", "enum", "multi"]`(`multi` = `cert`, 값마다 한 줄)
    - `@dataclass(frozen=True) MetricDef(name: str, label: str, kind: MetricKind, unit: str | None, lo: float | None, hi: float | None, values: tuple[str, ...] = ())`
    - `METRICS: dict[str, MetricDef]` — 스펙 6.2 + v1.2 정정의 지표 전부. 범위(포함): `profile_birth_year` 1930~(올해−15, 검사 때 계산) · `height_cm` 140~220 · `weight_kg` 35~200 · `body_fat_pct` 3~60 · `fat_free_mass_kg` 25~120 · `skeletal_muscle_kg` 15~70 · `waist_cm` 50~150 · `face_rating`·`grooming_rating` 0~100 · `bp_sys` 70~250 · `bp_dia` 40~150 · `fasting_glucose` 40~400 · `ldl` 20~400 · `alt` 1~1000 · `shuttle_run_laps` 0~200 · `grip_rel_pct` 10~150 · `situp_per_min` 0~100 · `run_6k_min` 15~120 · `squat_1rm_kg`·`bench_1rm_kg`·`deadlift_1rm_kg` 0~400 · `exercise_days_week` 0~7 · `salary_krw` 1,000,000~2,000,000,000 · `company_tier` 0~20 · `role_points` 0~15 · `years_exp` 0~50 · `level_points` 0~6 · `outside_activity_count` 0~5 · `recruiter_contacts_6m` 0~200 · `offer_ratio` 0.5~5 · `net_worth_krw` −5e9~1e11 · `monthly_saving_krw` −1e8~1e8 · `monthly_net_income_krw` 0~1e8 · `savings_rate_pct` −100~100 · `support_people` 0~50 · `monthly_meetups` 0~60 · `family_net_worth_krw` −1e10~1e12. 열거값은 스펙 표 그대로. `cert` 값: `jlpt_n1`, `jlpt_n2`, `engineer_info`, `aice_associate`, `pro_license`, `toeic:<10~990 정수>`, 그 밖 `other:<1~30자 영숫자_>`.
    - 라벨(한국어, 카드·목록에 보임): 예 `body_fat_pct` "체지방률", `salary_krw` "연봉(세전)", `cert` "자격". 모든 지표에 하나씩.
    - `validate(metric: str, value: float | str, measured_on: date, today: date) -> str | None` — 오류 문구 또는 None. 목록 밖 지표 "모르는 측정값이에요.", 범위 밖 "{라벨} 값이 맞지 않아요.", 미래 날짜 "측정일이 오늘보다 늦어요." `today`는 논리적 날짜가 아니라 **달력상 현지 날짜**(자정~하루 경계 사이에 그날 결과지가 거절되지 않게). 부르는 쪽이 `clock.now()`의 현지 날짜를 넘긴다.
  - `store/repos/standing.py`:
    - `@dataclass(frozen=True) Measure(id: int, metric: str, value_num: float | None, value_text: str | None, measured_on: date, source_kind: str, source_ref: str | None, reliability: str, created_at: datetime)`
    - `class StandingRepo(conn, clock)`:
      - `add(metric, value: float | str, measured_on: date, source_kind: str, source_ref: str | None, reliability: str, now: datetime) -> int` (검사는 부르는 쪽, 저장소는 `validate`를 한 번 더 불러 `ValueError`)
      - `get(id) -> Measure | None`, `delete(id, now) -> bool`(지운 것 표시), `restore(id) -> bool`
      - `active() -> list[Measure]`(지우지 않은 것, `metric`, `measured_on` 내림차순, `id` 내림차순)
      - `latest(as_of: date | None = None) -> dict[str, Measure | list[Measure]]` — 지표마다 최신 하나(`measured_on`, 다음 `id`가 큰 것). `cert`는 `:` 앞 키마다 최신 하나씩의 목록. `as_of`가 있으면 `measured_on <= as_of`만.
      - `has_import(metric, measured_on, value_text: str | None = None) -> bool`(`source_kind='import'`, 지우지 않은 것. `value_text`를 주면 그 값까지 같아야 참 — `cert`용)
      - `snapshot(period, axis, cohort) -> SnapshotRow | None`, `snapshots_for(period) -> list[SnapshotRow]`, `latest_period_before(period: str) -> str | None`, `put_snapshot(period, axis, cohort, score, bench_version, inputs_json, taken_at) -> None`(INSERT OR REPLACE)
      - `@dataclass(frozen=True) SnapshotRow(period, axis, cohort, score: int, bench_version: str, inputs: dict[str, Any], taken_at: datetime)`
  - 쓰기는 부르는 쪽 `transaction`에 맡긴다(`WorkoutRepo`와 같은 방식).

- [ ] **Step 1: 실패하는 테스트**
  - `test_migrations.py::test_022_standing_tables`: 표 둘이 있고, `standing_measures`에 `value_num`·`value_text`가 둘 다 NULL인 행은 `IntegrityError`, `source_kind='bogus'`도 `IntegrityError`.
  - `test_migrations.py::test_022_ledger_moved_intact`: 021 상태에서 원장 3행(합 25) → 022 → 행 3, 합 25, `source_kind='standing'` 삽입 성공.
  - `test_standing_repo.py::test_validate_rejects_unknown_range_future`(T1): `validate("iq", 120, ...)` 오류, `validate("body_fat_pct", 80, ...)` 오류, 내일 날짜 오류, `validate("body_fat_pct", 17.5, 오늘)` None.
  - `test_standing_repo.py::test_salary_in_manwon_is_rejected`: `validate("salary_krw", 5500, ...)`는 오류, `55_000_000`은 None.
  - `test_standing_repo.py::test_latest_by_date_then_id`(T2): 같은 지표 (2026-09-01, id1) (2026-10-01, id2) (2026-10-01, id3) → `latest()["weight_kg"].id == id3`. id3을 `delete` → id2. `as_of=2026-09-15` → id1.
  - `test_standing_repo.py::test_cert_latest_per_key`: `toeic:825`(9월) `toeic:900`(10월) `jlpt_n1` → `latest()["cert"]` 값 집합 `{"toeic:900", "jlpt_n1"}`.
  - `test_standing_repo.py::test_snapshot_put_replaces_and_period_before`: `2026-Q3`·`2026-Q4` 넣고 같은 키 다시 넣으면 한 행. `latest_period_before("2026-Q4") == "2026-Q3"`, `latest_period_before("2026-Q3") is None`.
- [ ] **Step 2:** `python -m pytest tests/test_migrations.py tests/test_standing_repo.py -q` → FAIL.
- [ ] **Step 3:** SQL, `metrics.py`, `StandingRepo` 구현. `cert` 키는 `value_text.split(":")[0]`.
- [ ] **Step 4:** 같은 명령 PASS, `python -m pytest -q` 전체 PASS.
- [ ] **Step 5:** `git commit -m "feat(sp13): 022 측정값 표와 StandingRepo"`

### Task 2: 기준표 파일과 읽기 (SP13-02)

**Files:**
- Create: `src/my_planner/standing/benchmarks/2026.toml`, `src/my_planner/standing/bench.py`
- Modify: `pyproject.toml`(패키지 데이터에 `standing/benchmarks/*.toml`, 지금 `harness/prompts/*.md`를 넣는 방식과 같게)
- Test: `tests/test_standing_bench.py`

**Interfaces:**
- Produces:
  - `Points = tuple[tuple[float, float], ...]`
  - `@dataclass(frozen=True) Bench(version: str, effective_from: date, raw: Mapping[str, Any])` + 메서드 `table(*path: str) -> Mapping[str, Any]`, `points(*path: str) -> Points`, `estimate(*path: str) -> bool`(그 표의 `estimate`)
  - `load_bench(today: date, directory: Path | None = None) -> Bench` — `effective_from <= today`인 파일 가운데 가장 늦은 것. 없으면 `effective_from`이 가장 이른 것. 기본 폴더는 패키지 안 `standing/benchmarks`.
  - `load_bench_version(version: str, directory: Path | None = None) -> Bench | None`
  - `interp(x: float, pts: Points) -> float` — 첫 점 아래는 첫 점의 값, 마지막 점 위는 마지막 값, 사이는 선형.
- `2026.toml` 내용(값은 이대로. 표마다 `source`, `year`, `url`, `estimate`를 그 표 위 주석의 문서 절에서 옮긴다. 금액은 만원):

```toml
version = "2026.1"
effective_from = "2026-11-01"

[height]            # body-health.md 1-1·1-2, SK8-논문. 평균·SD는 공식, 백분위는 정규분포 가정이라 estimate = true
mean = 174.6
sd = 5.68

[looks]             # body-health.md 6-2 + 스펙 8.2 (estimate = true)
body_share = 70
face = 15
grooming = 15
body_weights = { waist = 30, body_fat = 28, ffmi = 30, bmi = 12 }
waist = { mean = 86.9, sd = 8.81, full_below = 75 }
body_fat_bands = [[8, 70], [15, 100], [18, 85], [22, 70], [25, 50], [28, 30]]   # x < 상한 → 점수
body_fat_top = 10
ffmi = { mean = 19.1, sd = 1.9 }
bmi_bands = [[18.5, 30], [21, 80], [25, 100], [27, 70], [30, 40]]
bmi_top = 10

[health]            # body-health.md 4-1, 4-2, 6-3 (estimate = true)
weights = { cardio = 20, strength = 15, endurance = 10, bp = 15, glucose = 10, ldl = 10, alt = 5, smoking = 5, drinking = 5, exercise = 5 }
grade_scores = [90, 75, 55, 35, 10]   # 1등급, 2등급, 3등급, 등급 밖(위험 아님), 위험
nfa."30_34" = { shuttle = [49, 40, 31], shuttle_risk = 22, grip = [62.6, 57.2, 51.8], grip_risk = 46.4, situp = [47, 41, 35] }
nfa."35_39" = { shuttle = [45, 37, 28], shuttle_risk = 20, grip = [62.1, 56.6, 51.1], grip_risk = 46.4, situp = [45, 39, 33] }
run_6k = [[30, 75], [36, 55], [42, 35]]         # 분 이하 → 점수, 그 밖 10
lift_ratio = [[4.0, 90], [3.0, 75], [2.25, 55], [1.5, 35]]   # (스쿼트+벤치+데드)/체중 이상 → 점수, 그 밖 10
checkup_fill = { normal = 100, watch = 75, abnormal = 30 }
smoking = { none = 100, quit = 80, current = 0 }
drinking = { none = 100, monthly_binge = 40, high_risk = 0 }
exercise = [[2, 100], [1, 60]]                  # 주당 날 이상 → 점수, 그 밖 15

[income]            # money-career.md 6-2 P_income (estimate = true)
national."30_34" = [[0, 0], [2700, 10], [3700, 25], [5000, 50], [6600, 75], [8700, 90], [10500, 95], [15000, 99]]
national."35_39" = [[0, 0], [2700, 10], [3700, 25], [5000, 50], [6600, 75], [8700, 90], [10500, 95], [15000, 99]]
peer.dev_general = [[0, 0], [3800, 10], [4400, 25], [5300, 50], [6800, 75], [8800, 90], [10500, 95], [15000, 99]]
peer.ai_ml = [[0, 0], [4300, 10], [5200, 25], [6500, 50], [8200, 75], [10500, 90], [12500, 95], [18000, 99]]

[networth]          # money-career.md 6-2 P_networth (estimate = true). 0 이하 = 5
national = [[0, 5], [4500, 10], [6900, 20], [12200, 40], [15600, 50], [20000, 60], [35400, 80], [54300, 90], [77400, 95], [140000, 99]]
peer = [[0, 5], [5600, 10], [8600, 20], [15300, 40], [19500, 50], [25000, 60], [44300, 80], [67900, 90], [96800, 95], [180000, 99]]

[saving]            # money-career.md 6-2 P_saving (estimate = true)
points = [[0, 5], [10, 25], [20, 40], [28, 50], [40, 70], [50, 85], [60, 95]]
missing = 25

[money]             # money-career.md 6-2 (estimate = true)
weights = { income = 40, networth = 45, saving = 15 }

[career]            # money-career.md 6-3 (estimate = true)
weights = { rubric = 60, income = 40 }
years = { per_year = 1.2, cap_years = 10, cap = 20 }
outside_per = 3
recruiter = [[12, 15], [6, 11], [3, 8], [1, 4]]     # 이상 → 점수, 그 밖 0
offer = [[1.3, 15], [1.15, 10], [1.0, 5]]
if_present = { recruiter_contacts_6m = 3, outside_activity_count = 2, offer_ratio = 1.1 }   # 빈칸일 때 범위 상단
raw_pct.national = [[0, 0], [20, 35], [30, 55], [40, 70], [50, 80], [60, 88], [70, 94], [80, 97], [90, 99]]
raw_pct.peer = [[0, 0], [20, 10], [30, 20], [40, 35], [50, 50], [60, 65], [70, 80], [80, 90], [90, 97]]

[relations]         # social-market.md 6-3 (estimate = true)
support = [[4, 68], [2, 50], [1, 32]]              # 이상 → 기본점, 0명 12
support_none = 12
meetups = [[8, 15], [5, 10], [2, 7]]               # 월 이상 → 가점, 그 밖 0
dating = { single = 0, dating = 6, married = 7 }
lonely_yes = -5
missing_support = { score = 45, low = 35, high = 55 }

[intellect]         # social-market.md 6-4 (estimate = true)
base = { jlpt_n1 = 95, jlpt_n2 = 85, engineer_info = 84, pro_license = 97, aice_associate = 60 }
other = 60
toeic = [[0, 0], [600, 35], [700, 55], [825, 80], [900, 90], [950, 95], [990, 97]]
extra_each = 4
cap = 99
none = 50

[education]         # social-market.md 6-1 (estimate = true)
tiers = { hs = 20, college2 = 40, local_private = 56, seoul_mid_low = 73, seoul_mid_high = 84, top = 95 }
double_major = 3

[family]            # social-market.md 6-2, 2-2 (estimate = true)
points = [[0, 0], [10000, 30], [30000, 57], [100000, 88], [450000, 99]]   # 2-2: 10억~45억 = 88~99
parent_60plus = -4
support = { none = 0, receive = 2, support = -7 }

[markets]           # social-market.md 5-2, 5-3 (가중치 값 자체가 추정, estimate = true)
marriage = { career = 20, money = 18, looks = 13, height = 10, family = 10, education = 9, health = 7, relations = 7, intellect = 6 }
career = { career = 30, money = 5, looks = 7, height = 3, family = 5, education = 12, health = 8, relations = 12, intellect = 18 }
```

- [ ] **Step 1: 실패하는 테스트**
  - `test_load_bench_2026`: `load_bench(date(2026, 11, 1)).version == "2026.1"`, `interp(6000, bench.points("income", "national", "30_34")) == 50 + 25 * 1000 / 1600`(= 65.625).
  - `test_future_bench_not_used_yet`: tmp 폴더에 2026.toml 사본과 `version="2027.1"`, `effective_from="2027-11-01"`인 2027.toml → `load_bench(date(2027, 1, 5), tmp).version == "2026.1"`, `load_bench(date(2027, 11, 1), tmp).version == "2027.1"`.
  - `test_load_bench_version`: `load_bench_version("2026.1").effective_from == date(2026, 11, 1)`, `load_bench_version("1999.1") is None`.
  - `test_interp_edges`: 첫 점 아래·마지막 점 위·정확히 점 위.
  - `test_every_table_has_source`: 맨 위 키 둘(`version`, `effective_from`)을 뺀 모든 표에 `source`(빈 글 아님), `year`(정수), `url`(`https://`로 시작), `estimate`(불) 있음.
- [ ] **Step 2:** `python -m pytest tests/test_standing_bench.py -q` → FAIL.
- [ ] **Step 3:** 구현. `tomllib`, 날짜는 `date.fromisoformat`.
- [ ] **Step 4:** PASS, 전체 PASS. `python -m build --wheel` 뒤 `python -c "import zipfile,glob; print(any(n.endswith('standing/benchmarks/2026.toml') for n in zipfile.ZipFile(glob.glob('dist/*.whl')[0]).namelist()))"` → `True`(노트북은 editable 설치라 소스 트리를 읽지만 휠도 맞게 둔다. `build`가 없으면 `pip install build`, dist/는 커밋하지 않는다).
- [ ] **Step 5:** `git commit -m "feat(sp13): 2026 기준표와 load_bench"`

### Task 3: 점수 계산 `score.py`, `markets.py` (SP13-03)

**Files:**
- Create: `src/my_planner/standing/score.py`, `src/my_planner/standing/markets.py`
- Create: `tests/fixtures/standing_sample.json`, `tests/fixtures/standing_sample_expected.json`
- Test: `tests/test_standing_score.py`

**Interfaces:**
- Consumes: Task 1 `Measure`, Task 2 `Bench`, `interp`.
- Produces:
  - `Axis = Literal["career", "money", "health", "looks", "relations", "intellect", "height", "education", "family"]`, `AXES: tuple[Axis, ...]`(이 순서), `INNATE = ("height", "education", "family")`, `AXIS_AREA = {"career": "career", "money": "finance", "health": "health", "looks": "health", "relations": "relationships", "intellect": "learning"}`, `AXIS_LABELS`(스펙 5.1 이름. `intellect` = "자격·학습 실적").
  - `Cohort = Literal["national", "peer"]`
  - `Values = Mapping[str, float | str | list[str]]` — 지표 → 값(`cert`는 값 목록). `values_from(latest: dict[str, Measure | list[Measure]]) -> tuple[Values, dict[str, int]]`(값, 지표 → 측정값 id. `cert`는 빼고 id 없음).
  - `@dataclass(frozen=True) AxisScore(axis: Axis, score: int, raw: float, low: int, high: int, reliability: Literal["high", "mid", "low"], estimate: bool, inputs: tuple[str, ...], missing: tuple[str, ...], assumed: tuple[str, ...])` — `inputs`는 쓴 지표 이름, `missing`은 빈 지표, `assumed`는 가정값을 넣은 하위 항목 이름.
  - `age_band(values: Values, today: date) -> str | None` — `today.year − profile_birth_year − 1`(생일을 모르므로 만 나이를 낮게), 34 이하 `"30_34"`, 35~39 `"35_39"`, 그 밖은 가까운 쪽. 태어난 해 없으면 None.
  - `peer_key(values) -> str | None` — `profile_region == "capital"`이고 `profile_job_family`가 `ai_ml`·`dev_general`이면 그 값, 아니면 None.
  - `score_all(values: Values, bench: Bench, cohort: Cohort, today: date) -> dict[Axis, AxisScore]` — 점수가 없는 축은 키가 없다. `peer`인데 `peer_key`가 None이면 빈 사전. 태어난 해가 없으면 고정 축 셋만. `profile_sex == "f"`이면 학벌·집안만(지금 기준표는 남성 표뿐, 영역 안내 "지금 기준표는 남성 표만 있어요.").
  - `area_positions(scores: Mapping[Axis, AxisScore]) -> dict[str, float | None]` — 6영역, 축의 `raw`(반올림 전 실수)로 계산. 건강 = 0.6 health + 0.4 looks(하나만 있으면 그 하나), `quality_of_life`는 늘 None. 화면 값은 `round_half_up`.
  - `round_half_up(x: float) -> int`
  - `markets.py`: `@dataclass(frozen=True) Market(score: int | None, excluded: tuple[Axis, ...])`, `market_scores(scores: Mapping[Axis, AxisScore], bench: Bench) -> dict[str, Market]`(`"marriage"`, `"career"`). 없는 축은 빼고 남은 가중치로 나눈다. 축이 하나도 없으면 `score=None`.
- 축별 규칙(스펙 8.2를 숫자로 고정. 하위 항목 점수는 실수, 축 점수에서만 반올림):
  - **키**: `Φ((키 − mean)/sd) × 100`. `Φ(z) = 0.5 × (1 + erf(z/√2))`.
  - **외모**: 키가 있어야 FFMI·BMI를 계산한다. `fat_free_mass_kg`가 없고 체중·체지방률이 있으면 `체중 × (1 − 체지방률/100)`. 허리 `< full_below`면 100, 아니면 `100 − Φ((허리 − 86.9)/8.81) × 100`. 체지방·BMI는 `x < 상한`인 첫 구간 값, 없으면 `*_top`. FFMI `Φ((FFM/키m² − 19.1)/1.9) × 100`. 몸 = `Σ 가중치 × (하위 항목 또는 50) / 100`, 몸 하위 항목이 하나도 없으면 축 없음. 외모 = `0.70 × 몸 + 0.15 × (face_rating 또는 50) + 0.15 × (grooming_rating 또는 50)`.
  - **건강**: 나이 구간의 `nfa` 표. 등급 점수 = 1등급 컷 이상 90, 2등급 이상 75, 3등급 이상 55, 그 밖 위험 컷 초과 35, 위험 컷 이하 10(근지구력은 위험 컷이 없어 3등급 미만 35). 심폐 = 왕복오래달리기, 없으면 `run_6k_min`이 `[[30,75],[36,55],[42,35]]`의 상한 이하인 첫 값(그 밖 10, `estimate`). 근력 = 상대악력, 없으면 1RM 셋과 체중이 다 있을 때 합/체중으로 `lift_ratio`(그 밖 10). 근지구력 = `situp_per_min`. 혈압: `sys ≥ 140 또는 dia ≥ 90` 10, `sys ≥ 130 또는 dia ≥ 80` 45, `sys ≥ 120` 75, 그 밖 100. 혈당 `< 100` 100, `< 126` 35, 그 밖 5. LDL `< 130` 100, `< 160` 55, 그 밖 15. ALT `≤ 30` 100, `≤ 40` 70, `≤ 80` 30, 그 밖 5. 검진 수치가 없고 `checkup_flag`가 있으면 혈압·혈당·LDL·ALT 가운데 빈 것을 `checkup_fill` 값으로(가정이 아니라 채움. 대신 신뢰도를 한 단계 내린다). 흡연·음주는 표. 운동 습관 = `exercise_days_week`(Task 4가 운동 기록 `derived`로 바꿔 넣는다) `≥ 2` 100, `≥ 1` 60, 그 밖 15. 빈 하위 항목은 50(가정). 건강 = `Σ 가중치 × 점수 / 100`. 하위 항목이 하나도 없으면 축 없음.
  - **소득 백분위**: `national`은 `income.national.<나이 구간>`, `peer`는 `income.peer.<peer_key>`. 값은 `salary_krw / 10_000`.
  - **직업**: `salary_krw`와 `company_tier`가 있어야 축이 있다. `T = company_tier`, `R = role_points(없으면 0)`, `Y = min(20, min(years_exp, 10) × 1.2 + level_points)`(없으면 0), `O = 3 × outside_activity_count`, `C = recruiter 표`, `M = offer 표`(빈칸은 0). `Raw = T+R+Y+O+C+M`, 직업 = `0.6 × interp(Raw, raw_pct.<cohort>) + 0.4 × 소득 백분위`.
  - **경제력**: 연봉과 `net_worth_krw`가 있어야 한다. 순자산 `≤ 0`이면 5, 아니면 `interp(값/10_000, networth.<cohort>)`. 저축률 = `savings_rate_pct`, 없으면 `monthly_saving_krw / monthly_net_income_krw × 100`, 그것도 없으면 점수 25(가정). 경제력 = `0.40 × 소득 + 0.45 × 순자산 + 0.15 × 저축률 점수`.
  - **관계**: `support_people`가 있으면 `support` 표(이상 → 기본점, 0명 12) + `meetups` 가점(빈칸 0), 없으면 기본 45. 그 위에 `dating`, 외로움 `yes`면 −5. 0~100.
  - **자격**: `cert` 값마다 기본점(`toeic:n`은 `interp(n, toeic)`, `base`에 없는 키는 `other`). `min(99, 가장 높은 값 + 4 × (나머지 개수))`. 자격이 없으면 50(가정, `assumed = ("cert",)`).
  - **학벌**: `tiers[education_tier] + (3 if double_major == "yes")`. 없으면 축 없음.
  - **집안**: `interp(family_net_worth_krw/10_000, family.points) + (−4 if family_parent_60plus == "yes") + support[family_support]`, 0~100. 없으면 축 없음.
- 오차 범위와 신뢰도:
  - `err = 8 if estimate else 5`. `low = score − err`, `high = score + err`, 0~100.
  - 가정한 하위 항목이 있으면 그 하위 항목을 모두 0으로, 모두 100으로 넣은 두 점수로 `low = min(low, 그 0점)`, `high = max(high, 그 100점)`.
  - 관계에서 `support_people`가 없으면 `low = min(low, 35)`, `high = max(high, 55)`(`missing_support`).
  - 직업은 `recruiter_contacts_6m`·`outside_activity_count`·`offer_ratio` 가운데 빈 것을 `if_present` 값으로 넣은 점수로 `high = max(high, 그 점수)`.
  - 신뢰도: 가정 개수 0이고 쓴 표가 `estimate = false` → `high`, 가정 1개 이하 또는 추정 표 → `mid`, 가정 2개 이상 → `low`. 검진 채움을 썼거나 외모에서 `face_rating`이 들어갔으면 한 단계 내린다(`high`→`mid`→`low`). 관계에서 `support_people`가 없으면 `low`.
- 고정 자료 `tests/fixtures/standing_sample.json`(가짜 사람, 가져오기 파일 모양 `{"version": 1, "measures": [{"metric", "value", "measured_on"}]}`, 측정일은 모두 `2026-10-01`, `cert`는 값마다 한 줄):
  `profile_birth_year 1992, profile_sex m, profile_region capital, profile_job_family dev_general, height_cm 176, weight_kg 72.0, body_fat_pct 19.0, waist_cm 82.0, face_rating 55, grooming_rating 70, shuttle_run_laps 42, grip_rel_pct 55.0, situp_per_min 38, bp_sys 118, bp_dia 78, fasting_glucose 96, ldl 142, alt 28, smoking quit, drinking monthly_binge, exercise_days_week 1.5, salary_krw 62000000, company_tier 15, role_points 9, years_exp 7, level_points 4, outside_activity_count 1, recruiter_contacts_6m 4, offer_ratio 1.2, net_worth_krw 180000000, monthly_saving_krw 1500000, monthly_net_income_krw 4500000, support_people 3, monthly_meetups 3, dating_status dating, lonely_often yes, cert toeic:900, cert jlpt_n2, education_tier local_private, double_major no, family_net_worth_krw 250000000, family_support support, family_parent_60plus no`
- 기대값 `tests/fixtures/standing_sample_expected.json`(오늘 2026-11-01. 이 계획을 쓸 때 별도 계산기로 구한 값):

```json
{"today": "2026-11-01",
 "national": {"height": 60, "looks": 65, "health": 73, "career": 79, "money": 61, "relations": 58, "intellect": 94, "education": 56, "family": 43, "markets": {"marriage": 65, "career": 72}},
 "peer": {"height": 60, "looks": 65, "health": 73, "career": 63, "money": 56, "relations": 58, "intellect": 94, "education": 56, "family": 43, "markets": {"marriage": 61, "career": 67}}}
```

- [ ] **Step 1: 실패하는 테스트**
  - `test_sample_matches_expected`(T3): 고정 자료 → `values_from` → 두 비교 집단 `score_all` + `market_scores`가 기대값과 ±1.
  - `test_height_180_is_83`, `test_waist_below_75_full`.
  - `test_saving_missing_assumes_25`(T4): 고정 자료에서 저축 두 지표를 빼면 경제력 `assumed == ("saving",)`, 국가 점수 = `round_half_up(0.40×inc + 0.45×nw + 0.15×25)`(테스트가 `interp`로 inc·nw를 구해 비교).
  - `test_relations_missing_support_is_45_low`(T4): `support_people`·`monthly_meetups`·`lonely_often` 없음, `dating_status single` → 점수 45, `low ≤ 35`, `high ≥ 55`, 신뢰도 `low`.
  - `test_career_missing_recruiter_widens_high`(T4): 리크루터·오퍼·외부활동을 빼면 점수는 내려가고 `high`는 `if_present` 값으로 계산한 점수 이상.
  - `test_checkup_flag_fills_and_lowers_reliability`: 검진 수치 넷을 빼고 `checkup_flag normal` → 혈압 등 100으로 채워지고 `assumed`에 없으며, 신뢰도가 한 단계 낮다.
  - `test_profile_missing_scores_only_innate`: 태어난 해를 빼면 `score_all(...).keys() == {"height", "education", "family"}`, `area_positions`는 모두 None.
  - `test_peer_needs_capital_and_dev`: `profile_region other` → `score_all(..., "peer", ...) == {}`.
  - `test_cert_same_key_latest_only`: Task 1 저장소에 `toeic:825`(9월) `toeic:900`(10월) → 자격 = `interp(900, toeic)` = 90(다른 자격 없음).
  - `test_markets_reweight_missing_axes`: 키·학벌·집안만 있으면 결혼시장 = `(키×10 + 집안×10 + 학벌×9)/29` 반올림, `excluded`에 나머지 여섯.
  - `test_health_area_weighted`: health 80, looks 60 → 건강 영역 72.0. looks만 있으면 60.0. `quality_of_life` None.
- [ ] **Step 2:** `python -m pytest tests/test_standing_score.py -q` → FAIL.
- [ ] **Step 3:** 구현. 축마다 작은 함수 하나.
- [ ] **Step 4:** PASS, 전체 PASS.
- [ ] **Step 5:** `git commit -m "feat(sp13): 9축 점수와 시장 점수"`

### Task 4: 하락 이유 나누기와 스냅숏 (SP13-04)

**Files:**
- Create: `src/my_planner/standing/drift.py`, `src/my_planner/standing/service.py`
- Test: `tests/test_standing_drift.py`

**Interfaces:**
- Consumes: Task 1~3.
- Produces:
  - `drift.py`:
    - `@dataclass(frozen=True) Drift(delta: float, world: float, me: float)` — 스펙 9.2의 Δ, Δw, Δm.
    - `split(before_values: Values, before_bench: Bench, before_day: date, now_values: Values, now_bench: Bench, today: date, area: str) -> Drift | None` — 영역 위치(반올림 전)로 계산. 앞이나 지금의 영역 위치가 없으면 None. **계산 전에 두 값 묶음을 합집합으로 채운다**: 한쪽에만 있는 지표는 다른 쪽에 같은 값을 넣는다. 그래서 빈칸을 처음 채우거나(가정 50 → 실제 값) 측정값을 지우는 것은 내 변화가 아니고, 같은 지표의 값이 바뀐 것만 내 변화다(ADR 0006: 자료를 넣었다고 디버프가 붙지 않는다).
    - `marks(d: Drift) -> list[dict[str, Any]]` — `[{"kind": "me", "delta": n}]`(`Δm ≥ 5` 또는 `≤ −5`, `n = round_half_up(Δm)`, 부호 있음), `{"kind": "world", "delta": n}`(`Δw ≤ −5`). 둘 다면 me 먼저. 그 밖 빈 목록.
    - `debuff(d: Drift | None) -> bool` — `Δm ≤ −5`.
  - `service.py`:
    - `with_derived(values: Values, workout: WorkoutRepo | None, today: date) -> Values` — 지난 56일에 운동 기록이 있으면 `exercise_days_week = len(log_days(today − 27일, today)) / 4`로 바꾼다.
    - `current(conn, clock, today: date, bench_dir: Path | None = None) -> StandingNow` — `@dataclass StandingNow(values, ids, bench, scores: dict[Cohort, dict[Axis, AxisScore]], areas: dict[Cohort, dict[str, float | None]], markets: dict[Cohort, dict[str, Market]], profile_missing: bool)`.
    - `base_snapshot(repo, period: str) -> tuple[Values, str, date] | None` — `latest_period_before(period)`의 스냅숏, 없으면 그 분기 스냅숏. `national` 줄 하나의 `inputs_json`(모든 줄이 같은 값을 갖는다)에서 값, `bench_version`, `taken_at`의 현지 날짜.
    - `area_drifts(conn, clock, today, now: StandingNow) -> dict[str, Drift | None]` — `national`만.
    - `write_snapshot(conn, clock, period: str, *, as_of: date | None = None) -> int` — 쓴 줄 수. `as_of`가 있으면 그날까지의 측정값과 그날 유효한 기준표, 스냅숏 `taken_at`은 `as_of`의 23:59 현지. 태어난 해가 없으면 0. `inputs_json = {"values": {...}, "ids": {...}}`.
    - `snapshot_if_first(conn, clock, today) -> bool` — 스냅숏이 **하나도** 없을 때만 지금 분기 스냅숏을 쓴다(첫 기준선, 스펙 9.1). 그 뒤 분기들의 스냅숏은 분기 회고와 따라잡기만 쓴다.
    - `catch_up_snapshots(conn, clock, today) -> int` — 지난 분기 스냅숏이 없고 그 분기 끝 이전 측정값이 있으면 `write_snapshot(prev, as_of=분기 끝)`. 첫 기준선이 지난 분기에 쓰였어도(분기 중간 값) 분기 회고 스냅숏이 없었으면 분기 끝 값으로 덮어쓴다: 판정은 `taken_at`의 현지 날짜가 분기 마지막 날보다 이르고 회고 표시(`inputs_json.source == "review"`)가 없을 때. `inputs_json`에 `source`(`first`·`review`·`catch_up`)를 둔다.
  - 모든 쓰기는 부르는 쪽 트랜잭션 안(`conn.execute`만).

- [ ] **Step 1: 실패하는 테스트**(고정 자료 값을 쓴다)
  - `test_bench_only_change_is_world`(T5): 같은 값, 기준표만 `income.national` P50을 5000→6000으로 바꾼 사본(tmp 폴더 2027.toml) → `me == 0`, `world < 0`, `delta == world`.
  - `test_input_only_change_is_me`(T5): 같은 기준표, 연봉만 6,200만 → 4,500만 → `world == 0`, `me == delta < 0`.
  - `test_both_sum`(T5): 기준표와 연봉을 함께 바꾸면 `world`는 `test_bench_only_change_is_world`의 값과 같고 `me`는 "새 기준표에서 연봉만 바꾼 차이"와 같다(각각 따로 계산한 기대값과 1e-9).
  - `test_age_band_move_is_world`(T5): 고정 자료에서 왕복오래달리기만 46(1992년생). 앞 날 2027-06-01(34세, 30_34 → 75점), 지금 2028-06-01(35세, 35_39 → 90점) → 건강 영역 `world == 0.6 × 0.20 × 15 = 1.8`, `me == 0`.
  - `test_marks_thresholds`(T6): `me = −4.9` → 빈 목록, `−5` → `[{"kind": "me", "delta": -5}]`와 `debuff True`, `world = −6`, `me = 0` → `[{"kind": "world", "delta": -6}]`, `debuff False`.
  - `test_innate_not_in_area_drift`(T6): 키만 바꿔도 6영역 drift가 모두 0 또는 None.
  - `test_snapshot_if_first_once`: 두 번 불러도 분기 줄 수 같음(축 수 × 2 집단 이하).
  - `test_catch_up_previous_quarter`: Q3에 측정값, 스냅숏 없음, 오늘 2026-10-02 → `2026-Q3` 줄이 생기고 `taken_at`의 현지 날짜 2026-09-30.
  - `test_drift_survives_deleted_snapshot_measure`: 스냅숏 뒤 그 측정값을 지움 → `area_drifts`가 예외 없이 계산되고 그 영역 `me == 0`.
  - `test_filling_blank_is_not_my_drop`: 스냅숏 때 저축 지표 없음(가정 25), 뒤에 저축률 5%를 넣음 → 경제 영역 `me == 0`, `debuff False`.
  - `test_catch_up_replaces_mid_quarter_first`: 첫 기준선 2026-08-10, 회고 없음, 9월에 값 바뀜, 오늘 2026-10-02 → `2026-Q3` 스냅숏 `taken_at` 2026-09-30, 값은 9월 값.
  - `test_derived_exercise_from_workout_logs`: 지난 28일 운동 기록 8일 → `exercise_days_week == 2.0`(수동 값 0.5보다 우선).
- [ ] **Step 2:** FAIL 확인.
- [ ] **Step 3:** 구현.
- [ ] **Step 4:** PASS, 전체 PASS.
- [ ] **Step 5:** `git commit -m "feat(sp13): 하락 이유 나누기와 분기 스냅숏"`

### Task 5: 도구·동작·확인 카드·경험치 (SP13-05)

**Files:**
- Create: `src/my_planner/tools/standing.py`(`StandingTools` mixin)
- Modify: `src/my_planner/tools/core.py`(mixin, `standing: StandingRepo | None = None` 인자), `src/my_planner/tools/actions.py`(`ACTIONS`), `src/my_planner/tools/activity.py`(되돌리기 처리, 대상 `measure:<id>`), `src/my_planner/tools/mcp_adapter.py`(`propose_measures`를 `APP_ONLY_TOOLS`에, 설명·스키마), `src/my_planner/tools/ui.py`(`ui_measure_confirm` 하네스 조각), `src/my_planner/harness/dispatcher.py`(`Outbound.measure_cards`, `_outbound`), `src/my_planner/harness/stream.py`(`harness_cards`가 확인 카드 다음에 `("h_measure", "ui_measure_confirm", props, {"ok": True})`), `src/my_planner/harness/prompts/channel_app.md`(측정값 절, 앱 전용 도구라서), `src/my_planner/harness/prompts/system.md`(금지어 블록에 셋), `src/my_planner/status/xp.py`(`XP_STANDING = 20`, `LABEL_STANDING = "측정값 기록"`), `src/my_planner/tools/core.py`의 `record_area_scores`(스냅숏, 아래), `src/my_planner/loop/runner.py`·`app.py`(하루 한 번 `standing_daily`), 저장소를 넘기는 곳(`app.py`의 `Tools(...)`).
- Test: `tests/test_standing_tools.py`, `tests/test_api_actions.py`(더함), `tests/test_prompts.py`(`channel_app.md` 모양을 지키는 테스트 `test_channel_app_is_spec_text`가 있으면 새 절을 그 기대 글에 더한다), `tests/test_write_paths.py`, `tests/test_api_e2e.py`(save_measures 시나리오 하나)

**Interfaces:**
- Consumes: Task 1 `validate`, `StandingRepo`; Task 4 `snapshot_if_first`, `write_snapshot`, `catch_up_snapshots`, `current`.
- Produces:
  - `ui_measure_confirm` props 모델: `rows: list[{metric: str, label: str, value: float | str, unit: str | None, measured_on: "YYYY-MM-DD"}]`(1~30), `source_kind: Literal["photo", "pdf", "manual"]`, `source_ref: str | None`(`photo:<id>`만). origin `harness`.
  - 두뇌 도구 `propose_measures(rows, source_kind, source_ref=None)`: 줄마다 `validate`. 하나라도 틀리면 저장·카드 없이 `{"ok": False, "errors": [{"index", "message"}]}`. 다 맞으면 `ToolEvent("measures_proposed", None, {"rows": [...], "source_kind", "source_ref"})`, 결과 `{"ok": True, "card": True}`. 쓰지 않는다. `face_rating`은 `source_kind`와 상관없이 저장 때 `reliability = "low"`.
  - `/actions save_measures {rows, source_kind, source_ref}`(공개, 앱): 다시 검사(틀리면 `422 rejected`), 한 트랜잭션에 줄들 저장 + `snapshot_if_first` + X14(`grant(source_kind="standing", source_ref=f"standing:{분기}", amount=20, label="측정값 기록", gain=ctx.xp)`), 활동 `kind="measures_saved"`, `target=None`, `targets=["measure:<id>", …]`, `risk="low"`, `undo={"measure_ids": [...]}`, `summary="측정값 {n}개 저장"`(값 없음). 응답 확인 문구 `"✓ 측정값 {n}개 저장 · {영역 라벨} 위치 {이전}→{새}"`: 가장 많이 바뀐 영역 하나(바뀐 영역이 없거나 이전이 없으면 `"✓ 측정값 {n}개 저장"`).
  - `/actions delete_measure {id}`(공개): `deleted_at`, 활동 `measure_deleted`, `undo={"measure_id": id}`, `summary="측정값 지움"`.
  - 되돌리기: `measures_saved` → 그 줄들 `deleted_at`; `measure_deleted` → `restore`. 경험치는 그대로(U6). 그 저장이 첫 기준선을 썼으면(`undo_json.baseline_period`) 그 스냅숏 줄도 지운다(다음 저장이 다시 기준선을 쓴다).
  - 내부 동작 `standing_daily`(`public=False`): `catch_up_snapshots`. 하루 한 번 작업 `standing_daily(target)`를 `runner.py`에 `memos_daily`와 같은 모양으로, `app.py`에 등록.
  - `record_area_scores`(`tools/core.py`)가 적용되면 같은 트랜잭션에서: 그 기간이 지금 분기면 `write_snapshot(그 분기)`(`source=review`), 지난 분기면 `write_snapshot(그 분기, as_of=분기 끝)`. 측정값이 없으면 0줄.
  - `channel_app.md` 측정값 절(문구는 이대로). 같은 파일의 "사진만 오면 create_memo" 줄 바로 앞에 두고, 그 줄에 "(결과지 사진은 아래 측정값 절이 먼저)"를 붙인다:
    ```
    ## 측정값 (상태창 객관적 위치)
    - 인바디·검진표·급여명세·자산 화면 같은 결과지 사진이 오거나, 사용자가 "연봉 5,500이야"처럼 숫자를 말하면 propose_measures로 확인 카드를 냅니다. 묻지 않고 저장하는 길은 없습니다. 카드를 냈으면 "카드에서 확인하고 저장해 주세요."라고만 말합니다.
    - 금액은 원 단위입니다(5,500만 원 = 55000000). 측정일은 결과지의 날짜이고 올린 날이 아닙니다.
    - 얼굴 사진으로 face_rating을 낼 때는 카드 뒤에 "얼굴 점수는 조명·각도·취향에 따라 ±10 흔들려요."를 붙이고, 같은 조건 사진끼리의 변화만 말합니다.
    - 위치 점수는 사람의 가치가 아니라 이번 조건의 측정값이라고 말합니다. 순위나 남과 견주는 표현을 쓰지 않습니다.
    ```

- [ ] **Step 1: 실패하는 테스트**
  - `test_propose_measures_validates`: 틀린 줄 하나 → `ok False`, 이벤트 없음. 맞는 줄 → `measures_proposed` 이벤트, 저장소 줄 수 0.
  - `test_outbound_measure_card`: `measures_proposed` 이벤트 → `harness_cards`에 `ui_measure_confirm` 하나, props가 스키마 검사(`validate_props`) 통과.
  - `test_save_measures_low_risk_undoable`(T8): `/actions save_measures` → 200, 줄 저장, 활동 `risk == "low"`, `summary`·`undo_json`에 값 숫자가 없다(문자열에 `55000000` 없음), 되돌리기 → 줄들 지워짐, 원장 그대로.
  - `test_save_measures_rejects_bad_row`: 범위 밖 한 줄 → `422 rejected`, 아무것도 저장 안 됨.
  - `test_x14_once_per_quarter`(T10): 같은 분기 두 번 저장 → X14 한 줄, 다음 분기 저장 → 두 줄, 측정값을 지워도 그대로.
  - `test_first_save_writes_baseline_snapshot`: 저장 뒤 지금 분기 스냅숏 줄 > 0.
  - `test_record_area_scores_quarter_writes_snapshot`: 측정값 있음 + 분기 영역 점수 기록 → 그 분기 스냅숏 `taken_at`이 갱신.
  - `test_delete_measure_and_undo`.
  - `test_face_rating_saved_low`.
  - `test_banned_words_include_standing`(T11): `tools.ui.banned_words()`에 `등수`, `패배`, `뒤처짐`, `실패`가 있고, `channel_app.md`·카드·확인 문구에 금지어가 없다.
  - `test_undo_first_save_removes_baseline`.
  - `test_record_past_quarter_scores_snapshot_as_of_end`.
- [ ] **Step 2:** FAIL 확인.
- [ ] **Step 3:** 구현.
- [ ] **Step 4:** `tests/test_write_paths.py`: `TOOLS`에 `my_planner.tools.standing`, `ALLOWED`에 `standing_measures: {*TOOLS, "my_planner.standing.importer"}`, `standing_snapshots: {*TOOLS, "my_planner.standing.service", "my_planner.standing.importer"}`, `status_xp_ledger`에 `my_planner.standing.importer`를 더하고, e2e 시나리오에 save_measures가 들어가 실제로 잡히는지 본다. 그 뒤 PASS, 전체 PASS.
- [ ] **Step 5:** `git commit -m "feat(sp13): 측정값 확인 카드, save_measures, X14"`

### Task 6: API `GET /standing`, `GET /standing/measures`, `/status` 더하기, 대시보드 403 (SP13-06)

**Files:**
- Create: `src/my_planner/api/standing.py`
- Modify: `src/my_planner/api/server.py`(`READ_ROUTES`), `src/my_planner/api/devices.py`(`DeviceTokens`가 기기 종류도 안다), `src/my_planner/api/read.py`(`get_status`), `src/my_planner/status/snapshot.py`(`status_snapshot(..., standing: dict | None = None)`), `src/my_planner/api/models.py`(모델, `schema_bundle`)
- Test: `tests/test_api_standing.py`, `tests/test_api_curve_status.py`(더함), `tests/test_api_devices.py`(더함)

**Interfaces:**
- Consumes: Task 4 `current`, `area_drifts`, `marks`, `debuff`; Task 1 `StandingRepo.active`, `METRICS`.
- Produces:
  - `DeviceTokens.add(hash_: str, device_id: int, client: str)`, `DeviceTokens.client(device_id: int) -> str | None`(`load`가 `DevicesRepo.active()`의 `client`를 함께 담는다). `api/standing.py`의 `dashboard_device(request) -> bool`(기기 토큰이고 그 기기의 `client == "dashboard"`).
  - `GET /standing` 본문(모델 `Standing`):
    ```
    {profile_missing: bool,
     bench: {version, effective_from},
     axes: [{axis, label, area: str|null, innate: bool,
             national: AxisScoreOut|null, peer: AxisScoreOut|null}],          # AXES 순서
     areas: {<6영역>: {score: int|null, peer_score: int|null, reliability: str|null,
                       drift: [{kind: "me"|"world", delta: int}], debuff: bool,
                       recovery_quest: str|null, hint: str|null}},
     innate: [{axis, label, score: int|null}],
     markets: {marriage: {national: int|null, peer: int|null, excluded: [axis]},
               career: {…}},
     measures_count: int}
    AxisScoreOut = {score, low, high, reliability, estimate, inputs: [metric], missing: [metric], assumed: [str],
                    measured_on: "YYYY-MM-DD"|null}   # 쓴 측정값 가운데 가장 이른 측정일
    ```
    - `areas[*].hint`: 위치가 없을 때만. `quality_of_life` = "삶의 질은 객관적 기준표가 없어요. 만족 점수와 생활 지표(잠, 걸음, 쉬는 저녁)로 봐요.", 태어난 해 없음 = "태어난 해를 넣으면 생겨요.", 그 밖 = `"{그 영역 축의 첫 빈 지표 라벨}을 넣으면 생겨요."`(`을/를`은 받침으로).
    - 영역의 `reliability`는 그 영역 축들 가운데 가장 낮은 것. `recovery_quest`는 `debuff`일 때 `curve.area_default(영역) or DEFAULT_RECOVERY_QUESTS[영역]`(지금 만족 디버프와 같은 순서에서 그 분기 점수의 퀘스트만 뺀 것, SP15 전).
  - `GET /standing/measures`: `{measures: [{id, metric, label, value_num, value_text, unit, measured_on, source_kind, reliability, created_at}]}` — `StandingRepo.active()` 순서.
  - `GET /status`: 대시보드 기기가 아니면 `stats[i].standing = {score, peer_score, reliability, drift, debuff, recovery_quest, hint}`(그 영역의 `areas` 값과 같다)와 최상위 `innate`를 더한다. 대시보드 기기면 키를 넣지 않는다(`dump`가 `exclude_unset`이라 모델 필드는 `None` 기본값으로 둔다).
  - 대시보드 기기의 `/standing`, `/standing/measures` → `403 {"error": {"code": "forbidden", "message": "이 화면에서는 볼 수 없어요."}}`(지금 `error_response` 모양).
- [ ] **Step 1: 실패하는 테스트**
  - `test_api_standing.py::test_standing_shape_with_sample`: 고정 자료를 저장소에 넣고 `GET /standing` → 200, `axes` 9개 순서, `areas.health.score == round_half_up(0.6×health.raw + 0.4×looks.raw)`(= 70), `innate` 셋, `markets.marriage.national == 65`.
  - `test_api_standing.py::test_dashboard_device_forbidden`(T7): `client='dashboard'` 기기 토큰 → `/standing`·`/standing/measures` 403. `client='app'` 기기와 API 토큰 → 200.
  - `test_api_curve_status.py::test_status_standing_only_for_app`(T7): 대시보드 기기 → `stats[0]`에 `"standing"` 키 없음, 최상위 `"innate"` 없음. 앱 기기 → 있음.
  - `test_api_standing.py::test_empty_standing`: 측정값 0 → 200, 모든 영역 `score` null과 `hint` 있음, `measures_count == 0`.
  - `test_api_standing.py::test_logs_have_no_values`: 요청 뒤 로그 기록(`caplog`)에 측정값 숫자 문자열이 없다.
  - `test_api_schema.py`가 새 모델을 묶음에 담는지(지금 테스트 방식대로).
- [ ] **Step 2:** FAIL 확인.
- [ ] **Step 3:** 구현. 읽기는 `read_handler`(읽기 전용 연결).
- [ ] **Step 4:** `cd web/app && npm run gen:types`, `cd web/dashboard && npm run gen:types`(대시보드 스키마 일치 테스트 `tests/test_dashboard_fixtures.py::test_schema_json_matches_bundle`), 그리고 `python -m pytest tests/test_dashboard_fixtures.py --update-dashboard-fixtures`. 대시보드 고정 자료는 지금처럼 API 토큰으로 기록한다(새 키는 선택 필드라 대시보드는 쓰지 않는다. 대시보드 기기에서 키가 없는 것은 T7이 지킨다). 그 뒤 PASS, 전체 PASS.
- [ ] **Step 5:** `git commit -m "feat(sp13): GET /standing, /status 위치, 대시보드 403"`

### Task 7: 가져오기 명령 `standing import` (SP13-07)

**Files:**
- Modify: `src/my_planner/cli.py`(`standing` 하위 명령, `USAGE`)
- Create: `src/my_planner/standing/importer.py`
- Test: `tests/test_cli.py`(더함), `tests/test_standing_import.py`

**Interfaces:**
- Produces:
  - `python -m my_planner standing import <파일> [--dry-run]`. 루트는 `seed-life`와 같다(`resolve_root()`). BE가 돌고 있으면 거절(코드 3, `seed-life`가 쓰는 검사 그대로).
  - 파일 모양: `{"version": 1, "measures": [{"metric": str, "value": number|string, "measured_on": "YYYY-MM-DD", "reliability"?: "high"|"mid"|"low"}]}`. `version`이 1이 아니거나 JSON 객체가 아니면 코드 6.
  - `run_import(root: Path, file: Path, *, dry_run: bool, out: TextIO) -> int`: 파일은 `encoding="utf-8"`로 읽는다. 줄마다 `validate`. `face_rating`은 파일 값과 상관없이 `reliability="low"`. 하나라도 틀리면 아무것도 쓰지 않고 `invalid: <index> <지표 이름>`(값 없이) 줄들과 코드 5. 같은 지표·측정일의 `import` 줄이 있으면 건너뜀(`has_import`, `cert`는 `value_text`까지). 쓰기는 한 트랜잭션: 줄들 + `snapshot_if_first` + X14. 출력 한 줄 `imported: {n}, skipped: {m}`. `--dry-run`은 쓰지 않고 같은 줄.
  - 로그·출력에 값이 없다.
- [ ] **Step 1: 실패하는 테스트**
  - `test_import_twice_same_rows`(T9): 고정 자료 두 번 → 처음 `imported: 43, skipped: 0`(고정 자료의 줄 수, `cert` 둘 포함), 두 번째 `imported: 0, skipped: 43`, 표 줄 수 같음.
  - `test_import_invalid_writes_nothing`: 한 줄 범위 밖 → 코드 5, 줄 0, 출력에 값 숫자 없음.
  - `test_import_grants_x14_and_snapshot`.
  - `test_import_dry_run`.
- [ ] **Step 2:** FAIL 확인.
- [ ] **Step 3:** 구현.
- [ ] **Step 4:** PASS, 전체 PASS.
- [ ] **Step 5:** `git commit -m "feat(sp13): standing import 명령"`

### Task 8: 운영 앱 — 상태창 두 숫자, 타고난 스탯, 상세 화면, 확인 카드 (SP13-08)

**Files:**
- Modify: `web/app/src/api/schema.json`, `web/app/src/api/types.gen.ts`(`npm run gen:types`), `web/app/src/api/actions.ts`(동작 이름에 `save_measures`·`delete_measure`), `web/app/src/screens/Status.tsx`·`Status.module.css`·`Status.test.tsx`, `web/app/src/lib/copy.ts`, `web/app/scripts/lint-copy.mjs`(금지어 넷), `web/app/src/ui/registry.tsx`
- Create: `web/app/src/pages/status/standing.tsx`, `web/app/src/screens/Standing.tsx`·`Standing.module.css`·`Standing.test.tsx`, `web/app/src/ui/components/MeasureConfirm.tsx`·`MeasureConfirm.test.tsx`, `web/app/e2e/standing.spec.ts`
- 픽스처: 앱 테스트가 쓰는 API 고정 응답(지금 `fixtures` 방식)에 `GET /standing`, `GET /standing/measures`, `/status`의 `standing`·`innate`

**Interfaces:**
- Consumes: Task 6 모델(생성 타입 `Standing`, `StandingMeasures`, `StatusStat.standing`, `Status.innate`), Task 5 `ui_measure_confirm`, `/actions save_measures`·`delete_measure`, 되돌리기(지금 토스트 방식).
- Produces(화면 규칙, 스펙 10장):
  - 상태창 영역 줄: 지금 줄 오른쪽 값 옆에 "만족 {n}"과 "위치 {n}"(`stats[i].standing`이 있을 때만. 키가 없으면 지금 화면 그대로). peer가 다르면 "위치 59 (IT 27)". 신뢰도 `low`면 "· 낮음". `drift`마다 "▲3 내 변화" / "▼4 내 변화" / "▼4 세상 변화"(세상 변화는 회색 `--muted` 토큰). `debuff`면 지금 디버프 모양에 "위치 하락" 문구와 `recovery_quest`. 위치가 없으면 "위치 —"이고 누르면 `hint` 한 줄이 펼쳐진다.
  - 영역 목록 아래 묶음 "타고난 스탯": "키 83 · 학벌 76 · 집안 66"(없는 것은 "—"), 설명 "바꿀 수 없는 출발점이에요. 다시 채점하지 않아요."
  - 묶음 아래 줄 "객관적 위치 자세히 ›" → `/status/standing/`.
  - 상세 화면: 맨 위 시장 점수 두 개(두 비교 집단, 결혼시장 아래 "나이·성격·가치관이 빠진 서류 스펙 점수예요.", `excluded`가 있으면 "빠짐: {축 이름들}"), 9축 레이더(SVG, 두 집단 겹침, CSP 때문에 인라인 style 없이 그리기 속성만 — `Status.tsx`의 XP 막대와 같은 방식), 축별 막대(점수, 오차 띠 `low~high`, 신뢰도, `missing`이 있으면 "미입력: {라벨들}"과 "빈 항목은 가정값으로 계산했어요.", 측정일), 맨 아래 "측정값" 목록(지표 라벨, 값+단위, 측정일, 출처) — 각 줄의 지우기 버튼 → `delete_measure` → 되돌리기 토스트. 오프라인이면 상태창과 같은 문구.
  - 금액 표시: `salary_krw`·`*_krw`는 "5,500만 원" 형식(만 원 단위 반올림).
  - `MeasureConfirm`(`ui_measure_confirm`): 줄마다 라벨, 고칠 수 있는 값 입력(숫자 지표는 숫자 입력, 열거는 고르기), 측정일, 줄 빼기. 버튼 "저장" → `save_measures`(남은 줄만), 성공하면 확인 문구를 보이고 카드가 읽기 전용이 된다(지금 `Confirm` 카드의 처리 뒤 모양과 같게). 줄이 0개면 "저장"이 꺼진다. 얼굴 점수 줄이 있으면 "얼굴 점수는 조명·각도·취향에 따라 ±10 흔들려요."를 카드 아래에 늘 보인다.
  - 금지어(`lint:copy`): `연속`, `스트릭`, `달성률`, `등수`, `패배`, `뒤처짐`, `실패`. "상위", "%"를 위치 문구에 쓰지 않는다.
- [ ] **Step 1: 실패하는 테스트**(vitest + Testing Library)
  - `Status.test.tsx`: `standing`이 있는 고정 응답 → "만족 7", "위치 59 (IT 27)", "▼6 세상 변화", 타고난 스탯 줄, 자세히 링크. `standing`이 없는 응답(대시보드와 같은 모양) → 지금 화면 그대로(기존 테스트 통과).
  - `Status.test.tsx`: 위치 없는 영역을 누르면 `hint`가 보인다.
  - `Standing.test.tsx`: 시장 두 개, 축 9개 막대, "미입력" 줄, 측정값 목록의 지우기 → `delete_measure` 호출.
  - `MeasureConfirm.test.tsx`: 값을 고치고 한 줄을 빼고 저장 → `save_measures`의 `rows`가 고친 값과 남은 줄. 줄 0개면 저장 꺼짐. 얼굴 점수 안내.
  - `e2e/standing.spec.ts`(T12): 상태창 → 자세히 → 상세 화면이 열리고 레이더 SVG가 있다(고정 응답 서버, 지금 e2e 방식).
- [ ] **Step 2:** `cd web/app && npm test` → FAIL.
- [ ] **Step 3:** 구현.
- [ ] **Step 4:** `npm test && npm run typecheck && npm run lint:copy && npm run e2e && npm run size` 모두 통과(첫 로드 예산을 넘지 않는다. 상세 화면은 따로 된 페이지라 첫 로드에 들지 않는다).
- [ ] **Step 5:** `git commit -m "feat(sp13): 앱 상태창 위치, 타고난 스탯, 상세 화면, 측정값 카드"`

> 범위 밖(SP13에서 만들지 않음): 스펙 13장의 "해마다 11월 기준표 갱신 확인" 제안. 첫 갱신이 2027-11이라 SP15 이후 작업으로 둔다(스펙 v1.3에 적음).

### Task 9: 마무리 — 문서와 노트북 확인 목록 (SP13-09)

**Files:**
- Create: `docs/sp13/laptop-checklist.md`(저장소 쪽은 개인 값 없이 절차만)
- Modify: `GLOSSARY.md`("디버프" 정의에 "위치 하락: 내 변화 −5 이하" 한 줄), 스펙(v1.3 정정은 이 계획을 올리는 PR이 이미 한다. 구현 중 다른 점이 더 생기면 그때 v1.4 한 줄)

- [ ] **Step 1:** 노트북 확인 목록(수용 기준 3, 8):
  1. BE 업데이트·재시작 뒤 `python -m my_planner standing import <프로젝트 폴더의 standing-2026-11-01.json>` (BE를 멈추고) → `imported: n, skipped: 0`.
  2. 앱 상태창에 영역 줄 두 숫자, 타고난 스탯, 자세히 화면이 보인다.
  3. 리포트 v2 점수와 ±3 안인지 본다. 다른 축은 이 계획의 "알려진 차이" 표와 맞는지 본다.
  4. 채팅에 인바디 사진 → 확인 카드 → 값 하나 고쳐 저장 → 건강 위치가 바뀐다 → 되돌리기.
  5. 대시보드 상태창이 지금과 같다(위치가 없다). 대시보드가 연결 코드(기기 종류 dashboard)로 붙어 있는지 기기 목록에서 확인한다. API 토큰으로 붙어 있으면 위치가 보이므로 연결 코드로 다시 붙인다.
- [ ] **Step 2:** 저장소의 확인 목록에는 "리포트 v2와 다를 수 있는 축: 자격, 집안, 경제력(IT), 직업"처럼 축 이름만 적는다. 이유와 값은 프로젝트 폴더(`social-level/`)의 노트에만 둔다.
- [ ] **Step 3:** `python -m pytest -q`, 앱 검사 모두 통과.
- [ ] **Step 4:** `git commit -m "docs(sp13): 노트북 확인 목록"`
