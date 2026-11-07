# SP16 애플 건강앱 연동 상세 설계 (추가 기능)

- 상태: 초안 v0.2 (2026-11-07, doc-reviewer 1차 반영). 5장 Q1·Q2는 Dahun 답을 기다린다. 나머지는 비서 추천으로 채우고 15장에 모았다
- 작성일: 2026-11-07
- 상위 문서: [마스터 설계](2026-10-23-my-planner-master-design.md), [SP8 상태창 기록](2026-10-25-sp8-status-records-history-design.md) (몸 기록, `BODY_TOKEN`, 건강 보너스), [SP12 운동메이트](2026-10-31-sp12-workout-mate-design.md) (운동 기록, 앞머리, 메이트 도구), [SP13 객관적 위치](2026-11-01-sp13-objective-standing-design.md) (측정값), [SP3-4 스펙](2026-10-24-sp3-4-life-curve-dashboard-design.md) (HTTP API 계약 정본)
- 용어: [`GLOSSARY.md`](../../../GLOSSARY.md) (이번에 "건강앱 운동", "건강앱 보내기", "건강앱 이력 가져오기" 추가, "단축어 토큰" 뜻 넓힘). 결정 기록: [ADR 0023](../../adr/0023-apple-health-via-export-app-and-history-file.md) 추가
- 범위: 아이폰 건강앱(HealthKit)에 쌓인 **운동**(워치·다른 앱 기록)을 BE로 가져와 운동메이트가 읽게 한다. 매일 자동으로 받는 길과, 지난 이력을 한 번에 채우는 길 둘. 걸음·잠(SP8 몸 기록)과 몸무게·체지방률(SP13 측정값)도 같은 길로 받을 수 있게 한다. 텔레그램과 대시보드는 건드리지 않는다.

## 1. 목표와 완료 조건

Dahun이 운동메이트에게 "나 운동 뭐 했었어?"라고 물었더니 "기록이 없다"고 했다(2026-11-07). 3장에서 보듯 고장이 아니라, 메이트가 아는 운동이 **메이트 대화에서 말로 남긴 것뿐**이기 때문이다. Dahun은 아이폰 건강앱과 이어서, 이미 폰·워치에 쌓인 운동을 메이트가 알기를 바란다.

**완료 조건 (수용 기준)**

1. 아이폰의 내보내기 앱(4장 안 A)이 정해진 주기로 `POST /api/v1/health/export`에 JSON을 보내면, 그 안의 운동이 `health_workouts`에 저장된다. 같은 운동을 다시 보내도 한 줄이다(6.2 같은 운동 규칙).
2. 오늘 아침 워치로 45분 근력 운동을 했고 그 뒤 한 번 보내졌다면, 메이트 새 대화의 앞머리 `## 최근 기록`에 `- 11-07 (토) 건강앱 · 근력 운동 45분 · 320kcal · 평균 심박 128 (h#12)` 같은 줄이 보이고, "오늘 운동 뭐 했지?"에 메이트가 이 줄을 근거로 답한다.
3. `python -m my_planner health import <export.zip>`(BE를 멈춘 상태)으로 건강앱 "모든 건강 데이터 내보내기" 파일을 읽으면, 지난 운동이 모두 `health_workouts`에 들어가고, 출력은 개수뿐이다(`운동 412개 가져옴, 3개 이미 있음, 9개 건너뜀`, 8.1). 다시 돌려도 새로 늘지 않는다.
4. "지난달에 운동 몇 번 했어?", "작년 여름엔 뭐 했어?"에 메이트가 `list_workouts`로 기간을 넓혀 찾아 답한다. 찾아본 기간에 아무것도 없을 때만 "기록이 없다"고 하고, 건강앱에서 한 번도 받은 적이 없으면 연결 안내 한 줄을 덧붙인다(9.3).
5. 내보내기 앱이 걸음 수·수면을 함께 보내면 `body_days`가 SP8 규칙(지난 14일, 덮어쓰기)대로 채워져, 지금 단축어를 꺼도 상태창 몸 기록 줄이 그대로다(7.4).
6. 몸무게·체지방률을 보내면 SP13 측정값(`standing_measures`, `source_kind = 'shortcut'`)에 지표마다 날마다 많아야 한 줄로 들어간다(7.5).
7. 건강앱 운동이 있는 날은 건강 활동 보너스 0.5가 붙는다(운동 기록과 같은 날이면 합쳐서 0.5 한 번). 경험치 X13은 받은 날 기준 지난 7일 안의 운동에만 붙고, 이력 가져오기로 들어온 옛 운동에는 붙지 않는다(10장).
8. 경로(GPS), 심박 시계열, 기기 이름은 BE 어디에도 저장되지 않고 로그에는 개수만 남는다(12장). `API_TOKEN`으로는 이 경로에 쓸 수 없다.
9. 13장의 자동 테스트가 모두 통과한다.

## 2. 범위

| 포함 | 제외 (언제) |
|---|---|
| 건강앱 운동(종류, 시작·끝, 시간, 활동 칼로리, 거리, 평균·최대 심박, 실내·실외) 받기와 저장 | 세트·횟수·무게: 건강앱에 없다. 메이트 대화 운동 기록(SP12)이 계속 맡는다 |
| 내보내기 앱 → BE 자동 전송 경로(`POST /health/export`) | 네이티브 iOS 앱, HealthKit 직접 읽기 (하지 않음. 앱은 PWA이고 개발자 계정이 없다. SP5 결정) |
| 건강앱 내보내기 파일(export.zip / export.xml)로 지난 이력 한 번에 채우기(CLI) | 앱에서 내보내기 파일 올리기 (나중. 파일이 수백 MB가 될 수 있다) |
| 같은 경로로 걸음·수면 → 몸 기록, 몸무게·체지방률 → 측정값 | 심박 변이, 안정 시 심박, VO2max, 식단·칼로리 섭취 (필요해지면. 15장 D7) |
| 메이트 앞머리·`list_workouts`에 건강앱 운동 합치기, 지시문 고침 | 비서가 건강앱 운동 내용 읽기 (하지 않음. SP12 D7 그대로) |
| 운동 화면 최근 기록에 건강앱 운동 줄, 설정에 "건강앱 마지막 받음" 한 줄 | 대시보드 운동 화면 (나중) |
| 건강 활동 보너스·경험치 X13 연결 | 운동 칼로리·거리로 따로 주는 보상 (하지 않음. ADR 0006) |

## 3. 진단: 메이트가 "기록 없음"이라고 한 이유

코드를 따라가 본 결과(2026-11-07, develop `a93d70b`):

1. 메이트가 아는 운동은 `workout_logs`뿐이다. 이 표는 메이트 대화에서 Dahun이 한 운동을 말했을 때 `log_workout`이 쓸 때만 채워진다(SP12 8장). 건강앱·워치 기록은 BE에 들어오는 길이 없다. SP8 몸 기록 단축어는 걸음과 잠 두 값만 보낸다(SP8 2장 "심박, 체중, 운동 기록 등 다른 건강 값: 하지 않음").
2. 말로 남길 수 있는 기록은 오늘 포함 7일 안이다(`LOG_BACKDATE_DAYS = 6`). 그래서 이전 운동은 지금 구조로는 채울 수도 없다.
3. 새 대화 앞머리는 최근 14일·8개만 넣고(`mate_context.RECENT_LOG_DAYS`), 비어 있으면 "아직 없음"이라고 쓴다. 지시문은 "지난 기록은 `list_workouts`로 찾는다"고 하지만, 앞머리가 "아직 없음"이면 두뇌가 도구를 부르지 않고 그대로 "기록이 없다"고 답하기 쉽다.
4. 도구 연결(`app.py` → `WorkoutRepo` → `PlannerTools.workout`)과 `MATE_TOOLS`의 `list_workouts`는 정상이다.

결론: 1·2가 원인이고 3이 답을 더 단정적으로 만든다. 이 설계는 1·2를 건강앱 연동으로, 3을 지시문·앞머리 고침(9장)으로 푼다.

확인할 것: Dahun이 메이트에게 운동을 말로 남긴 적이 있는데도 "없다"고 했다면 다른 버그다. 그때는 노트북 DB에서 `SELECT count(*) FROM workout_logs WHERE deleted_at IS NULL`을 확인한다(14.1 스파이크 S0).

## 4. 접근안과 선택

PWA는 HealthKit을 읽을 수 없다(SP8 4장 안 A). 그래서 폰에서 건강 데이터를 꺼내 BE로 보내 줄 무언가가 필요하다.

| 안 | 내용 | 판단 |
|---|---|---|
| **A. 내보내기 앱 "Health Auto Export"의 REST API 자동화 (선택, 매일)** | 앱이 정해진 주기로 고른 지표와 운동을 JSON으로 BE 주소에 POST한다. 운동마다 종류·시간·칼로리·거리·심박 요약이 있다 | **추천**. 운동을 정해진 주기로 보내는 방법 중 확인된 유일한 길. 유료: 자동 전송은 프리미엄(평생 $24.99, 연 $6.99, 월 $1.99, 7일 체험. 2026-11-07 App Store). 백그라운드 전송 빈도와 잠금 화면 동작, 사용자 헤더 지원은 스파이크 S1에서 확인 |
| B. 지금 단축어 늘리기(무료) | 몸 기록 단축어에 운동 읽기를 더한다 | 버림(대안으로 남김). 기본 단축어의 "건강 샘플 찾기"는 운동 유형을 제대로 주지 않는다는 보고가 있고(2024 포럼), 서드파티 동작(Toolbox Pro)이 필요하다. 폰이 잠겨 있으면 "Protected health data is inaccessible"로 실패한다는 보고도 있다(2022). 심박 요약을 얻기 어렵다 |
| **C. 건강앱 "모든 건강 데이터 내보내기" 파일 가져오기 (선택, 한 번)** | 건강앱 › 프로필 › 내보내기로 만든 export.zip을 노트북에서 읽는다 | **추천(A와 함께)**. 지난 이력을 한 번에 채우는 유일한 길. 무료. 파일이 크고(수백 MB~GB) 손으로 옮겨야 해서 매일 쓰기에는 맞지 않는다 |
| D. 다른 서비스 거치기(Strava, Google Fit 등) | 건강앱 → 서비스 → BE가 그 API를 읽는다 | 버림. 데이터가 한 번 더 바깥 서비스로 나가고(P5), 노트북 BE가 외부 OAuth를 들고 있어야 한다 |

선택: **A(매일) + C(한 번)**. 둘 다 같은 저장 규칙(6장)을 쓰고, A가 C를 덮어써도 결과가 같다. A를 쓰지 않기로 하면(5장 Q1) C만으로도 이력은 채워지고, 매일 받는 것만 빠진다.

A가 쓰는 쓰기 경로는 SP8의 **단축어 토큰(`BODY_TOKEN`)**을 그대로 쓴다: "폰이 건강 값을 쓰는 좁은 토큰"으로 뜻을 넓힌다(12장). 새 토큰을 늘리지 않는다.

## 5. Dahun 결정

| # | 질문 | 상태 |
|---|---|---|
| Q1 | 어떤 방식으로 받을까(유료 앱 자동 전송 + 이력 한 번 / 무료 단축어 + 이력 한 번 / 이력 한 번만) | **기다림** (2026-11-07 결정 카드). 이 문서는 추천인 첫째 안으로 쓴다 |
| Q2 | 운동을 무엇으로 기록하나(애플워치 운동 앱 / 다른 앱 / 폰만) | **기다림**. 심박 값이 있을지, 운동 종류가 어떻게 들어올지가 달라진다. 저장 구조는 어느 쪽이든 같다 |
| — | 그 밖의 결정 | 비서 추천으로 채우고 15장에 모은다 |

## 6. 데이터: 건강앱 운동

### 6.1 표 (마이그레이션 `025_health_import.sql`)

```sql
-- 025: 건강앱 운동 (SP16 스펙 6.1). 시각은 UTC ISO 8601, date는 논리적 날짜(04:00 경계).
CREATE TABLE health_workouts (
    id              INTEGER PRIMARY KEY,
    external_id     TEXT NULL,                -- 내보내기 앱이 주는 운동 id(있을 때만). 6.2의 첫 번째 열쇠
    activity        TEXT NOT NULL CHECK (length(activity) BETWEEN 1 AND 60),   -- 정규화한 종류 키(부록 B), 모르는 종류는 'other'
    activity_raw    TEXT NOT NULL CHECK (length(activity_raw) BETWEEN 1 AND 80), -- 받은 그대로의 종류 이름(디버그·재분류용)
    start_at        TEXT NOT NULL,
    end_at          TEXT NOT NULL,
    date            TEXT NOT NULL,            -- start_at의 논리적 날짜
    minutes         INTEGER NOT NULL CHECK (minutes BETWEEN 1 AND 1440),
    energy_kcal     INTEGER NULL CHECK (energy_kcal IS NULL OR energy_kcal BETWEEN 0 AND 10000),
    distance_km     REAL NULL CHECK (distance_km IS NULL OR distance_km BETWEEN 0 AND 500),
    hr_avg          INTEGER NULL CHECK (hr_avg IS NULL OR hr_avg BETWEEN 30 AND 250),
    hr_max          INTEGER NULL CHECK (hr_max IS NULL OR hr_max BETWEEN 30 AND 250),
    xp_eligible     INTEGER NOT NULL DEFAULT 0 CHECK (xp_eligible IN (0, 1)),  -- 10장: 내보내기 앱으로 7일 안에 받은 적 있음
    indoor          INTEGER NULL CHECK (indoor IS NULL OR indoor IN (0, 1)),
    source          TEXT NOT NULL CHECK (source IN ('export_app', 'history_file')),
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    hidden_at       TEXT NULL,                -- 앱에서 숨김(지우기 대신, 6.3)
    CHECK (end_at > start_at),
    CHECK (hr_avg IS NULL OR hr_max IS NULL OR hr_max >= hr_avg)
);
CREATE INDEX idx_health_workouts_date ON health_workouts (date) WHERE hidden_at IS NULL;
CREATE INDEX idx_health_workouts_start ON health_workouts (activity, start_at);
CREATE UNIQUE INDEX idx_health_workouts_ext ON health_workouts (external_id) WHERE external_id IS NOT NULL;

CREATE TABLE health_sync (
    id              INTEGER PRIMARY KEY CHECK (id = 1),   -- 한 줄뿐
    last_received_at TEXT NULL,               -- 마지막으로 내보내기 앱 요청을 받아 저장한 시각
    last_import_at   TEXT NULL,               -- 마지막 이력 가져오기 시각
    activity_map_version INTEGER NOT NULL DEFAULT 0   -- 부록 B 매핑 버전(6.4)
);
INSERT INTO health_sync (id) VALUES (1);
```

`workout_logs`(SP12)와 **표를 나눈다**. 까닭: 건강앱 운동에는 세트·횟수·무게가 없고 날짜 제한(7일)과 경험치 규칙이 다르며, 같은 운동을 여러 번 받아 덮어써야 한다. 두 표를 합쳐 보이는 일은 읽는 쪽(9장, 11장)이 한다.

경로·심박 시계열·기기 이름·메타데이터 원문은 칸이 없다. 받아도 버린다(12장).

### 6.2 같은 운동 규칙

- **분**: `minutes` = 받은 길이(`duration` 초, 내보내기 파일은 `duration`+`durationUnit`)를 60으로 나눠 **버림**한다. 길이가 없으면 `end_at − start_at`을 같은 방식으로. 1 미만이면 그 운동을 건너뛴다. 예: 2730초 → 45분.
- **같은 운동 찾기** (`HealthRepo.upsert`, 이 순서로 처음 맞는 줄 하나):
  1. 들어온 운동에 `external_id`가 있고 같은 `external_id` 줄이 있으면 그 줄.
  2. 같은 `activity`이고 `start_at`이 ±60초 안이고 `minutes`가 ±1 안인 줄(가장 가까운 시작).
  3. 없으면 새 줄.
- 까닭: 내보내기 파일(C)에는 운동 id가 없고, 내보내기 앱(A)과 파일은 초 단위·반올림이 다를 수 있다. 분으로 자른 열쇠는 09:12:59와 09:13:00처럼 경계에서 갈리므로 범위로 찾는다.
- 찾은 줄이 있으면 **고친다**: 비어 있던 값만 채우고, 들어온 값이 있으면 들어온 값으로 바꾼다. `external_id`가 비어 있었으면 채운다. `source`는 처음 값을 둔다. `hidden_at`은 건드리지 않는다(숨긴 운동이 다시 나타나지 않는다).
- 같은 시각에 다른 앱 두 개가 같은 운동을 기록한 경우(워치 + 다른 앱): 종류가 다르거나 길이가 1분 넘게 다르면 두 줄이 된다. v1은 그대로 두고 운동 화면에서 숨기게 한다(6.3). 실제로 자주 생기면 나중에 규칙을 넓힌다(15장 D5).

### 6.3 숨기기

- 운동 화면에서 건강앱 운동 줄을 숨길 수 있다(`/actions` `hide_health_workout {id}`, 되돌리기 있음). 지우지 않는 까닭: 다음 전송에서 같은 운동이 다시 들어오므로, 지우면 되살아난다.
- 숨긴 운동은 앞머리·`list_workouts`·보너스·경험치에서 빠진다. 경험치는 이미 쌓였으면 줄지 않는다(ADR 0006).

### 6.4 종류 다시 나누기

부록 B 매핑은 코드 상수(`health/activities.py`, `ACTIVITY_MAP_VERSION`)다. S2 등으로 매핑을 고치면 버전을 올리고, BE 시작 때 `health_sync.activity_map_version`이 코드보다 작으면 모든 줄의 `activity`를 `activity_raw`로 다시 계산하고 버전을 맞춘다(한 트랜잭션). `health import` CLI도 시작할 때 같은 검사를 먼저 돈다(BE를 켜지 않고 매핑을 바꾼 직후 가져와도 섞이지 않게). 이렇게 해야 `other`였던 운동이 새 종류로 바뀐 뒤 다음 전송에서 같은 운동이 두 줄이 되지 않는다(6.2의 2번은 `activity`가 같아야 찾는다).

## 7. 매일 받기: `POST /api/v1/health/export`

### 7.1 경로와 인증

- `POST /api/v1/health/export`. 몸 기록(`/body`)과 같이 `BODY_TOKEN`만 받는다. `API_TOKEN`은 `401`. `BODY_TOKEN`은 `/body`와 이 경로 말고는 모두 `401`이다.
- 인증 코드 변경(`api/server.py`): 지금의 `route == BODY_PATH` 갈래(기대 토큰 고르기, 기기 토큰 제외 조건)를 `route in PHONE_PATHS`(`{BODY_PATH, HEALTH_EXPORT_PATH}`)로 바꾼다. 비교는 지금처럼 `hmac.compare_digest`, 실패는 같은 실패 세기(limiter)에 센다.
- 헤더: `Authorization: Bearer <BODY_TOKEN>`. 내보내기 앱이 Authorization 헤더를 못 넣으면(스파이크 S1) `X-Body-Token: <BODY_TOKEN>`도 받는다. 이 헤더는 `PHONE_PATHS`에서만 읽고, 같은 `hmac` 비교와 같은 실패 세기를 쓴다. S1에서 Authorization이 되면 `X-Body-Token`은 만들지 않는다. 주소 쿼리에 토큰을 넣는 방식은 받지 않는다(로그·기록에 남기 쉽다).
- 등록 조건: SP8 7.2와 같이 `BODY_TOKEN`이 없거나 짧거나 `API_TOKEN`과 같으면 이 경로도 등록하지 않는다(`404`). 그때 `GET /health`의 `features`에서 `"apple_health"`도 뺀다.
- 본문 상한 **2MB**(다른 경로는 지금대로). 앱 전체 `client_max_size`가 64KB라 `request.read()`로는 64KB에서 먼저 막힌다. 그래서 이 경로는 사진 올리기(`api/photos.py`)처럼 `request.content`를 스트림으로 세며 읽고, `body_limit_middleware`에 이 경로 갈래(2MB, 아래 413 문구)를 더한다. 경로·심박 시계열을 끄고 보내면 하루치는 수 KB이다. 2MB를 넘으면 `413`과 함께 "경로와 심박 기록은 빼고 보내 주세요."를 돌려준다.
- CORS 없음(`/body`와 같다). `client_msg_id` 없음(같은 내용을 다시 보내면 결과가 같다).
- 디스패처의 즉시 갈래 내부 동작 `record_health_export`(`endpoint="health_export"`)로만 쓴다. 단일 작성자(ADR 0007).

### 7.2 받는 본문

내보내기 앱의 JSON 형식(버전 2)을 받는다. 정확한 키 이름은 스파이크 S1에서 실제 요청 하나를 받아 `tests/fixtures/health_export_v2.json`으로 고정하고, 그 파일을 정본으로 한다. 아래는 그 전의 가정이다.

```json
{
  "data": {
    "metrics": [
      {"name": "step_count", "units": "count", "data": [{"date": "2026-11-06 00:00:00 +0900", "qty": 8123}]},
      {"name": "sleep_analysis", "units": "hr", "data": [{"date": "2026-11-07 00:00:00 +0900", "asleep": 6.8}]},
      {"name": "weight_body_mass", "units": "kg", "data": [{"date": "2026-11-07 07:10:00 +0900", "qty": 74.2}]}
    ],
    "workouts": [
      {"id": "…", "name": "Traditional Strength Training", "start": "2026-11-07 09:12:00 +0900",
       "end": "2026-11-07 09:57:30 +0900", "duration": 2730,
       "activeEnergyBurned": {"qty": 320.4, "units": "kcal"},
       "distance": {"qty": 0, "units": "km"},
       "avgHeartRate": {"qty": 128, "units": "bpm"}, "maxHeartRate": {"qty": 161, "units": "bpm"},
       "isIndoor": true}
    ]
  }
}
```

읽는 규칙(`health/export_parser.py`, 순수 함수 `parse_export(payload, today) -> ExportBatch | str`):

- 모르는 키는 **무시한다**(SP8 `/body`처럼 거절하지 않는다). 까닭: 앱이 버전을 올리며 키를 더해도 매일 전송이 멈추지 않게.
- `data`가 없거나 객체가 아니면 `400` "건강앱 내보내기 형식이 아니에요.".
- 운동 하나가 규칙(6.1 CHECK 범위, 시작 < 끝, 미래 아님)을 어기면 그 운동만 건너뛰고 개수에 센다. 요청 전체를 거절하지 않는다.
- 단위: 거리 `mi`는 km로(× 1.609344), 칼로리 `kJ`는 kcal로(÷ 4.184), 시간 `duration`은 초. 모르는 단위면 그 값만 `null`.
- 심박 요약이 없고 `heartRateData` 배열만 있으면 평균·최대를 계산해 넣고 배열은 버린다.
- 날짜 범위: 운동은 미래만 아니면 받는다(이력 보충 겸용). 걸음·수면은 SP8과 같이 한국 달력 오늘 − 13일까지만 쓰고 나머지는 건너뛴다.

### 7.3 응답

`200 {"workouts_saved": n, "workouts_skipped": k, "body_days_saved": m, "measures_saved": j}`. 로그에는 `health_export_received`와 이 네 개수만 남긴다(값·날짜·토큰 없음).

### 7.4 걸음·수면 → 몸 기록

- `step_count`는 날짜별 합계를 `body_days.steps`로, `sleep_analysis`는 그날 아침에 끝난 밤의 잠든 시간(분)을 `body_days.sleep_minutes`로(SP8 7.2와 같은 날짜 규칙). 쓰기는 SP8 `record_body_days`와 같은 함수를 부른다(보낸 값만 덮어쓰기, 56일 보관).
- 단축어와 내보내기 앱이 둘 다 보내면 나중 것이 이긴다. 같은 출처(건강앱)라 값이 같으므로 문제 되지 않는다. 단축어는 Dahun이 원할 때 끈다(15장 D3).

### 7.5 몸무게·체지방률 → 측정값

- `weight_body_mass` → 측정값 `weight_kg`, `body_fat_percentage` → `body_fat_pct`(비율이면 × 100). SP13 `metrics.py`의 범위(35~200kg, 3~60%)를 벗어나면 건너뛴다.
- 지표마다 날마다 많아야 한 줄: 같은 날 여러 값이면 그날 마지막 값. `source_kind = 'shortcut'`(폰에서 자동으로 온 값. `'import'`는 `standing import`의 중복 검사 `StandingRepo.has_import`가 쓰므로 피한다), `source_ref = 'health:<YYYY-MM-DD>'`, `reliability = 'mid'`. 열쇠는 **(`metric`, `source_ref`)**: 같은 지표·같은 날 줄이 있으면 값을 바꾸고 새 줄을 만들지 않는다. 몸무게와 체지방률은 서로 덮지 않는다.
- SP13 화면에서 지운 줄(`deleted_at` 있음)은 다시 쓰지도 되살리지도 않는다: 같은 열쇠의 지운 줄이 있으면 그 값은 건너뛴다.
- SP13의 객관적 위치 계산은 지금처럼 그 지표의 가장 최근 값을 쓴다. 인바디 사진(`photo`, `high`)이 더 최근이 아니면 건강앱 값이 쓰인다. 날마다 오르내리는 몸무게로 점수가 흔들리지 않도록 SP13 화면의 변화 표시 규칙(분기 스냅숏)은 그대로 둔다.

### 7.6 Dahun이 할 설정 (README "애플 건강앱" 절로 옮긴다, SP16-06)

뼈대만 적는다. 정확한 메뉴 이름은 스파이크 S1에서 실제 아이폰으로 만들어 보고 화면 순서대로 적는다.

1. 아이폰에 Tailscale이 켜져 있는지 확인(운영 앱과 같은 조건).
2. App Store에서 "Health Auto Export - JSON+CSV" 설치, 건강 접근 허용(운동, 심박, 걸음, 수면, 몸무게, 체지방률만).
3. 자동화 › 새 자동화 › REST API: 주소 `https://<노트북 tailnet 이름>/api/v1/health/export`, 형식 JSON, 버전 2, 헤더 `Authorization: Bearer <BODY_TOKEN>`, 고를 것: 운동 + 위 지표, 기간 "지난 3일", 묶음 "일별", 경로 데이터 끔, 심박 시계열 끔, 주기 1시간(또는 앱이 허락하는 가장 짧은 값).
4. 한 번 손으로 보내 응답에 `workouts_saved`가 보이는지 확인. 운영 앱 운동 화면에 건강앱 운동이 보인다.
5. 이 자동화 설정을 다른 사람에게 공유하지 않는다(헤더에 `BODY_TOKEN`이 들어 있다). 새었다고 생각되면 SP8 11장 `BODY_TOKEN` 절차로 바꾸고, 단축어와 이 앱 둘 다 고친다.

노트북이 꺼져 있던 동안의 전송은 실패한다. "지난 3일"을 매번 보내므로 사흘 안의 빈칸은 다음 전송에서 채워진다. 그보다 오래 비면 이력 가져오기(8장)로 채운다.

## 8. 한 번에 채우기: 이력 가져오기 CLI

### 8.1 명령

`python -m my_planner health import <파일> [--dry-run] [--since YYYY-MM-DD] [--with-weight]`

- `<파일>`: 건강앱 내보내기 `export.zip` 또는 그 안의 `apple_health_export/export.xml`(노트북의 `data/import/` 아래에 두기를 권한다).
- `seed-life`, `standing import`와 같은 규칙: **BE가 돌고 있으면 거절**(코드 3). 단일 작성자(ADR 0007)를 지키는 가장 단순한 길이다. Dahun은 작업 스케줄러에서 BE를 멈추고 → 명령 → 다시 시작한다(README에 세 줄).
- 출력은 개수뿐: `운동 412개 가져옴, 3개 이미 있음, 9개 건너뜀`. `--with-weight`를 주면 뒤에 `, 측정값 37개`가 붙는다. 종료 코드는 `standing import` 관례에 맞춘다: 0 끝남, 3 BE 실행 중, 5 export.xml 형식이 아님, 6 읽을 수 없는 파일.
- `--dry-run`: 쓰지 않고 같은 개수만 출력. `--since`: 그 날짜 이후 운동만(기본 없음 = 전부).

### 8.2 읽는 방법

- zip 안의 `export.xml`을 **스트리밍으로** 읽는다(`zipfile` + `xml.etree.ElementTree.iterparse`, 끝난 요소는 `clear()`). 파일 전체를 메모리에 올리지 않는다. 노트북 RAM이 빠듯하다(채팅 지연 진단, 2026-10-28).
- `<Workout>` 요소만 운동으로 읽는다: `workoutActivityType`(→ 부록 B), `startDate`, `endDate`, `duration`+`durationUnit`, 자식 `<WorkoutStatistics type="HKQuantityTypeIdentifierActiveEnergyBurned" sum=…>`, `…DistanceWalkingRunning|DistanceCycling|DistanceSwimming sum=…`, `…HeartRate average=… maximum=…`, `<MetadataEntry key="HKIndoorWorkout" value="1">`. 옛 형식의 `totalEnergyBurned`, `totalDistance` 속성도 읽는다.
- `<WorkoutRoute>`, `<Record>`(걸음·심박 원시값)는 읽지 않고 건너뛴다. 예외: `--with-weight`(8.1)를 주면 `HKQuantityTypeIdentifierBodyMass`, `HKQuantityTypeIdentifierBodyFatPercentage` `<Record>`만 7.5 규칙으로 측정값에 넣는다(기본은 끔: 몸무게 이력은 SP13 화면에서 확인 카드를 거치는 것이 원칙이라, 한 번에 많이 넣는 것은 Dahun이 고를 때만).
- 저장은 6.2 규칙 그대로(`source = 'history_file'`), 1,000개마다 한 트랜잭션.
- 걸음·수면 원시값은 가져오지 않는다(몸 기록은 56일 보관이고, 이력 그래프는 범위 밖).

## 9. 운동메이트 연결

### 9.1 앞머리 `## 최근 기록`

- 두 표를 날짜 내림차순으로 합친다. 기간·개수 상한은 지금처럼 14일·8개(합친 개수).
- 건강앱 운동 줄: `- 11-07 (토) 건강앱 · 근력 운동 45분 · 320kcal · 평균 심박 128 (h#12)`. 없는 값은 그 부분을 뺀다. 거리가 0이거나 없으면 뺀다. 번호 앞의 `h#`는 운동 기록 번호(`#`)와 헷갈리지 않게 한다.
- 같은 날 운동 기록(말로 남긴 것)과 건강앱 운동이 둘 다 있으면 두 줄 다 보인다. 지시문이 둘을 같은 운동으로 볼 수 있게 한다(9.3).
- 앞머리 끝에 한 줄을 더한다: `건강앱 마지막 받음: 11-07 09:00` 또는 `건강앱: 아직 받은 적 없음`.

### 9.2 `list_workouts`

- 결과에 `health_workouts` 배열을 더한다: `{"id", "date", "activity", "activity_label", "minutes", "energy_kcal", "distance_km", "hr_avg", "hr_max"}`. 지금의 `logs`는 그대로.
- `days` 최대를 180 → **730**으로 늘린다(이력 가져오기로 몇 년치가 들어오므로). 기본은 28 그대로. 바꿀 곳: `tools/workout.py`의 `LIST_DAYS_MAX`와 `MSG_DAYS`, `tools/mcp_adapter.py`의 `list_workouts` 설명("최대 180")과 JSON 스키마 `maximum`.
- `name` 부분 일치는 운동 기록에는 지금처럼 운동 줄 이름, 건강앱 운동에는 `activity_label`(한국어 이름)에 건다.
- 결과가 많아질 수 있으니 `health_workouts`는 최근 것부터 **최대 60개**, 넘으면 `"health_truncated": true`와 기간 안 전체 개수 `"health_total": n`을 준다.
- 도구 설명에 한 줄: "건강앱(워치 등)에서 받은 운동도 함께 나옵니다. 세트·무게는 없습니다."

### 9.3 `mate.md` 고침 (운동 기록 절)

더하는 줄:

- "지난 운동을 물으면 앞머리만 보고 답하지 않고 `list_workouts`를 부릅니다. 물은 기간을 덮도록 `days`를 정합니다(지난달 → 62, 올해 → 오늘까지 날 수)."
- "찾아본 기간에 운동 기록과 건강앱 운동이 둘 다 없을 때만 기록이 없다고 말합니다. 앞머리에 '건강앱: 아직 받은 적 없음'이 있으면 '건강앱을 연결하면 워치 운동도 볼 수 있어요. 설정은 README의 애플 건강앱 절을 봐 주세요.'를 한 번 덧붙입니다."
- "건강앱 운동에는 세트·무게가 없습니다. 같은 날 운동 기록과 건강앱 운동이 둘 다 있으면 같은 운동일 수 있으니 따로 세지 않습니다."
- "건강앱 운동이 있어도 운동 기록을 대신 만들지 않습니다. 운동 기록은 지금처럼 Dahun이 말할 때만 남깁니다."
- 금지어·숫자 규칙(SP12 9.4)은 그대로: 운동한 횟수를 셀 수는 있지만 빠진 날 수·연속·비율은 말하지 않는다. "지난달 몇 번 했어?"에는 날 수로 답한다.

## 10. 경험치와 활동 보너스

- **건강 활동 보너스**: SP12 10장의 "운동 기록이 있는 날 0.5"를 "운동 기록 **또는** 숨기지 않은 건강앱 운동이 있는 날 0.5"로 넓힌다. 같은 날 둘 다면 0.5 한 번. 운동한 날 집합을 만드는 `store/repos/status.py`의 쿼리에 `UNION SELECT date FROM health_workouts WHERE hidden_at IS NULL`을 더한다. `ActivityCounts.workout_days`도 합친 날 수가 된다.
- **경험치 X13**: 운동 기록과 **같은 원장 키**를 쓴다: `source_kind = 'workout_log'`, `source_ref = 'workout_day:<date>'`, `logical_date` = 운동의 `date`, `area = 'health'`, `label` "운동 기록". 그래서 원장 표를 옮기는 마이그레이션이 필요 없고, 운동 기록과 건강앱 운동이 같은 날 있어도 하루 하나뿐이다.
- X13은 **내보내기 앱 요청으로 받은 순간의 논리적 날짜 기준 지난 7일 안**(`date >= 오늘 − 6`)인 운동만 만든다. 이때 그 줄의 `xp_eligible`을 1로 한다. 이력 가져오기(`history_file`)는 경험치를 만들지 않는다. 이력으로 먼저 들어온 운동이라도 내보내기 앱이 7일 안에 다시 보내면 그때 X13이 생긴다(실제로 최근에 한 운동이라서). 까닭: 몇 년치를 넣는 순간 경험치가 한꺼번에 쌓이면 "XP는 한 일에서만 오른다"는 감각이 깨진다(ADR 0006의 정신).
- 이룬 순간(SP8): 건강앱 운동은 출처로 쓰지 않는다(v1). 하루 끝 순간 정리는 지금처럼 대화와 운동 기록에서만.
- 사건(ADR 0021): `log_workout`이 내는 `workout_logged` 사건을 건강앱 운동은 내지 않는다(v1). 하루 끝 판단은 지금처럼 `list_workouts`로 읽어서 본다.
- SP13 측정값 `exercise_days_week`: 건강앱 운동으로 자동 계산해 대신하지 않는다(v1). 필요해지면 따로 정한다.

## 11. 운영 앱

- **운동 화면 `최근 기록`**: 건강앱 운동 줄을 함께 그린다. 줄 왼쪽에 작은 태그 "건강앱"(무채색, DESIGN.md "차분한 종이"의 태그 규칙), 제목 = 한국어 종류 이름, 둘째 줄 `45분 · 320kcal · 평균 심박 128`. 왼쪽으로 밀면 "숨기기"(되돌리기 알림 줄).
- **설정 › 연결**: "건강앱" 한 줄, 오른쪽 "마지막 받음 11/7 09:00" 또는 "연결 안 됨". 누르면 README 안내 한 문장(링크 없이 글만, 부록 A).
- **API**(SP3-4 6장에 필드 추가, `/api/v1` 그대로):
  - `GET /workout`의 응답에 `health_workouts`(최근 28일, 숨김 제외)와 `health_last_received_at`(문자열 또는 `null`)을 더한다.
  - `POST /actions` 동작 `hide_health_workout {id}`(되돌리기 `unhide_health_workout`).
  - `GET /health`의 `features`에 `"apple_health"`를 넣는다. 앱은 없으면 위 화면 요소를 숨긴다(SP12 13장과 같은 규칙).
- 앱 첫 로드 크기 여유가 거의 없다(SP15 기록: 179.4/180KB). 새 화면을 만들지 않고 운동 화면 안의 줄 모양만 더하며, 새 비동기 CSS 조각을 만들지 않는다.

## 12. 보안·개인정보와 마이그레이션

- **단축어 토큰의 뜻 넓힘**: `BODY_TOKEN`은 "폰이 건강 값을 쓰는 두 경로(`/body`, `/health/export`)"에만 통한다. 읽기는 여전히 불가. SP8 7.2·11장의 "`POST /body`만 된다"와 결정 7("경험치 없음")을 이 문서가 바꾼다(SP8 변경 기록에 한 줄 더한다, SP16-06).
- **새었을 때의 대가**: 건강 값 덮어쓰기, 가짜 운동 넣기. 가짜 운동은 숨기면 보너스·앞머리에서 빠지지만, 이미 생긴 경험치는 줄지 않는다(ADR 0006). 상한은 하루 5, 받는 순간 지난 7일까지라 한 번 새면 많아야 35다. 알아채면 SP8 11장 절차로 토큰을 바꾼다.
- **저장하지 않는 것**: 경로(GPS·위치), 심박 시계열, 기기·앱 이름(`source`/`sourceName`), 메타데이터 원문, 날씨. 파서가 읽자마자 버린다. 이력 가져오기도 같다.
- **로그**: 개수만(`health_export_received`, `health_import_done`). 운동 종류·시각·숫자는 로그에 없다.
- **두뇌로 가는 것**: 메이트 앞머리·도구 결과에 운동 종류·시간·칼로리·심박 요약이 들어간다. 채팅과 같은 경로로 Anthropic에 간다(SP12 14장과 같은 대가). 비서 두뇌에는 가지 않는다(SP12 D7). 라이프 매니저 건강 전문가는 지금처럼 `list_workouts`를 받으므로 건강앱 운동도 본다(SP15 도구 목록 그대로).
- **내보내기 앱 쪽**: 데이터는 폰 → (Tailscale) → 노트북으로 직접 간다. 앱 개발사 서버를 거치지 않는지 스파이크 S1에서 확인한다(앱 설명은 "로컬에서 보낸다"고 한다. 확인 못 하면 15장 D1에 적고 Dahun에게 묻는다).
- **보관**: 건강앱 운동은 기간 제한 없이 둔다(이력이 목적). 몸 기록·측정값은 지금 규칙.
- **마이그레이션**: `025_health_import.sql` 하나. 새 표 둘이라 앞 코드가 무시한다. 롤백은 지금 규칙(배포 롤백은 DB 파일을 바꾼다, ADR 0010). 롤백 사이에 받은 운동은 다음 전송(지난 3일)과 이력 가져오기로 다시 채운다.

## 13. 테스트

| 묶음 | 명령 | 확인 |
|---|---|---|
| 파서 | `python -m pytest tests/test_health_export_parser.py -q` | 고정 파일(S1) 한 개가 운동 n개·몸 기록·측정값으로 정확히 바뀜, 모르는 키 무시, mi·kJ 변환, `heartRateData`만 있을 때 평균·최대, 범위 밖 운동만 건너뜀, 미래 운동 건너뜀, 경로·심박 배열이 결과 객체에 없음 |
| API | `python -m pytest tests/test_api_health_export.py tests/test_api_auth.py -q` | `BODY_TOKEN`으로 200, `API_TOKEN`으로 401, 기기 토큰으로 401, (S1에서 만들면) `X-Body-Token` 헤더도 200·틀리면 실패 세기에 셈, 쿼리 토큰 401, `BODY_TOKEN` 없음 → 404이고 `features`에 `apple_health` 없음, 100KB 본문 200(64KB 앱 상한에 안 걸림), 2MB 넘으면 413과 문구, CORS 헤더 없음, 같은 본문 두 번 → 줄 수 그대로, `BODY_TOKEN`으로 `GET /workout` 401 |
| 같은 운동 | `python -m pytest tests/test_health_workouts_repo.py -q` | `external_id` 같으면 한 줄, 09:12:59와 09:13:00 시작·45와 46분은 한 줄(빈 값만 채움, 숨김 유지), 종류가 다르거나 길이가 2분 다르면 두 줄, 2730초 → 45분, 매핑 버전을 올리면 `other` 줄이 새 종류로 바뀌고 다음 전송이 같은 줄을 찾음 |
| 측정값 | `python -m pytest tests/test_health_measures.py -q` | 같은 날 몸무게·체지방률 두 줄(서로 안 덮음), 같은 날 다시 보내면 값만 바뀜, 지운 줄은 되살리지 않음, `standing import`의 같은 날 몸무게가 건너뛰어지지 않음 |
| 이력 | `python -m pytest tests/test_health_import.py -q` | 작은 export.xml 고정 파일(옛 형식·새 형식 운동 각각, Route·Record 섞임)에서 운동만, `--dry-run` 쓰기 없음, 두 번 돌려도 그대로, BE 실행 중 코드 3, 형식 아님 코드 5, `--with-weight` 없으면 측정값 0. 큰 파일: 50MB 가짜 파일을 스트리밍으로 만들어 메모리 200MB 아래(`tracemalloc`), `@pytest.mark.slow`로 따로 |
| 메이트 | `python -m pytest tests/test_tools_workout.py tests/test_mate_prompts.py -q` | 앞머리에 두 표가 날짜순으로 합쳐짐(14일·8개), `h#` 줄 형식, "건강앱: 아직 받은 적 없음" 줄, `list_workouts` `days=730` 허용·731 거절, 도구 스키마 `maximum` 730, 60개 자름과 `health_total`, 숨긴 운동 빠짐 |
| 보너스·경험치 | `python -m pytest tests/test_status_activity.py tests/test_status_xp.py -q` | 운동 기록 + 건강앱 같은 날 0.5 한 번·X13 한 번, 건강앱만 있는 날 0.5, 받은 날 기준 7일 안만 X13(8일 전 운동은 없음), `history_file`은 X13 없음, 이력으로 들어온 어제 운동을 내보내기 앱이 다시 보내면 X13 생김, 숨겨도 경험치 그대로 |
| 앱 | `cd web/app && npm test -- Workout && npm run build && npm run size` | 건강앱 태그 줄, 숨기기·되돌리기, `features`에 없으면 안 보임, 첫 로드 크기(`npm run size`) 180KB 안 |
| 노트북 수용 | `docs/sp16/laptop-checklist.md` | 실제 아이폰 전송 한 번(S1), 실제 export.zip 가져오기 한 번(S2), 메이트에게 "지난주 운동 뭐 했어?" → 건강앱 줄 근거로 답함 |

## 14. 구현 순서 (계획에서 티켓으로 쪼갠다)

### 14.1 스파이크 (Dahun 폰·노트북이 필요하다)

- **S0 기록 확인**: 노트북 DB의 `workout_logs` 개수. 0이면 3장 진단 그대로. 0이 아닌데 메이트가 없다고 했으면 그 대화를 따로 본다.
- **S1 내보내기 앱 실제 요청**: 7일 체험으로 노트북에 요청 한 번 받기. 확인: JSON 키 이름(고정 파일로 저장, 숫자는 가짜로 바꿔서), 사용자 헤더 지원, 폰 잠금 상태에서 자동 전송이 도는지와 실제 주기, 앱 개발사 서버를 거치는지, 하루치 본문 크기.
- **S2 export.zip 실제 크기와 시간**: Dahun 파일로 `health import --dry-run` 실행 시간·메모리, 운동 종류 목록(부록 B 보충).

### 14.2 티켓

1. SP16-00 스파이크 S0~S2 (위). S1 결과가 SP16-02를 막는다.
2. SP16-01 마이그레이션 025 + `store/repos/health.py`(UPSERT, 숨기기, 기간 읽기, `health_sync`).
3. SP16-02 파서 + `POST /health/export` + 인증 표 + 몸 기록·측정값 연결.
4. SP16-03 이력 가져오기 CLI.
5. SP16-04 메이트 앞머리 + `list_workouts` + `mate.md` + 보너스·경험치.
6. SP16-05 API 필드·동작·`features` + 앱 운동 화면 줄·설정 줄.
7. SP16-06 README "애플 건강앱" 절(S1을 보고 화면 순서대로) + 노트북 체크리스트.
8. SP16-07 노트북 수용.

## 15. 미결 사항 (Dahun 확인)

비서 추천으로 정한 것들이다. 바꾸고 싶은 것만 말해 주면 된다.

| # | 결정 | 추천(이 문서) | 다른 안 |
|---|---|---|---|
| D1 | 매일 받는 방법 | Health Auto Export 프리미엄(유료) | 무료 단축어 + Toolbox Pro / 매일 받지 않음 |
| D2 | 토큰 | `BODY_TOKEN`을 같이 씀 | 건강앱 전용 토큰을 하나 더 |
| D3 | 지금 걸음·잠 단축어 | 내보내기 앱이 잘 돌면 끈다(둘 다 켜도 문제 없음) | 계속 단축어로 |
| D4 | 몸무게·체지방률 | 매일 받기에는 넣고, 이력 가져오기는 고를 때만(`--with-weight`) | 둘 다 넣지 않음 / 둘 다 넣음 |
| D5 | 겹친 운동(워치 + 다른 앱) | v1은 두 줄, 화면에서 숨기기 | 시작 5분 안·같은 종류면 자동으로 하나 |
| D6 | 경험치 | 받은 날 기준 7일 안의 건강앱 운동만 X13 | 건강앱 운동은 경험치 없음(보너스만) |
| D7 | 더 받을 값 | 운동 + 걸음·수면 + 몸무게·체지방률 | 안정 시 심박, 심박 변이, VO2max도 |
| D8 | 고정 문구 | 부록 A | 고쳐 주기 |

## 부록 A. 새 고정 문구 (Dahun 확인 필요)

| 자리 | 문구 |
|---|---|
| 운동 화면 태그 | 건강앱 |
| 운동 화면 둘째 줄 | {분}분 · {kcal}kcal · 평균 심박 {bpm} |
| 숨기기 | 숨기기 / ✓ 건강앱 운동 숨김 |
| 설정 줄 | 건강앱 · 마지막 받음 {M}/{D} {HH:MM} / 건강앱 · 연결 안 됨 |
| 설정 안내 | 아이폰의 Health Auto Export 앱이 운동과 걸음, 잠을 보내면 운동메이트가 함께 봐요. 설정은 README의 '애플 건강앱'을 봐 주세요. |
| 오류(413) | 경로와 심박 기록은 빼고 보내 주세요. |
| 오류(400) | 건강앱 내보내기 형식이 아니에요. |
| 측정값 출처(SP13 화면) | 지금 `shortcut` 출처 이름 "단축어"를 "건강앱"으로 바꾼다(`web/app/src/lib/copyStanding.ts`). 단축어는 측정값을 보내지 않으므로 `shortcut` 출처는 건강앱 내보내기 앱뿐이다 |
| 메이트 안내 | 건강앱을 연결하면 워치 운동도 볼 수 있어요. 설정은 README의 애플 건강앱 절을 봐 주세요. |

## 부록 B. 운동 종류 (정규화 키 → 한국어 이름)

내보내기 앱은 영어 이름("Traditional Strength Training"), 내보내기 파일은 `HKWorkoutActivityType…` 이름을 준다. 둘 다 같은 키로 바꾼다. 목록에 없으면 `other` / "기타 운동"이고 `activity_raw`는 그대로 둔다. S2에서 Dahun 파일의 종류를 보고 보충한다.

| 키 | 한국어 | 내보내기 앱 이름 | HealthKit 이름 |
|---|---|---|---|
| `strength` | 근력 운동 | Traditional Strength Training | `HKWorkoutActivityTypeTraditionalStrengthTraining` |
| `functional` | 기능성 근력 | Functional Strength Training | `…FunctionalStrengthTraining` |
| `walk` | 걷기 | Walking | `…Walking` |
| `run` | 달리기 | Running | `…Running` |
| `cycle` | 자전거 | Cycling | `…Cycling` |
| `swim` | 수영 | Swimming | `…Swimming` |
| `hiit` | 고강도 인터벌 | High Intensity Interval Training | `…HighIntensityIntervalTraining` |
| `yoga` | 요가 | Yoga | `…Yoga` |
| `pilates` | 필라테스 | Pilates | `…Pilates` |
| `core` | 코어 운동 | Core Training | `…CoreTraining` |
| `elliptical` | 일립티컬 | Elliptical | `…Elliptical` |
| `stairs` | 계단 오르기 | Stair Climbing / Stairs | `…StairClimbing`, `…Stairs` |
| `rowing` | 로잉 | Rowing | `…Rowing` |
| `hiking` | 등산 | Hiking | `…Hiking` |
| `cooldown` | 쿨다운 | Cooldown | `…Cooldown` |
| `flexibility` | 스트레칭 | Flexibility | `…Flexibility` |
| `other` | 기타 운동 | (그 밖) | (그 밖) |

## 변경 기록

- v0.1 (2026-11-07): 첫 초안. 3장 진단, 안 A+C 추천, Q1·Q2 Dahun 답 기다림.
- v0.2 (2026-11-07): doc-reviewer 1차. 측정값 열쇠 (metric, source_ref)와 `source_kind='shortcut'`(has_import 충돌 피함), 지운 측정값 안 되살림. 2MB 본문은 스트림 읽기·미들웨어 갈래. 인증 `PHONE_PATHS`, `X-Body-Token` 비교·실패 세기, 등록 조건. 토큰 새었을 때 경험치 대가. X13 원장 키 명시와 `xp_eligible`. 같은 운동은 ±60초·±1분 범위로 찾기, 분 버림, 매핑 버전 다시 나누기(6.4). `list_workouts` 스키마 바꿀 곳. `--with-weight`, 종료 코드 5. hr CHECK. 사건·`exercise_days_week`는 v1 아님.
