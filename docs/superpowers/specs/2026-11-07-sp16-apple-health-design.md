# SP16 애플 건강앱 연동 상세 설계 (추가 기능)

- 상태: 초안 v0.5 (2026-11-07, v0.4 doc-reviewer 반영). Dahun Q1 "과거 이력 가져오기만"(2026-11-07 결정 카드)에 맞춰 매일 자동 전송을 뺐다. Q2는 기다림. 나머지는 비서 추천으로 채우고 15장에 모았다
- 작성일: 2026-11-07
- 상위 문서: [마스터 설계](2026-10-23-my-planner-master-design.md), [SP8 상태창 기록](2026-10-25-sp8-status-records-history-design.md) (건강 보너스), [SP12 운동메이트](2026-10-31-sp12-workout-mate-design.md) (운동 기록, 앞머리, 메이트 도구), [SP3-4 스펙](2026-10-24-sp3-4-life-curve-dashboard-design.md) (HTTP API 계약 정본)
- 용어: [`GLOSSARY.md`](../../../GLOSSARY.md) (이번에 "건강앱 운동", "건강앱 이력 가져오기" 추가). 결정 기록: [ADR 0023](../../adr/0023-apple-health-history-file-import.md) 추가
- 범위: 아이폰 건강앱(HealthKit)에 쌓인 **운동**(워치·다른 앱 기록)을 BE로 가져와 운동메이트가 읽게 한다. 길은 하나: 건강앱 "모든 건강 데이터 내보내기" 파일을 노트북에서 읽는다. 처음 한 번 지난 이력을 채우고, 그 뒤로는 Dahun이 원할 때(예: 주말에) 다시 내보내 새 운동을 더한다. 매일 자동 전송, 걸음·잠·몸무게 가져오기는 하지 않는다(5장 Q1). 텔레그램과 대시보드는 건드리지 않는다.

## 1. 목표와 완료 조건

Dahun이 운동메이트에게 "나 운동 뭐 했었어?"라고 물었더니 "기록이 없다"고 했다(2026-11-07). 3장에서 보듯 고장이 아니라, 메이트가 아는 운동이 **메이트 대화에서 말로 남긴 것뿐**이기 때문이다. Dahun은 아이폰 건강앱과 이어서, 이미 폰·워치에 쌓인 운동을 메이트가 알기를 바란다.

**완료 조건 (수용 기준)**

1. 노트북의 `data/import/` 아래에 export.zip을 두고 `scripts\health_import.ps1`(또는 BE를 멈춘 채 `python -m my_planner health import <export.zip>`)을 돌리면, 파일 안의 운동이 모두 `health_workouts`에 들어가고 출력은 개수뿐이다(`운동 412개 가져옴, 3개 이미 있음, 9개 건너뜀`, 8.1). BE는 다시 켜진다.
2. 같은 파일이나 더 최근에 내보낸 파일을 다시 가져와도 이미 있는 운동은 늘지 않고 새 운동만 더해진다(6.2 같은 운동 규칙).
3. 오늘 아침 워치로 45분 근력 운동을 하고 그 뒤 가져오기를 했다면, 메이트 새 대화의 앞머리 `## 최근 기록`에 `- 11-07 (토) 건강앱 · 근력 운동 45분 · 320kcal · 평균 심박 128 (h#12)` 같은 줄이 보이고, "오늘 운동 뭐 했지?"에 메이트가 이 줄을 근거로 답한다.
4. "지난달에 운동 몇 번 했어?", "작년 여름엔 뭐 했어?"에 메이트가 `list_workouts`로 기간을 넓혀 찾아 답한다. 찾아본 기간에 운동 기록·비서 쪽 흔적·건강앱 운동이 모두 없을 때만 "기록이 없다"고 하고, 건강앱 이력을 한 번도 가져오지 않았으면 안내 한 줄을 덧붙인다(9.3).
5. 마지막 가져오기 이후의 운동은 메이트가 모른다. 메이트는 앞머리의 `건강앱: 11-09까지 가져옴` 줄(날짜는 파일을 내보낸 날)을 보고, 그 뒤 날짜를 물으면 "건강앱은 11-09까지 가져와 있어요"라고 말한다(9.3).
6. 건강앱 운동이 있는 날은 건강 활동 보너스 0.5가 붙는다(운동 기록과 같은 날이면 합쳐서 0.5 한 번). 경험치 X13은 가져온 날 기준 지난 7일 안의 운동에만 붙고, 그보다 옛 운동에는 붙지 않는다(10장).
7. 경로(GPS), 심박 시계열, 기기 이름은 BE 어디에도 저장되지 않고 로그에는 개수만 남는다(12장).
8. 새 HTTP 쓰기 경로와 새 토큰이 없다. 폰에서 BE로 가는 길은 지금 그대로(단축어 `/body`)다.
9. 13장의 자동 테스트가 모두 통과한다.

## 2. 범위

| 포함 | 제외 (언제) |
|---|---|
| 건강앱 운동(종류, 시작·끝, 시간, 활동 칼로리, 거리, 평균·최대 심박, 실내·실외) 가져오기와 저장 | 세트·횟수·무게: 건강앱에 없다. 메이트 대화 운동 기록(SP12)이 계속 맡는다 |
| 건강앱 내보내기 파일(export.zip / export.xml) 가져오기 CLI와 노트북 스크립트(BE 멈춤 → 가져오기 → 다시 켬) | 매일 자동 전송(내보내기 앱 REST, 단축어 운동 읽기) (하지 않음. Dahun Q1. 필요해지면 4장 안 A를 따로 설계) |
| 메이트 앞머리·`list_workouts`에 건강앱 운동 합치기, 지시문 고침 | 네이티브 iOS 앱, HealthKit 직접 읽기 (하지 않음. PWA, 개발자 계정 없음. SP5 결정) |
| 운동 화면 최근 기록에 건강앱 운동 줄, "마지막 가져옴" 한 줄 | 앱에서 내보내기 파일 올리기 (나중. 파일이 수백 MB가 될 수 있다) |
| 건강 활동 보너스·경험치 X13 연결 | 걸음·수면·몸무게·심박 변이 등 다른 값 가져오기 (하지 않음. 걸음·잠은 SP8 단축어가 맡는다. 15장 D4) |
| | 비서가 건강앱 운동 내용 읽기 (하지 않음. SP12 D7 그대로), 대시보드 운동 화면 (나중), 칼로리·거리 보상 (하지 않음. ADR 0006) |

## 3. 진단: 메이트가 "기록 없음"이라고 한 이유

코드를 따라가 본 결과(2026-11-07, develop `a93d70b`):

1. 메이트가 아는 운동은 `workout_logs`뿐이다. 이 표는 메이트 대화에서 Dahun이 한 운동을 말했을 때 `log_workout`이 쓸 때만 채워진다(SP12 8장). 건강앱·워치 기록은 BE에 들어오는 길이 없다. SP8 몸 기록 단축어는 걸음과 잠 두 값만 보낸다(SP8 2장 "심박, 체중, 운동 기록 등 다른 건강 값: 하지 않음").
2. 말로 남길 수 있는 기록은 오늘 포함 7일 안이다(`LOG_BACKDATE_DAYS = 6`). 그래서 이전 운동은 지금 구조로는 채울 수도 없다.
3. 새 대화 앞머리는 최근 14일·8개만 넣고(`mate_context.RECENT_LOG_DAYS`), 비어 있으면 "아직 없음"이라고 쓴다. 지시문은 "지난 기록은 `list_workouts`로 찾는다"고 하지만, 앞머리가 "아직 없음"이면 두뇌가 도구를 부르지 않고 그대로 "기록이 없다"고 답하기 쉽다.
4. 도구 연결(`app.py` → `WorkoutRepo` → `PlannerTools.workout`)과 `MATE_TOOLS`의 `list_workouts`는 정상이다.

결론: 1·2가 원인이고 3이 답을 더 단정적으로 만든다.

**#244로 먼저 고친 것 (2026-11-07, SP12 5.5.1 덧붙임)**: 앞머리 끝에 `## 비서 쪽 운동 흔적`(건강 습관 체크, 끝낸 운동 할 일, 14일·10개)을 더하고, `list_workouts`가 `traces`를 함께 주며, `mate.md`에 "앞머리보다 오래된 것은 `list_workouts`로 찾고, 기록과 흔적이 둘 다 없을 때만 없다고 말한다"가 들어갔다. 3번은 이것으로 대부분 풀렸다. 이 설계는 남은 1·2(워치·건강앱 운동, 7일보다 오래된 이력)를 건강앱 이력 가져오기로 풀고, 9장은 #244 위에 건강앱 운동을 더하는 것만 다룬다.

확인할 것: Dahun이 메이트에게 운동을 말로 남긴 적이 있는데도 "없다"고 했다면 다른 버그다. 그때는 노트북 DB에서 `SELECT count(*) FROM workout_logs WHERE deleted_at IS NULL`을 확인한다(14.1 스파이크 S0).

## 4. 접근안과 선택

PWA는 HealthKit을 읽을 수 없다(SP8 4장 안 A). 건강 데이터를 읽는 것은 앱스토어 네이티브 앱만 할 수 있어서, 폰에서 꺼내 줄 무언가가 필요하다.

| 안 | 내용 | 판단 |
|---|---|---|
| A. 내보내기 앱 "Health Auto Export"의 REST API 자동화 (매일) | 앱이 정해진 주기로 고른 지표와 운동을 JSON으로 BE 주소에 POST한다. 운동마다 종류·시간·칼로리·거리·심박 요약이 있다 | 버림(Dahun Q1). 운동을 정해진 주기로 보내는 방법 중 확인된 유일한 길이지만 유료: 자동 전송은 프리미엄(평생 $24.99, 연 $6.99, 월 $1.99, 7일 체험. 2026-11-07 App Store). 나중에 매일 받기가 필요해지면 이 안을 따로 설계한다 |
| B. 지금 단축어 늘리기(무료) | 몸 기록 단축어에 운동 읽기를 더한다 | 버림(대안으로 남김). 기본 단축어의 "건강 샘플 찾기"는 운동 유형을 제대로 주지 않는다는 보고가 있고(2024 포럼), 서드파티 동작(Toolbox Pro)이 필요하다. 폰이 잠겨 있으면 "Protected health data is inaccessible"로 실패한다는 보고도 있다(2022). 심박 요약을 얻기 어렵다 |
| **C. 건강앱 "모든 건강 데이터 내보내기" 파일 가져오기 (선택)** | 건강앱 › 프로필 › 내보내기로 만든 export.zip을 노트북에서 읽는다 | **선택**. 무료이고, 지난 이력을 한 번에 채우는 유일한 길. 파일이 크고(수백 MB~GB) 손으로 옮겨야 해서 매일은 아니고 가끔(주 1회쯤) 다시 가져온다. 그 사이 운동은 메이트가 모른다 |
| D. 다른 서비스 거치기(Strava, Google Fit 등) | 건강앱 → 서비스 → BE가 그 API를 읽는다 | 버림. 데이터가 한 번 더 바깥 서비스로 나가고(P5), 노트북 BE가 외부 OAuth를 들고 있어야 한다 |

선택: **C**(Dahun Q1, 2026-11-07). 같은 저장 규칙(6장)이라 나중에 A를 붙여도 표와 읽는 쪽은 그대로 쓴다.

## 5. Dahun 결정

| # | 질문 | 상태 |
|---|---|---|
| Q1 | 어떤 방식으로 받을까(유료 앱 자동 전송 + 이력 / 무료 단축어 + 이력 / 이력 가져오기만) | **이력 가져오기만** (2026-11-07 결정 카드). 자동이 왜 유료인지 물어 답함(네이티브 앱만 건강 데이터를 읽을 수 있고, 백그라운드 전송은 그 앱의 유료 기능) |
| Q2 | 운동을 무엇으로 기록하나(애플워치 운동 앱 / 다른 앱 / 폰만) | **기다림**. 심박 값이 있을지, 운동 종류가 어떻게 들어올지가 달라진다. 저장 구조는 어느 쪽이든 같다 |
| — | 그 밖의 결정 | 비서 추천으로 채우고 15장에 모은다 |

## 6. 데이터: 건강앱 운동

### 6.1 표 (마이그레이션 `025_health_import.sql`)

```sql
-- 025: 건강앱 운동 (SP16 스펙 6.1). 시각은 UTC ISO 8601, date는 논리적 날짜(04:00 경계).
CREATE TABLE health_workouts (
    id              INTEGER PRIMARY KEY,
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
    indoor          INTEGER NULL CHECK (indoor IS NULL OR indoor IN (0, 1)),
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    hidden_at       TEXT NULL,                -- 앱에서 숨김(지우기 대신, 6.3)
    CHECK (end_at > start_at),
    CHECK (hr_avg IS NULL OR hr_max IS NULL OR hr_max >= hr_avg)
);
CREATE INDEX idx_health_workouts_date ON health_workouts (date) WHERE hidden_at IS NULL;
CREATE INDEX idx_health_workouts_start ON health_workouts (activity, start_at);

CREATE TABLE health_sync (
    id              INTEGER PRIMARY KEY CHECK (id = 1),   -- 한 줄뿐
    last_import_at   TEXT NULL,               -- 마지막 이력 가져오기를 끝낸 시각(UTC)
    exported_on      TEXT NULL,               -- 가져온 파일 중 가장 늦은 <ExportDate>의 논리적 날짜(04:00 경계, "어디까지 가져왔나"). 그날 당일은 내보낸 시각까지만 있다
    last_workout_date TEXT NULL,              -- 지금까지 가져온 가장 최근 운동의 논리적 날짜(다음 가져오기 범위의 기준)
    activity_map_version INTEGER NOT NULL DEFAULT 0   -- 부록 B 매핑 버전(6.4)
);
INSERT INTO health_sync (id) VALUES (1);
```

`workout_logs`(SP12)와 **표를 나눈다**. 까닭: 건강앱 운동에는 세트·횟수·무게가 없고 날짜 제한(7일)과 경험치 규칙이 다르며, 가져올 때마다 같은 운동이 다시 들어와 덮어써야 한다. 두 표를 합쳐 보이는 일은 읽는 쪽(9장, 11장)이 한다.

경로·심박 시계열·기기 이름·메타데이터 원문은 칸이 없다. 읽어도 버린다(12장).

### 6.2 같은 운동 규칙

- **분**: `minutes` = `duration`+`durationUnit`을 초로 바꾼 뒤 60으로 나눠 **버림**한다. 길이가 없으면 `end_at − start_at`을 같은 방식으로. 1 미만이면 그 운동을 건너뛴다. 예: 2730초 → 45분.
- **같은 운동 찾기** (`HealthRepo.upsert`, 이 순서로 처음 맞는 줄 하나):
  1. 같은 `activity`이고 `start_at`이 ±60초 안이고 `minutes`가 ±1 안인 줄(가장 가까운 시작).
  2. 없으면 새 줄.
- 까닭: 내보내기 파일에는 운동 id가 없고, 워치가 운동을 나중에 고치면(예: 끝 시각) 다음 내보내기에서 초 단위가 달라질 수 있다. 분으로 자른 열쇠는 09:12:59와 09:13:00처럼 경계에서 갈리므로 범위로 찾는다.
- 찾은 줄이 있으면 **고친다**: 비어 있던 값만 채우고, 들어온 값이 있으면 들어온 값으로 바꾼다. `hidden_at`은 건드리지 않는다(숨긴 운동이 다시 나타나지 않는다).
- 같은 시각에 다른 앱 두 개가 같은 운동을 기록한 경우(워치 + 다른 앱): 종류가 다르거나 길이가 1분 넘게 다르면 두 줄이 된다. v1은 그대로 두고 운동 화면에서 숨기게 한다(6.3). 실제로 자주 생기면 나중에 규칙을 넓힌다(15장 D5).

### 6.3 숨기기

- 운동 화면에서 건강앱 운동 줄을 숨길 수 있다(`/actions` `hide_health_workout {id}`). 다른 동작처럼 활동 기록을 남기고, 되돌리기는 지금의 `POST /activity/{id}/undo`(SP3-4 6.4.3)로 한다. 새 되돌리기 동작은 만들지 않는다. 지우지 않는 까닭: 다음 가져오기에서 같은 운동이 다시 들어오므로, 지우면 되살아난다.
- 숨긴 운동은 앞머리·`list_workouts`·보너스·경험치에서 빠진다. 경험치는 이미 쌓였으면 줄지 않는다(ADR 0006).

### 6.4 종류 다시 나누기

부록 B 매핑은 코드 상수(`health/activities.py`, `ACTIVITY_MAP_VERSION`)다. S2 등으로 매핑을 고치면 버전을 올린다. `health import` CLI는 쓰기 전에 `health_sync.activity_map_version`이 코드보다 작으면 모든 줄의 `activity`를 `activity_raw`로 다시 계산하고 버전을 맞춘다(한 트랜잭션). 쓰는 곳이 CLI뿐이라 BE 시작 때는 하지 않는다. 이렇게 해야 `other`였던 운동이 새 종류로 바뀐 뒤 다음 가져오기에서 같은 운동이 두 줄이 되지 않는다(6.2의 2번은 `activity`가 같아야 찾는다).

## 7. 매일 받기 (하지 않음)

Dahun Q1로 v1에서 뺐다. 걸음·잠은 지금처럼 SP8 단축어(`POST /body`, `BODY_TOKEN`)가 보낸다. 나중에 매일 받기가 필요해지면 4장 안 A(내보내기 앱 → 새 쓰기 경로)를 따로 설계하고, 6장 표와 9~11장 읽는 쪽은 그대로 쓴다. 그때 정할 것: 토큰 범위, 본문 크기(앱 전체 상한 64KB), 경험치 규칙(폰 토큰이 경험치를 만들게 되는 대가).

## 8. 이력 가져오기

### 8.1 명령

`python -m my_planner health import <파일> [--dry-run] [--since YYYY-MM-DD]`

- `<파일>`: 건강앱 내보내기 `export.zip` 또는 그 안의 `apple_health_export/export.xml`(노트북의 `data/import/` 아래에 두기를 권한다).
- `seed-life`, `standing import`와 같은 규칙: **BE가 돌고 있으면 거절**(코드 3). 단일 작성자(ADR 0007)를 지키는 가장 단순한 길이다. Dahun이 손으로 하지 않도록 노트북 스크립트를 둔다(8.3).
- 출력은 개수와 범위뿐: `운동 412개 가져옴, 3개 이미 있음, 9개 건너뜀 · 마지막 운동 11-07`. 종료 코드: 0 끝남, 3 BE 실행 중(잠금을 못 잡음), 6 읽을 수 없거나 건강앱 내보내기 형식이 아닌 파일(`standing import`의 `EXIT_BAD_FILE`과 같은 뜻). 줄 하나가 틀리면 그 운동만 건너뛰므로 5(줄 오류)는 쓰지 않는다.
- `--dry-run`: 쓰지 않고 같은 개수만 출력. DB를 읽기 전용으로 열고(없으면 만들지 않는다), 6.4 매핑 다시 계산도 하지 않는다. 잠금은 잡는다(`standing import`와 같다). `--since`: 그 날짜 이후 운동만. 기본은 처음이면 전부, `health_sync.last_workout_date`가 있으면 그 날 − 14일부터(워치가 고친 최근 운동을 다시 맞추되, 몇 년치를 매번 다시 쓰지 않게). 파일은 매번 처음부터 끝까지 스트리밍으로 읽지만 쓰기는 이 범위만 한다.
- 끝나면 `health_sync.last_import_at`을 쓰고, `exported_on`과 `last_workout_date`는 **기존 값과 새 값 중 늦은 쪽**으로 둔다(실수로 옛 파일을 골라도 뒤로 가지 않게). `exported_on`은 `export.xml`의 `<ExportDate value=…>`, `last_workout_date`는 파일 안 가장 최근 운동 날짜다. `--dry-run`은 쓰지 않는다.

### 8.2 읽는 방법

- 어느 파일인가: 한국어 아이폰은 `apple_health_export/내보내기.xml`(그리고 `내보내기_cda.xml`), 영어는 `export.xml`(`export_cda.xml`)로 만든다. zip 안에서 이름이 `export.xml` 또는 `내보내기.xml`로 끝나는 항목을 고르고 `_cda`가 든 것은 뺀다. `.xml`을 바로 주면 그 파일을 쓴다. 뿌리 요소가 `HealthData`인지로 마지막 확인을 한다.
- 고른 XML을 **스트리밍으로** 읽는다(`zipfile` + `xml.etree.ElementTree.iterparse`, 끝난 요소는 `clear()`). 파일 전체를 메모리에 올리지 않는다. 노트북 RAM이 빠듯하다(채팅 지연 진단, 2026-10-28).
- `<Workout>` 요소만 운동으로 읽는다: `workoutActivityType`(→ 부록 B), `startDate`, `endDate`, `duration`+`durationUnit`, 자식 `<WorkoutStatistics type="HKQuantityTypeIdentifierActiveEnergyBurned" sum=…>`, `…DistanceWalkingRunning|DistanceCycling|DistanceSwimming sum=…`, `…HeartRate average=… maximum=…`, `<MetadataEntry key="HKIndoorWorkout" value="1">`. 옛 형식의 `totalEnergyBurned`, `totalDistance` 속성도 읽는다. 단위는 `unit`/`…Unit` 속성으로 바꾼다: 거리 `mi` → km(× 1.609344), `m` → km, 칼로리 `kJ`/`Cal` → kcal(`kJ` ÷ 4.184, `Cal` = kcal), 시간 `min`/`hr`/`s`. 모르는 단위면 그 값만 `null`. 6.1 범위를 벗어나거나 시작 ≥ 끝, 미래 운동은 그 운동만 건너뛰고 `건너뜀`에 센다.
- `<WorkoutRoute>`, `<Record>`(걸음·심박·몸무게 원시값)는 읽지 않고 건너뛴다.
- 저장은 6.2 규칙 그대로, 1,000개마다 한 트랜잭션. 경험치 원장(10장)도 같은 트랜잭션에서 쓴다.
- 종료 코드 6(형식 아님) 판단: zip 안에 위 이름의 XML이 없거나, 뿌리 요소가 `HealthData`가 아니면.

### 8.3 노트북 스크립트 `scripts/health_import.ps1`

가끔 다시 가져올 때 Dahun이 하는 일을 "파일 넣고 스크립트 두 번 누르기"로 줄인다.

1. 아이폰 건강앱 › 오른쪽 위 프로필 › "모든 건강 데이터 내보내기" → 만들어진 zip(영어 `export.zip`, 한국어 `내보내기.zip`일 수 있음)을 노트북으로 옮긴다(AirDrop이 없으니 iCloud Drive나 USB 케이블). 노트북의 `data\import\`에 둔다.
2. `scripts\health_import.ps1`을 돌린다. 스크립트는(매개변수 `-TaskName`(기본 `my-planner`), `-MedicTaskName`(기본 `my-planner-medic`): 개발 체크아웃은 `-dev` 이름을 넘긴다):
   1. `data\import\`에서 `*.zip` 중 가장 최근(수정 시각) 것을 고른다(한국어 아이폰은 `내보내기.zip`일 수 있다). 없으면 안내하고 끝(작업을 건드리지 않는다).
   2. 두 작업 모두 `Disable-ScheduledTask` 뒤 `Stop-ScheduledTask`. 두 작업에 5분 반복 트리거가 있어 끄지 않으면 가져오는 동안 다시 뜬다(README seed-life 절, medic `DISABLE_STOP`과 같은 관례). 작업을 멈춰도 남는 medic 자식 python은 `register_task.ps1`의 `Stop-MedicProcesses`와 같은 방법으로 끝낸다(공통 함수는 `task_common.ps1`로 옮겨 함께 쓴다).
   3. 가져오기를 돌린다: `.venv\Scripts\python.exe -m my_planner health import <파일>`. 코드 3(잠금)이면 BE가 아직 끝나는 중이므로 5초 간격으로 6번까지 다시 돌린다.
   4. 결과 줄을 그대로 보인다.
   5. `finally`: 두 작업에 `Enable-ScheduledTask` 뒤 `Start-ScheduledTask`(가져오기가 실패하거나 Ctrl+C로 끊어도 다시 켠다).
   6. 코드 0이면 zip을 지울지 묻는다(기본 "예": 건강 데이터 전체가 든 파일이라 남겨 두지 않는다).
3. `-DryRun` 스위치는 `--dry-run`을 넘긴다. CLI는 `--dry-run`에서도 잠금을 잡으므로(`standing import`와 같다) 멈춤·다시 켬 순서는 같다. 지우기는 묻지 않는다.

README "애플 건강앱" 절에 위 두 단계와 "얼마나 자주: 메이트가 최근 운동을 알았으면 할 때(예: 주말에 한 번)"를 적는다.

## 9. 운동메이트 연결

### 9.1 앞머리 `## 최근 기록`

- `workout_logs`와 `health_workouts` 두 표를 날짜 내림차순으로 합친다. 기간·개수 상한은 지금처럼 14일·8개(합친 개수). #244의 `## 비서 쪽 운동 흔적` 섹션은 그대로 따로 둔다(흔적은 숫자가 없는 다른 출처라서).
- 건강앱 운동 줄: `- 11-07 (토) 건강앱 · 근력 운동 45분 · 320kcal · 평균 심박 128 (h#12)`. 없는 값은 그 부분을 뺀다. 거리가 0이거나 없으면 뺀다. 번호 앞의 `h#`는 운동 기록 번호(`#`)와 헷갈리지 않게 한다.
- 같은 날 운동 기록(말로 남긴 것)과 건강앱 운동이 둘 다 있으면 두 줄 다 보인다. 지시문이 둘을 같은 운동으로 볼 수 있게 한다(9.3).
- `## 최근 기록` 머리 바로 아래 첫 줄로 더한다(앞머리 끝에 두면 #244의 흔적 섹션 안에 섞인다): `건강앱: 11-09까지 가져옴` 또는 `건강앱: 아직 가져온 적 없음`. 날짜는 `health_sync.exported_on`.
- 같은 날 운동 기록과 건강앱 운동이 둘 다 있으면 8개 상한을 두 줄이 쓴다. 받아들인다(14일 안에 8개가 넘는 일은 드물고, 넘으면 `list_workouts`로 본다).

### 9.2 `list_workouts`

- 결과에 `health_workouts` 배열과 `health_imported_through`(`health_sync.exported_on` 또는 `null`)를 더한다(`logs`, #244의 `traces`와 나란히): `{"id", "date", "activity", "activity_label", "minutes", "energy_kcal", "distance_km", "hr_avg", "hr_max"}`. 지금의 `logs`는 그대로.
- `days` 최대를 180 → **730**으로 늘린다(이력 가져오기로 몇 년치가 들어오므로). 기본은 28 그대로. 바꿀 곳: `tools/workout.py`의 `LIST_DAYS_MAX`, `MSG_DAYS`, `list_workouts` docstring("최대 180"), `tools/mcp_adapter.py`의 `list_workouts` 설명("최대 180")과 JSON 스키마 `maximum`.
- `name` 부분 일치는 운동 기록에는 지금처럼 운동 줄 이름, 건강앱 운동에는 `activity_label`(한국어 이름)에 건다.
- 결과가 많아질 수 있으니 `health_workouts`는 최근 것부터 **최대 60개**, 넘으면 `"health_truncated": true`와 기간 안 전체 개수 `"health_total": n`을 준다.
- 도구 설명에 한 줄: "건강앱(워치 등)에서 가져온 운동도 함께 나옵니다. 세트·무게는 없고, health_imported_through 날짜 이후는 아직 가져오지 않았습니다."

### 9.3 `mate.md` 고침 (운동 기록 절)

#244가 더한 "지난 운동을 물으면 … 둘 다 없을 때만 기록이 없다고 말합니다" 줄을 아래처럼 고친다(운동 기록 · 흔적 · 건강앱 운동 셋으로).

- "지난 운동을 물으면 앞머리만 보고 답하지 않고 `list_workouts`를 부릅니다. 물은 기간을 덮도록 `days`를 정합니다(지난달 → 62, 올해 → 오늘까지 날 수)."
- "찾아본 기간에 운동 기록, 비서 쪽 운동 흔적, 건강앱 운동이 모두 없을 때만 기록이 없다고 말합니다. 앞머리에 '건강앱: 아직 가져온 적 없음'이 있으면 '건강앱 기록을 가져오면 워치 운동도 볼 수 있어요. 방법은 README의 애플 건강앱 절에 있어요.'를 한 번 덧붙입니다."
- "건강앱 운동은 마지막으로 가져온 날까지만 있습니다. 그 날짜 당일과 그 뒤를 물었는데 기록이 없으면 '건강앱은 {MM-DD}까지 가져와 있어요'라고 말하고, 운동을 안 했다고 말하지 않습니다(그날 당일도 내보낸 뒤에 한 운동은 없을 수 있습니다). 가져오라고 재촉하지 않습니다."
- "건강앱 운동에는 세트·무게가 없습니다. 같은 날 운동 기록과 건강앱 운동이 둘 다 있으면 같은 운동일 수 있으니 따로 세지 않습니다."
- "건강앱 운동이 있어도 운동 기록을 대신 만들지 않습니다. 운동 기록은 지금처럼 Dahun이 말할 때만 남깁니다."
- 금지어·숫자 규칙(SP12 9.4)은 그대로: 운동한 횟수를 셀 수는 있지만 빠진 날 수·연속·비율은 말하지 않는다. "지난달 몇 번 했어?"에는 날 수로 답한다.

## 10. 경험치와 활동 보너스

- **운동한 날**: "운동 기록 **또는** 숨기지 않은 건강앱 운동이 있는 날"로 넓힌다. 지금 운동한 날을 따로 세는 곳이 셋이라, 한 함수 `exercise_days(conn, since, until) -> set[date]`(`store/repos/health.py`, 두 표 UNION)로 모으고 셋 다 이것을 쓴다:
  - `store/repos/status.py`의 운동한 날 쿼리(건강 활동 보너스 0.5, `ActivityCounts.workout_days`). 93행 docstring "log_days와 같은 질의"도 고친다.
  - `panel/pace.py`(내 속도 표, 지금 `WorkoutRepo.log_days`). 건강 습관 체크를 함께 세는 지금 합침은 그대로 둔다.
  - `standing/service.py:with_derived`의 `exercise_days_week`(지금 운동 기록으로 자동 계산한다. 건강앱 운동이 더 정확한 근거라 함께 센다). SP13 스펙의 `exercise_days_week` 정의("운동 기록으로 계산")를 이 문서가 바꾼다: SP13 변경 기록에 한 줄 더한다(SP16-03).
- **건강 활동 보너스**: SP12 10장의 "운동 기록이 있는 날 0.5"가 위 "운동한 날"로 바뀐다. 같은 날 둘 다면 0.5 한 번.
- **경험치 X13**: 운동 기록과 **같은 원장 키**를 쓴다: `source_kind = 'workout_log'`, `source_ref = 'workout_day:<date>'`, `logical_date` = 운동의 `date`, `area = 'health'`, `label` "운동 기록". 그래서 원장 표를 옮기는 마이그레이션이 필요 없고, 운동 기록과 건강앱 운동이 같은 날 있어도 하루 하나뿐이다.
- X13은 **가져오기를 돌린 순간의 논리적 날짜 기준 지난 7일 안**(`date >= 오늘 − 6`)인 숨기지 않은 운동만 만든다. 그보다 옛 운동은 만들지 않는다. 까닭: 첫 가져오기로 몇 년치를 넣는 순간 경험치가 한꺼번에 쌓이면 "XP는 한 일에서만 오른다"는 감각이 깨진다(ADR 0006의 정신). 같은 날 X13이 이미 있으면 원장 UNIQUE가 막는다. 주말에 한 번 가져오면 그 주 운동한 날마다 5가 그때 쌓인다(SP7 지난 날 체크처럼 `logical_date`는 운동 날짜).
- 가져오기를 2주에 한 번 하면 8~14일 전 운동은 X13이 없다. 받아들인다(보너스는 날짜로 계산하므로 그대로 붙는다). 15장 D3.
- 이룬 순간(SP8): 건강앱 운동은 출처로 쓰지 않는다(v1). 하루 끝 순간 정리는 지금처럼 대화와 운동 기록에서만.
- 사건(ADR 0021): `log_workout`이 내는 `workout_logged` 사건을 건강앱 운동은 내지 않는다(v1). 하루 끝 판단은 지금처럼 `list_workouts`로 읽어서 본다.

## 11. 운영 앱

- **운동 화면 `최근 기록`**: 건강앱 운동 줄을 함께 그린다. 줄 왼쪽에 작은 태그 "건강앱"(무채색, DESIGN.md "차분한 종이"의 태그 규칙), 제목 = 한국어 종류 이름, 둘째 줄 `45분 · 320kcal · 평균 심박 128`. 왼쪽으로 밀면 "숨기기"(되돌리기 알림 줄).
- **운동 화면 `최근 기록` 머리**: 건강앱 이력이 있으면 섹션 아래 보조 글 "건강앱 11/9까지"(`exported_on`, 앱 날짜 표기 `M/D`), 없으면 그리지 않는다. 설정 화면은 건드리지 않는다.
- **API**(SP3-4 6장에 필드 추가, `/api/v1` 그대로):
  - `GET /workout`의 응답에 `health_workouts`(최근 28일, 숨김 제외)와 `health_imported_through`(날짜 문자열 또는 `null`)를 더한다.
  - `POST /actions` 동작 `hide_health_workout {id}`(되돌리기는 지금의 `/activity/{id}/undo`). `api/models.py`와 앱 `types.gen.ts`를 함께 고친다(SP16-04).
  - `GET /health`의 `features`에 `"apple_health"`를 넣는다. 앱은 없으면 위 화면 요소를 숨긴다(SP12 13장과 같은 규칙).
- 앱 첫 로드 크기 여유가 거의 없다(SP15 기록: 179.4/180KB). 새 화면을 만들지 않고 운동 화면 안의 줄 모양만 더하며, 새 비동기 CSS 조각을 만들지 않는다.

## 12. 보안·개인정보와 마이그레이션

- **새 경로·토큰 없음**: 쓰는 곳은 노트북 CLI뿐이다(BE를 멈춘 채, 잠금을 잡고). HTTP로 건강앱 운동을 쓰는 길은 없고 `BODY_TOKEN`의 범위도 그대로다. 앱의 쓰기는 숨기기·되돌리기(`/actions`, `API_TOKEN`·기기 토큰)뿐이다.
- **저장하지 않는 것**: 경로(GPS·위치), 심박 시계열, 기기·앱 이름(`source`/`sourceName`), 메타데이터 원문, 날씨. 가져오기가 읽자마자 버린다.
- **로그**: 개수만(`health_import_done`). 운동 종류·시각·숫자는 로그에 없다.
- **두뇌로 가는 것**: 메이트 앞머리·도구 결과에 운동 종류·시간·칼로리·심박 요약이 들어간다. 채팅과 같은 경로로 Anthropic에 간다(SP12 14장과 같은 대가). 비서 두뇌에는 가지 않는다(SP12 D7). 라이프 매니저 건강 전문가는 지금처럼 `list_workouts`를 받으므로 건강앱 운동도 본다(SP15 도구 목록 그대로).
- **내보내기 파일**: 건강 데이터 전체(걸음·심박·위치 경로 포함)가 든 파일이다. 저장소·로그·`/mnt/project-files`·채팅에 올리지 않는다. 노트북 `data/import/`는 `.gitignore` 아래이고, 스크립트가 가져온 뒤 지우기를 권한다(8.3). iCloud Drive로 옮겼으면 거기서도 지우라고 README에 적는다.
- **보관**: 건강앱 운동은 기간 제한 없이 둔다(이력이 목적). 몸 기록·측정값은 지금 규칙.
- **마이그레이션**: `025_health_import.sql` 하나. 새 표 둘이라 앞 코드가 무시한다. 롤백은 지금 규칙(배포 롤백은 DB 파일을 바꾼다, ADR 0010). 롤백 사이에 가져온 운동은 다음 가져오기로 다시 채운다.

## 13. 테스트

| 묶음 | 명령 | 확인 |
|---|---|---|
| API | `python -m pytest tests/test_api_workout.py tests/test_api_actions.py -q` | `GET /workout`에 `health_workouts`(28일, 숨김 제외)·`health_imported_through`, `hide_health_workout`·되돌리기, 없는 id 오류, `features`에 `apple_health` |
| 같은 운동 | `python -m pytest tests/test_health_workouts_repo.py -q` | 09:12:59와 09:13:00 시작·45와 46분은 한 줄(빈 값만 채움, 숨김 유지), 종류가 다르거나 길이가 2분 다르면 두 줄, 2730초 → 45분, 매핑 버전을 올리면 가져오기 전에 `other` 줄이 새 종류로 바뀌고 같은 줄을 찾음 |
| 이력 | `python -m pytest tests/test_health_import.py -q` | 작은 export.xml 고정 파일(옛 형식·새 형식 운동 각각, Route·Record 섞임)에서 운동만, 경로·심박 원시값이 저장되지 않음, mi·kJ 단위 변환, `--dry-run` 쓰기 없음, 두 번 돌려도 그대로, 두 번째부터 기본 범위가 마지막 운동 − 14일, `exported_on`·`last_workout_date` 기록과 옛 파일로 뒤로 가지 않음, BE 실행 중 코드 3, 형식 아님(뿌리가 `HealthData` 아님, zip에 export.xml 없음)·못 읽는 파일 코드 6, `--dry-run`이 DB를 만들지 않음, 미래 운동 건너뜀. 큰 파일: 50MB 가짜 파일을 스트리밍으로 만들어 메모리 200MB 아래(`tracemalloc`), `@pytest.mark.slow`로 따로 |
| 메이트 | `python -m pytest tests/test_tools_workout.py tests/test_mate_prompts.py -q` | 앞머리에 두 표가 날짜순으로 합쳐짐(14일·8개), `h#` 줄 형식, "건강앱: 아직 가져온 적 없음"과 "건강앱 마지막 가져옴" 줄, `health_imported_through`, `list_workouts` `days=730` 허용·731 거절, 도구 스키마 `maximum` 730, 60개 자름과 `health_total`, 숨긴 운동 빠짐 |
| 보너스·경험치·운동한 날 | `python -m pytest tests/test_status_activity.py tests/test_status_xp.py tests/test_health_import.py tests/test_panel_pace.py tests/test_standing_drift.py -q` | `exercise_days`가 두 표 합침(숨김 제외), 내 속도 표와 `exercise_days_week`에 건강앱 운동이 셈, 운동 기록 + 건강앱 같은 날 0.5 한 번·X13 한 번, 건강앱만 있는 날 0.5, 가져온 날 기준 7일 안만 X13(7일 전 운동은 없음, 6일 전은 있음), 숨긴 운동은 X13 없음, 숨겨도 이미 생긴 경험치 그대로 |
| 스크립트 | `python -m pytest tests/test_health_import_script.py -q` | `tests/test_task_templates.py`처럼 스크립트 본문을 정적으로 검사: 두 작업 이름 매개변수, `Disable-ScheduledTask`·`Stop-ScheduledTask`가 가져오기 앞, `try`/`finally` 안에 `Enable-ScheduledTask`·`Start-ScheduledTask` 둘 다, medic 자식 끝내기 호출, 코드 3 재시도, BOM 붙인 UTF-8, 아무 이름의 최근 `*.zip`, `-DryRun`이면 지우기 묻지 않음. 기대: `n passed` |
| 앱 | `cd web/app && npm test -- Workout && npm run build && npm run size` | 건강앱 태그 줄, 숨기기·되돌리기, `features`에 없으면 안 보임, 첫 로드 크기(`npm run size`) 180KB 안 |
| 노트북 수용 | `docs/sp16/laptop-checklist.md` | 실제 export.zip을 스크립트로 가져오기 한 번(S2), 메이트에게 "지난주 운동 뭐 했어?" → 건강앱 줄 근거로 답함, 마지막 가져옴 이후 날짜를 물으면 "…까지 가져와 있어요" |

## 14. 구현 순서 (계획에서 티켓으로 쪼갠다)

### 14.1 스파이크 (Dahun 폰·노트북이 필요하다)

- **S0 기록 확인**: 노트북 DB의 `workout_logs` 개수. 0이면 3장 진단 그대로. 0이 아닌데 메이트가 없다고 했으면 그 대화를 따로 본다.
- **S2 export.zip 실제 크기와 시간**: Dahun 파일로 `health import --dry-run` 실행 시간·메모리, 운동 종류 목록(부록 B 보충), 워치 운동에 심박 통계가 있는지(Q2). 결과는 개수와 종류 이름만 기록한다(값은 남기지 않는다).

### 14.2 티켓

1. SP16-01 마이그레이션 025 + `store/repos/health.py`(같은 운동 찾기·고치기, 숨기기, 기간 읽기, `health_sync`) + `health/activities.py`(부록 B).
2. SP16-02 이력 가져오기 CLI(스트리밍 읽기, 범위, 경험치) + 고정 export.xml 파일.
3. SP16-03 메이트 앞머리 + `list_workouts` + `mate.md` + 보너스.
4. SP16-04 API 필드·동작·`features` + 앱 운동 화면 줄.
5. SP16-05 `scripts/health_import.ps1` + README "애플 건강앱" 절 + 노트북 체크리스트.
6. SP16-06 노트북 수용(S0, S2 포함). S2 결과로 부록 B를 보충하면 매핑 버전을 올린다(6.4).

## 15. 미결 사항 (Dahun 확인)

비서 추천으로 정한 것들이다. 바꾸고 싶은 것만 말해 주면 된다.

| # | 결정 | 추천(이 문서) | 다른 안 |
|---|---|---|---|
| D1 | 가져오는 자주 | Dahun이 원할 때(주말 한 번쯤 권함), 알림·재촉 없음 | 정해진 요일에 비서가 한 번 알려 줌 |
| D2 | 다시 가져올 때 쓰는 범위 | 마지막 운동 − 14일부터 | 매번 전부 |
| D3 | 경험치 | 가져온 날 기준 7일 안의 운동만 X13 | 건강앱 운동은 경험치 없음(보너스만) / 날짜 제한 없이 |
| D4 | 다른 값(걸음·잠·몸무게) | 가져오지 않음(걸음·잠은 SP8 단축어) | 몸무게 이력도 가져와 SP13 측정값으로 |
| D5 | 겹친 운동(워치 + 다른 앱) | v1은 두 줄, 화면에서 숨기기 | 시작 5분 안·같은 종류면 자동으로 하나 |
| D6 | 고정 문구 | 부록 A | 고쳐 주기 |

## 부록 A. 새 고정 문구 (Dahun 확인 필요)

| 자리 | 문구 |
|---|---|
| 운동 화면 태그 | 건강앱 |
| 운동 화면 둘째 줄 | {분}분 · {kcal}kcal · 평균 심박 {bpm} |
| 숨기기 | 숨기기 / ✓ 건강앱 운동 숨김 |
| 최근 기록 보조 글 | 건강앱 {M}/{D}까지 |
| CLI 출력 | 운동 {n}개 가져옴, {k}개 이미 있음, {s}개 건너뜀 · 마지막 운동 {MM-DD} |
| CLI 오류 | 건강앱 내보내기 파일(export.zip)이 아니에요. / 파일을 읽을 수 없어요. / BE가 돌고 있어요. 멈춘 뒤 다시 해 주세요. |
| 스크립트 끝 물음 | 가져온 파일을 지울까요? 건강 데이터 전체가 들어 있어요. (Y/n) |
| 메이트 안내 | 건강앱 기록을 가져오면 워치 운동도 볼 수 있어요. 방법은 README의 애플 건강앱 절에 있어요. / 건강앱은 {MM-DD}까지 가져와 있어요. |
| 앞머리 줄 | 건강앱: {MM-DD}까지 가져옴 / 건강앱: 아직 가져온 적 없음 |

## 부록 B. 운동 종류 (정규화 키 → 한국어 이름)

내보내기 파일은 `HKWorkoutActivityType…` 이름을 준다. 영어 이름 칸은 나중에 안 A(내보내기 앱)를 붙일 때를 위한 것이다. 목록에 없으면 `other` / "기타 운동"이고 `activity_raw`는 그대로 둔다. S2에서 Dahun 파일의 종류를 보고 보충한다.

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
- v0.3 (2026-11-07): develop에 들어온 #244(비서 쪽 운동 흔적)를 3장·9장에 반영. 건강앱 운동은 흔적과 따로 두고 `list_workouts`에 나란히.
- v0.4 (2026-11-07): Dahun Q1 "과거 이력 가져오기만". 7장 매일 받기(새 경로, `BODY_TOKEN` 넓힘, 걸음·잠·몸무게)를 뺐다. 다시 가져오기 흐름(범위, `last_workout_date`, 노트북 스크립트 8.3), 메이트의 "어디까지 가져왔나" 말하기, 경험치는 가져온 날 기준 7일 안, 내보내기 파일 취급. `external_id`·`source`·`xp_eligible` 칸 뺌. 15장 다시 정리.
- v0.5 (2026-11-07): v0.4 리뷰. (재확인 반영: `exported_on`은 논리적 날짜, 당일도 내보낸 뒤는 없을 수 있음, SP13 정의 바꿈 명시, 용어 "마지막으로 내보낸 파일".) 스크립트가 두 작업을 끄고(Disable) medic 자식까지 끝낸 뒤 가져오고 finally에서 켬, 작업 이름 매개변수, 코드 3 재시도, 정적 검사 테스트. "어디까지"는 `<ExportDate>`(`exported_on`), 날짜는 늦은 쪽만. 종료 코드 6으로 합침. 숨기기 되돌리기는 기존 undo. 운동한 날 세는 세 곳을 `exercise_days` 하나로. 앞머리 줄 위치·표기 통일.
