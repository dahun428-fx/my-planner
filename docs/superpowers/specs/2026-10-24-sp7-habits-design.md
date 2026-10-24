# SP7 습관 체크 상세 설계 (추가 기능)

- 상태: 초안 v2 (문서 리뷰 반영, Dahun 검토 전)
- 작성일: 2026-10-24
- 상위 문서: [마스터 설계](2026-10-23-my-planner-master-design.md), [SP1 비서 코어](2026-10-23-sp1-secretary-core-design.md), [SP3-4 스펙](2026-10-24-sp3-4-life-curve-dashboard-design.md) (BE HTTP API 계약의 정본), [SP5 운영 앱](2026-10-24-sp5-ops-app-design.md)
- 용어: [`GLOSSARY.md`](../../../GLOSSARY.md) (이번에 "습관", "습관 체크" 추가), 결정 기록: [ADR 0011](../../adr/0011-habits-are-not-recurring-tasks.md) 추가
- 범위: 할 일과 나란히 쓰는 **습관**과 그 **체크**. BE(SQLite, 도구, API, 텔레그램, 회차)와 운영 앱(오늘 화면 블록, 습관 화면, 카드 하나)을 다룬다. 채팅 생성형 UI 개편(카탈로그 조각 체계)은 운영 앱 스레드 몫이고, 이 문서는 컴포넌트 하나(`ui_habit_check`)만 더한다(9장).

## 1. 목표와 완료 조건

Dahun은 할 일 말고도 매일 또는 주 몇 번 챙길 **습관**(물 마시기, 스트레칭, 주 3회 운동)을 가볍게 체크한다. 새로 들이는 습관은 "이번 주 몇 번 했는지"와 지난 4주의 모양으로 자리 잡는 정도를 본다. 놓친 날을 세거나 끊긴 것을 알리지 않는다(ADR 0006).

**완료 조건 (수용 기준)**

1. 앱 습관 화면에서 "매일 물 마시기"와 "주 3회 운동"을 추가하면, 오늘 화면의 습관 블록과 텔레그램 `/habits`에 같은 순서로 보인다.
2. 오늘 화면에서 습관 줄을 누르면 `POST /actions check_habit`이 적용되고 확인 문구 "✓ 습관: 물 마시기"와 "되돌리기"가 알림 줄에 보인다. 다시 누르면 `uncheck_habit`이다.
3. 저녁 체크인 회차에 활성 습관이 있으면 텔레그램 메시지에는 습관 버튼 줄이, 앱 체크인 상세에는 `ui_habit_check` 카드가 컨디션 고르기 앞에 붙는다(텔레그램 버튼 줄과 같은 순서). 텔레그램 버튼을 누르면 그 줄의 표시가 `☐`에서 `✓`로 바뀌고, 앱에서 다시 읽으면 같은 상태다.
4. 대화에서 "오늘 스트레칭 했어"라고 하면 두뇌가 `check_habit`을 부르고 확인 문구가 붙는다. 회차 차례(사용자 메시지 없음)에서는 두뇌가 습관을 체크할 수 없다(5.4 H6).
5. 습관을 체크하면 경험치 3이 쌓인다. 체크를 되돌려도 경험치는 줄지 않고, 같은 날 다시 체크해도 두 번 쌓이지 않는다. 주 단위 목표 보상은 없다(기간 한정 보상, ADR 0006).
6. 습관 화면, 오늘 블록, 텔레그램, 두뇌의 답 어디에도 연속 기록, 끊김, 놓친 횟수, 비율(%)이 나오지 않는다. 금지어 검사 테스트(SP5 10장)가 새 문구에도 돈다.
7. 12장의 자동 테스트가 모두 통과한다.

## 2. 범위

| 포함 | 제외 (언제) |
|---|---|
| 습관 추가·고치기·쉬어 가기·다시 시작·그만두기 | 요일 지정 습관(월·수·금) (필요해지면. Dahun Q2 결정) |
| 매일 습관, 주 N회 습관(요일 자유) | 하루 여러 번 체크(물 8잔 세기) (하지 않음. 하루 한 번 체크) |
| 체크와 체크 취소(오늘 포함 7일) | 반복 할 일(날짜·시각이 있는 할 일 자동 생성) (SP1처럼 나중, ADR 0011) |
| 오늘 화면 습관 블록, 습관 화면(`/habits/`), 체크인 카드 | 습관 알림(시각 맞춰 따로 울리기) (하지 않음. 체크인 하루 3회 상한) |
| 텔레그램 `/habits`, 저녁 체크인 습관 버튼 | 아침 브리핑에 습관 넣기 (Dahun Q3 결정: 넣지 않음) |
| 두뇌 도구(추가·고치기·상태·체크·목록), 주간 회고에서 습관 돌아보기 | 비서가 습관 초안을 내는 흐름 (나중. 지금은 말로 제안하고 사용자가 원하면 추가) |
| 경험치 한 줄(체크) | 습관별 스탯·레벨, 대시보드 화면 (나중) |

## 3. Dahun 결정 (2026-10-24, 이 스레드)

| # | 질문 | 결정 |
|---|---|---|
| Q1 | 습관 체크로 무엇을 얻나 | C: 기본 루틴을 가볍게 체크하고, 새 습관은 "이번 주 몇 번"을 본다 |
| Q2 | 주기 | B: 매일 + 주 N회(요일 자유). 요일 지정은 뺀다 |
| Q3 | 어디서 체크하나 | B: 앱 오늘 화면 + 저녁 체크인 카드(텔레그램 버튼 포함) + 대화. 아침 브리핑에는 넣지 않는다 |
| — | 그 밖의 결정 | "일단 다 추천대로해": 이 문서의 나머지 선택은 비서의 추천이고 Dahun 검토 대상이다(15장) |

## 4. 접근안과 선택

| 안 | 내용 | 판단 |
|---|---|---|
| A. 반복 할 일로 만들기 | 습관마다 매일 `tasks` 행을 만들고 완료로 체크 | **버림**. 안 한 날의 할 일이 쌓여 "밀린 일"이 되고(P2·P4 위반), 우선순위·초안·첫 걸음 규칙과 엉킨다. 반복 할 일은 날짜·시각이 있는 일을 위한 별도 설계로 남긴다 |
| B. 습관 표 + 체크 표 (선택) | `habits`(정의)와 `habit_checks`(그날 했음)만 둔다. 안 한 날은 행이 없을 뿐이다 | **선택**. 놓친 날이 데이터로 존재하지 않아 벌줄 거리가 없다. 할 일 흐름을 건드리지 않는다 |
| C. 컨디션처럼 날마다 한 행에 JSON | `habit_days(date, checked_json)` | 버림. 습관 이름이 바뀌거나 그만둘 때 지난 기록 해석이 어렵고, 되돌리기 대상을 가르기 어렵다 |

## 5. BE

### 5.1 `012_habits.sql`

```sql
-- 012: 습관과 체크 (SP7 스펙 5.1). 날짜는 논리적 날짜 YYYY-MM-DD, 시각은 UTC ISO 8601.
CREATE TABLE habits (
    id               INTEGER PRIMARY KEY,
    title            TEXT NOT NULL CHECK (length(title) BETWEEN 1 AND 40),
    area             TEXT NOT NULL CHECK (area IN
        ('career', 'finance', 'health', 'relationships', 'learning', 'quality_of_life')),
    kind             TEXT NOT NULL CHECK (kind IN ('daily', 'weekly')),
    target_per_week  INTEGER NULL CHECK (target_per_week BETWEEN 1 AND 6),
    status           TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'paused', 'archived')),
    sort_order       INTEGER NOT NULL,
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL,
    deleted_at       TEXT NULL,          -- 되돌린 추가만. 도구로는 쓰지 않는다
    CHECK ((kind = 'daily') = (target_per_week IS NULL))
);

CREATE TABLE habit_checks (
    habit_id    INTEGER NOT NULL REFERENCES habits (id),
    date        TEXT NOT NULL,
    checked_at  TEXT NOT NULL,
    PRIMARY KEY (habit_id, date)
);
CREATE INDEX idx_habit_checks_date ON habit_checks (date);

-- 경험치 원장의 source_kind CHECK에 'habit_check'를 더한다(5.6). SQLite는 CHECK를 고칠 수 없어 새 표로 옮긴다.
CREATE TABLE status_xp_ledger_new (
    id           INTEGER PRIMARY KEY,
    at           TEXT NOT NULL,
    logical_date TEXT NOT NULL,
    source_kind  TEXT NOT NULL CHECK (source_kind IN
        ('task_done', 'checkin_reply', 'condition', 'review_week', 'ladder', 'wheel',
         'year_review', 'rest_day', 'secretary', 'habit_check')),
    source_ref   TEXT NOT NULL,
    amount       INTEGER NOT NULL CHECK (amount > 0),   -- 오르기만 한다(ADR 0006)
    area         TEXT NULL,
    label        TEXT NOT NULL,
    UNIQUE (source_kind, source_ref)
);
INSERT INTO status_xp_ledger_new (id, at, logical_date, source_kind, source_ref, amount, area, label)
    SELECT id, at, logical_date, source_kind, source_ref, amount, area, label FROM status_xp_ledger;
DROP TABLE status_xp_ledger;
ALTER TABLE status_xp_ledger_new RENAME TO status_xp_ledger;
CREATE INDEX idx_xp_date ON status_xp_ledger (logical_date);
```

- **원장 옮기기가 안전한 이유**: 001~011에 `status_xp_ledger`를 참조하는 FK, 트리거, 뷰가 없다. `store/db.py`는 마이그레이션 파일을 `executescript("BEGIN; … COMMIT;")`로 한 번에 적용하므로 중간에 멈춰도 원장이 반쯤 옮겨진 상태로 남지 않는다. `foreign_keys=ON`이어도 이 표에는 걸리는 키가 없다. id를 그대로 옮기므로 `recent_xp` 순서도 같다. 적용 뒤 `/health`의 `version.schema`는 12다.

- **매일 습관**(`daily`): 목표 횟수가 없다. 주 7회 습관은 매일 습관으로 만든다(그래서 `target_per_week`는 1~6).
- **주 N회 습관**(`weekly`): 한 ISO 주(월~일, `priorities.period`의 주와 같다)에 N번. 요일은 자유다.
- **안 한 날은 행이 없다.** "놓친 날"을 저장하거나 계산하는 함수를 만들지 않는다(12장 테스트로 확인: 저장소에 "빠진 날"을 돌려주는 함수가 없다).
- **활성 습관 상한 10개**(`active`만 센다). 넘으면 추가·다시 시작을 거절한다: "습관은 한 번에 10개까지 챙길 수 있어요. 하나를 쉬어 가거나 그만두면 더할 수 있어요." 체크인 메시지가 한 화면을 넘지 않게 하려는 것이다.
- `sort_order`: 추가한 순서(가장 큰 값 + 1). 순서 바꾸기는 v1에 없다(YAGNI).
- `paused`(쉬어 가기)와 `archived`(그만두기)는 체크 목록에서 빠지고 기록은 남는다. 그만둔 습관은 습관 화면의 "그만둔 습관" 묶음에서 다시 시작할 수 있다. 행을 지우는 길은 되돌린 추가(`deleted_at`)뿐이다.
- 이름을 바꿔도 지난 체크는 같은 습관의 기록이다(`habit_id`로 묶인다).

### 5.2 저장소 `store/repos/habits.py`

| 함수 | 하는 일 |
|---|---|
| `add(title, area, kind, target, now) -> Habit` | 추가(`sort_order` = 최대 + 1) |
| `get(id) -> Habit \| None` | `deleted_at IS NULL`만 |
| `list(statuses=("active",)) -> list[Habit]` | `sort_order` 순 |
| `update(id, **fields, now)`, `set_status(id, status, now)` | 고치기, 상태 바꾸기 |
| `soft_delete(id, now)` | 되돌린 추가 |
| `check(id, day, now) -> bool` | `INSERT … ON CONFLICT DO NOTHING`. 새로 넣었으면 `True` |
| `uncheck(id, day) -> str \| None` | 지운 행의 `checked_at`(되돌리기용), 없었으면 `None` |
| `restore_check(id, day, checked_at)` | 되돌리기 |
| `checked_on(day) -> set[int]` | 그날 체크한 습관 id |
| `week_counts(week_start) -> dict[int, int]` | 그 ISO 주의 습관별 체크 수 |
| `checks_between(id, from_, to) -> list[date]` | 습관 화면의 지난 4주(5.5 `GET /habits/{id}`) |

모든 쓰기는 `with transaction(self.conn):`(SP3-4 4.3)이다.

### 5.3 날짜 규칙

- 체크 날짜 기본값은 논리적 오늘(SP1의 04:00 경계). 자정이 지나 저녁 체크인에 답해도 그 체크인의 날짜다(아래 5.7).
- **오늘 포함 7일**(오늘과 그 앞 6일)만 체크·취소할 수 있다. 미래 날짜는 거절("아직 오지 않은 날은 체크할 수 없어요."), 7일보다 앞은 거절("오늘 포함 7일 안의 날만 체크할 수 있어요."). 지난 날짜를 받는 이유: 노트북이 꺼져 있었거나 며칠 뒤에 생각난 경우.
- `paused`, `archived` 습관은 체크·취소를 거절한다("쉬는 중인 습관이에요. 다시 시작하면 체크할 수 있어요.").
- 습관을 추가한 날 이전 날짜도 7일 안이면 받는다(추가하기 전에 이미 한 날을 남길 수 있게).

### 5.4 두뇌 도구 (MCP `planner`)

| 도구 | 입력 | 하는 일 | ToolEvent / 활동 `kind` |
|---|---|---|---|
| `add_habit` | title, area, kind(`daily` \| `weekly`), target_per_week?(weekly일 때 1~6) | 추가. **사용자가 직접 추가해 달라고 한 습관에만** 쓴다 | `habit_added` |
| `update_habit` | id, title?, area?, kind?, target_per_week? | 고치기 | `habit_updated` |
| `set_habit_status` | id, status(`active` \| `paused` \| `archived`) | 쉬어 가기·다시 시작·그만두기 | `habit_status_set` |
| `check_habit` | id, date? | 체크. 이미 체크했으면 바꾸지 않고 `{"already": true}` | `habit_checked` |
| `uncheck_habit` | id, date? | 체크 취소. 체크가 없으면 바꾸지 않고 `{"already": true}` | `habit_unchecked` |
| `list_habits` | status?(기본 `active`), date? | 습관과 그날 체크 여부, 그 주 체크 수 | 없음 |

규칙:

- **H1** 입력 검증과 오류 문구는 SP1 도구와 같은 방식(`{"error": "…"}`). 제목은 1~40자, 영역은 6개 중 하나.
- **H2** `kind = daily`에 `target_per_week`가 오면 거절, `weekly`에 없으면 거절("주 몇 번인지 1~6으로 알려 주세요. 매일이면 매일 습관으로 만들어요.").
- **H3** 같은 제목(앞뒤 공백을 뺀 뒤 그대로 비교)의 활성·쉬는 습관이 있으면 `add_habit`, 이름을 바꾸는 `update_habit`, 그만둔 습관의 다시 시작(`set_habit_status(active)`)을 거절한다("이미 있는 습관이에요."). 소프트 삭제된 습관은 없는 습관이다: 도구는 "없는 습관이에요.", `GET /habits/{id}`는 `404 not_found`, 지난 텔레그램 버튼은 "없는 습관이에요."로 알린다.
- **H4** 확인 문구(부록 A): `✓ 습관 추가: 물 마시기 (매일)`, `✓ 습관 추가: 운동 (주 3회)`, `✓ 습관: 물 마시기`(오늘), `✓ 습관: 물 마시기 (10/22)`(지난 날), `↩ 습관 체크 취소: 물 마시기`, `✓ 습관 쉬어 가기: 운동`, `✓ 습관 다시 시작: 운동`, `✓ 습관 그만두기: 운동`, `✓ 습관 고침: 운동 (주 2회)`.
- **H5** 변경 도구는 데이터, `activity`, 경험치 원장을 같은 트랜잭션에서 쓴다(SP3-4 5.2). `add_habit`, `update_habit`, `set_habit_status`는 할 일 도구처럼 `tool_events_log`에도 쓴다(사용자 메시지 다시 넣기, SP1 5.2 `inbound_id`). `check_habit`, `uncheck_habit`은 `record_condition`처럼 `tool_events_log`에 쓰지 않는다: 같은 날짜를 다시 해도 결과가 같고(H6 때문에 회차 차례에는 돌지 않는다), 쓰면 버튼만 누른 회차가 "도구가 이미 돌았다"로 읽힌다(SP3-4 5.2).
- **H6** **회차 차례**(SP3-4 10.1 A1)에서 `check_habit`, `uncheck_habit`, `add_habit`은 거절한다("사용자가 말한 습관만 체크할 수 있어요."). 비서는 습관을 추측해서 체크하지 않는다. 사용자 메시지에 답하는 차례(A3)에서는 바로 적용한다.
- **H7** 회차 차례의 `set_habit_status(archived)`와 `update_habit`은 A2처럼 `needs_confirm`이다(비서가 스스로 꺼낸 그만두기와 목표 바꾸기는 확인 뒤에만). `paused`는 바로 적용한다(쉬는 것은 가볍고 되돌리기 쉽다).
- **H8** 도구 수: 텔레그램 대화 22 + 6 = 28개, 앱 대화 28 + 6 + 화면 1(`ui_habit_check`) = 35개. SP3-4 스파이크 S12(도구 수와 `max_turns`)를 이 수로 다시 확인한다(계획 티켓 00).

### 5.5 HTTP API (SP3-4 6장에 더한다. 모두 필드·경로 추가라 `/api/v1` 그대로)

공통 습관 모양 `Habit`:

```json
{ "id": 3, "title": "운동", "area": "health", "kind": "weekly", "target_per_week": 3,
  "status": "active", "checked": false, "week_count": 2 }
```

- `checked`: 요청 날짜(기본 오늘)에 체크했는가. `week_count`: 그 날짜가 든 ISO 주(`clock.period_of(week, …)`, ISO 연도 기준 `%G-W%V`)의 체크 수. 앱은 `weekly`이고 `week_count >= target_per_week`이면 "이번 주 목표만큼 했어요"를 쓴다(계산은 앱에서, 보상은 없다).

| 메서드 | 경로 | 내용 |
|---|---|---|
| GET | `/today` | 필드 `habits: [Habit]`를 더한다(활성 습관, `sort_order` 순). 활성 습관이 없으면 `[]` |
| GET | `/habits?date=&status=active\|paused\|archived\|all` | `{"date", "week": "2026-W43", "items": [Habit]}`. 기본 `status=active` |
| GET | `/habits/{id}?weeks=4` | `{"habit": Habit, "from", "to", "checked_dates": ["2026-10-22", …], "weeks": [{"week": "2026-W43", "count": 2}]}`. `from` = 오늘이 든 주의 `weeks − 1`주 전 월요일, `to` = 오늘. `weeks` 1~12. `checked_dates`는 체크한 날만, `weeks`는 체크가 있는 주만 준다(빈 날·빈 주는 0이 아니라 없음, `GET /conditions`와 같은 방식). 예: 10/24(토), `weeks=4` → `from` 9/28(월) |
| POST | `/actions` | `action`에 `add_habit`, `update_habit`, `set_habit_status`, `check_habit`, `uncheck_habit`을 더한다. 위험은 모두 `low`이고, `set_habit_status`만 "low. `archived`이면 `confirm`(앱 통로만)"이다(SP3-4 6.4.2 표 형식). `args`는 5.4 도구 입력과 같다 |

- **앱 요청의 확인**: `set_habit_status(archived)`만 `needs_confirm`이다(summary "운동 습관을 그만둘까요? 기록은 남아요."). 앱에서 실수로 누른 그만두기를 막으려는 것이고, 확인 뒤 적용한 그만두기는 SP3-4 규칙대로 되돌릴 수 없지만 습관 화면에서 다시 시작할 수 있다.
- `/actions` 응답의 `xp`는 SP3-4 그대로 `{"gained", "level_up"}`이다. 새 체크면 `gained = 3`, 이미 쌓인 날짜면 `0`.

**되돌리기** (SP3-4 6.4.3 표에 더한다)

| 활동 `kind` | `target` | 되돌리면 |
|---|---|---|
| `habit_added` | `habit:<id>` | 소프트 삭제(`deleted_at`). 그 습관에 `habit_checks` 행이 하나라도 있으면 되돌리기 처리 함수가 직접 `superseded`를 돌려준다(`409`) |
| `habit_updated` | `habit:<id>` | 바뀐 필드를 이전 값으로 |
| `habit_status_set` | `habit:<id>` | 이전 상태. 쉬어 가기·그만두기를 되돌려 `active`로 돌아갈 때 상한 10개는 보지 않는다(이전 상태로 돌아가기만 한다. 그래서 잠깐 11개가 될 수 있고, 그동안 새 추가·다시 시작은 거절된다) |
| `habit_checked` | `habit:<id>:<날짜>` | 체크 행 삭제 |
| `habit_unchecked` | `habit:<id>:<날짜>` | 체크 행 복원(이전 `checked_at`) |

- 체크 활동은 대상 `habit:<id>:<날짜>` 하나만 적는다(보기만 하는 대상 `WATCH_ONLY_TARGETS`는 쓰지 않는다). 그래서 같은 날짜의 체크·취소끼리만 U3로 서로 막고, 다른 날짜의 체크끼리는 막지 않는다(월요일 체크를 화요일 체크 뒤에도 되돌릴 수 있다). `habit_updated`, `habit_status_set`의 U3는 `habit:<id>`만 보므로 체크와 서로 막지 않는다.
- 체크·취소의 되돌리기는 5.3의 거절(쉬는 습관, 7일 범위)을 보지 않는다. 그 사이 쉬어 가기를 했어도, 8일째여도 24시간 안이면 이전 상태로 돌린다(U2).
- 경험치는 그대로 둔다(U6).

### 5.6 경험치 (SP3-4 9.1에 한 줄을 더한다)

| # | 언제 | 경험치 | `source_kind` / `source_ref` | 한 번만 |
|---|---|---|---|---|
| X11 | 습관 체크 | 3 | `habit_check` / `habit:<id>:<날짜>` | 습관·날짜마다 |

- 원장의 `logical_date`는 **체크한 날짜**다(지난 날 체크는 그날의 경험치). `at`은 지금 시각.
- **주간 목표 보상을 두지 않는 이유**: "이번 주 안에 N번 채우면 보너스"는 그 주가 지나면 얻을 수 없는 기간 한정 보상이라 ADR 0006과 SP3-4 9.1에 걸린다. 주 목표는 앱의 글("이번 주 목표만큼 했어요")로만 알린다.
- 원장 CHECK 변경은 5.1의 SQL이다. 원장 행이 그대로 옮겨지는지 테스트한다(12장).
- `status/xp.py`에 `XP_HABIT_CHECK = 3`, 라벨 "습관 체크". 상태창 "최근 경험치" 줄에 습관 제목은 넣지 않는다(SP3-4 원칙 그대로).
- **쉬는 날(X9)은 그대로다**: 습관만 체크한 날도 완료한 할 일이 없으면 쉬는 날 경험치를 받는다.
- 한 주의 예상: 매일 습관 3개(63) + 주 3회 습관 하나(9) ≈ 72. 할 일 위주의 주 350보다 작게 두어 습관이 레벨을 끌고 가지 않게 했다(숫자는 제안값, 15장).
- **놓쳐도 줄지 않는다**: 체크 취소, 쉬어 가기, 그만두기 모두 원장을 건드리지 않는다.

### 5.7 회차와 텔레그램

**저녁 체크인 습관 버튼**

- `evening_checkin` 회차(합친 회차 포함)이고 활성 습관이 하나 이상이면, 하네스가 메시지 아래 버튼에 습관 줄을 붙인다. 날짜 `habit_date`는 `ask_condition_for(run, merged)`의 값이다. 월말 회고와 합쳐 사다리 줄이 붙느라 컨디션 버튼 날짜를 `None`으로 바꾸는 경우(`dispatcher._prepare_run`)에도 **바꾸기 전의 값**을 쓴다. 그래서 저녁 체크인이면 늘 그 체크인의 날짜다.
- 버튼 순서(`telegram_io.message_keyboard`): 할 일 초안 → 사건 초안 → 챕터 초안 → 확인 줄(SP3-4 A5) → **습관 줄** → 컨디션 `1`~`5` 또는 사다리 줄. 일요일 저녁 체크인이 월말 회고와 합쳐져 사다리 줄이 붙어도 습관 줄은 그 앞이다. 습관은 한 줄에 둘씩, 글자는 `☐ {제목 10자}` / `✓ {제목 10자}`(넘으면 9자 + `…`).
- 콜백 `hb:<habit_id>:<YYYY-MM-DD>`. 누르면 하네스가 즉시 갈래로 토글한다(체크돼 있으면 `uncheck_habit`, 아니면 `check_habit`, `actor = user`, `channel = telegram`). 그리고 그 메시지의 버튼만 다시 그린다: `query.message.reply_markup`을 복사하고, 그 안의 **모든** `hb:` 버튼 글자(`☐`/`✓`)를 지금 DB의 `checked_on(날짜)`로 다시 정해 `editMessageReplyMarkup`으로 보낸다(앱이나 `/habits`로 먼저 체크한 습관도 맞게 보인다. 본문과 다른 버튼은 그대로 복사한다. 버튼 재료 `Outbound`는 저장되지 않으므로 다시 만들지 않는다). 다시 그리기 직전에 그 회차가 앱에서 먼저 답해져 버튼이 거둬졌으면(`runs.answered_via = app`, SP3-4 6.4.5) 다시 그리지 않는다. 그 사이의 아주 짧은 경합으로 거둔 버튼이 다시 보일 수 있는 것은 받아들인다(누르면 지금 상태로 토글될 뿐이다). 같은 모양이라 텔레그램이 "message is not modified"를 돌려주면 잡고 넘어간다. 알림 문구는 확인 문구 한 줄(H4).
- `Outbound`와 `_ResendJob`에 `habit_date: date | None`을 더해 5분 뒤 다시 보내기(SP1 5.4-2)에도 습관 줄이 붙는다. `TelegramSender` 생성자에 `habits: HabitsRepo | None`을 더하고, `message_keyboard(out, …)`가 `out.habit_date`가 있을 때 `habits.list()`와 `habits.checked_on(out.habit_date)`로 습관 줄을 만든다(`tasks`, `curve`를 받는 지금 방식과 같다).
- 콜백 날짜는 `_ISO_DATE.fullmatch`로 검사하고, `bot/callbacks.py` 머리 주석의 콜백 목록에 `hb:`를 더한다. `hb:<id>:<날짜>`는 20바이트 남짓이라 64바이트 상한 안이고, 챕터 `h:`(정확히 `parts[0] == "h"`)와 겹치지 않는다.
- 누름은 그 회차의 **답으로 친다**(SP3-4 6.4.5 "답으로 치는 것"에 습관 버튼을 더한다. X3 경험치도 같다). 앱에서도 `check_habit`·`uncheck_habit`의 날짜가 답장 창 안 저녁 체크인의 날짜이면 답으로 친다(`record_condition`과 같은 규칙). 그래서 앱에서 먼저 습관을 체크하면 SP3-4 규칙대로 텔레그램의 그 회차 버튼(습관 줄 포함)이 거둬진다. 받아들인다: 같은 습관을 앱이나 `/habits`로 계속 체크할 수 있다.
- 쉬는 중이거나 그만둔 습관의 지난 버튼을 누르면 바꾸지 않고 "쉬는 중인 습관이에요."라고 알린다.
- 두뇌에게는 `## 습관 버튼` 메모를 붙인다(`_condition_buttons_note`와 같은 자리): "메시지 아래에 오늘 습관 버튼이 붙습니다. 습관을 글로 하나하나 묻지 말고, '오늘 챙긴 습관은 아래에서 눌러 주세요'처럼 한 줄로 부탁합니다."

**`/habits` 명령** (SP1 5.6 표에 더한다, 두뇌를 거치지 않음)

- `bot/commands.py`의 `COMMANDS`에 `/habits`를 더한다. `run_command`는 지금처럼 글(`str`)만 돌려주고, 텔레그램 갈래(`telegram_io._answer_command`)만 `/habits`일 때 위와 같은 습관 버튼(`hb:<id>:<오늘>`)을 붙여 보낸다. 앱 통로(`POST /chat`)의 `/habits`는 같은 글만 답한다(앱에는 습관 블록이 있다).
- 오늘 날짜의 활성 습관 목록과 같은 토글 버튼을 보낸다. 본문: `오늘 습관 (10/24 토)` 다음 줄마다 `- 운동 · 이번 주 2번 / 목표 3번`, 매일 습관은 `- 물 마시기`. 습관이 없으면 "아직 습관이 없어요. '매일 물 마시기 습관 추가해 줘'처럼 말하면 만들어 드려요."
- `/help` 목록에 `/habits — 오늘 습관 체크`를 더한다.

**두뇌 앞머리와 회고**

- 저녁 체크인과 대화의 앞머리(`harness/context.py`)에 `## 오늘 습관` 블록을 더한다: 활성 습관마다 `- 물 마시기 (매일): 오늘 ✓` / `- 운동 (주 3회): 이번 주 2번`. 습관이 없으면 블록을 넣지 않는다.
- 주간 회고 회차의 앞머리에는 `## 이번 주 습관`을 더한다: 습관마다 그 주 체크 수와 목표. 지난 4주 수도 함께(`3·2·3·0번`, 오래된 주부터, 0인 주 포함. 이 숫자는 두뇌에게만 주고 앱 화면에는 0인 주를 쓰지 않는다).
- 아침 브리핑에는 넣지 않는다(Dahun Q3).

**프롬프트 원칙** (`system.md`에 더할 원칙 12~14)

12. 습관은 사용자가 한 것만 체크한다. 체크한 것만 말하고, 하지 않은 습관을 세거나 "끊겼다", "며칠째 안 했다"고 말하지 않는다.
13. 주간 회고에서 습관은 "이번 주에 한 것"으로 돌아본다. (주 단위 횟수는 0인 주도 앞머리에 준다. 금지하는 것은 날 단위로 빠진 날을 세는 일이고, 주 횟수는 목표를 맞추려는 신호로만 쓴다.) 한 주에 한 번도 안 한 습관이 2주 넘게 이어지면 목표를 줄이거나 쉬어 가기를 **질문으로** 제안한다(먼저 바꾸지 않는다, H7).
14. 새 습관이 도움이 될 것 같으면 말로 제안하고, 사용자가 원할 때 `add_habit`을 부른다.

### 5.8 내보내기와 원문 기록

- 변경 도구 호출 뒤 `data/exports/habits.md`를 다시 만든다(ADR 0003): 활성·쉬는·그만둔 묶음, 습관마다 지난 4주 체크 수.
- 원문 기록: 텔레그램 버튼은 `[버튼] 습관 체크 물 마시기` / `[버튼] 습관 체크 취소 물 마시기`(SP1 5.8의 `[-]` 줄).

## 6. 운영 앱

SP5 5장의 토큰, 부품, 문구 규칙을 그대로 쓴다. 운영 앱 스레드가 진행 중인 테마 프리셋·조각 체계가 들어오면 그 토큰을 따른다.

### 6.1 오늘 화면 습관 블록 (SP5 5.5.1 표의 5번 컨디션과 6번 할 일 사이)

| 블록 | 데이터 | 동작 |
|---|---|---|
| "습관" 머리 + 오른쪽 "관리" 링크(`/habits/`) | `/today.habits` | |
| 습관 줄(52px): 왼쪽 체크 원(44px 누름 영역), 제목, 오른쪽 회색 메타 | `Habit` | 줄을 누르면 `check_habit` / `uncheck_habit`(날짜 = `/today.date`). 응답 뒤 `GET /today`를 다시 읽는다(SP5 6장) |

- 메타 글: 주 N회 습관은 `이번 주 2번 · 목표 3번`, 채웠으면 `이번 주 목표만큼 했어요`. 매일 습관은 `이번 주 4번`. 비율, 막대, 남은 횟수("1번 남음")는 쓰지 않는다.
- 체크한 줄은 원이 검정으로 채워지고 제목은 그대로다(할 일처럼 취소선을 긋지 않는다. 습관은 끝나는 것이 아니다).
- 활성 습관이 없으면 블록 대신 한 줄 "습관 추가하기"(회색, `/habits/`로).
- 오프라인(SP5 5.5.4): 줄은 보이고 체크 원은 입력이 아닌 그림이 된다. 스냅샷(`GET /today`)에 `habits`가 들어 있으므로 따로 저장하지 않는다.

### 6.2 습관 화면 (`/habits/`, 탭 밖, "‹ 오늘")

질문: **어떤 습관을 챙기고 있고, 자리 잡고 있나?**

| 블록 | 데이터 | 동작 |
|---|---|---|
| 큰 제목 "습관" + 오른쪽 추가 버튼(44px 원) | | 추가 시트 |
| 챙기는 습관 | `GET /habits` | 줄을 누르면 그 습관의 상세 시트 |
| 쉬는 습관 (있을 때만) | `GET /habits?status=paused` | 줄마다 "다시 시작" |
| 그만둔 습관 (있을 때만, 접힘) | `GET /habits?status=archived` | 줄마다 "다시 시작" |

- **상세 시트**: 제목, 영역, 주기, 그리고 **지난 4주 점 격자**(`GET /habits/{id}?weeks=4`): 7칸 × 4줄, 3주 전 월요일부터 이번 주 일요일까지. 칸마다 작은 회색 날짜 숫자만 있고, 체크한 날에만 검정 점을 찍는다. 안 한 날은 아무것도 그리지 않는다(빈 원, X, 빨강을 쓰지 않는다. 빈 원·X를 그리면 놓친 날 표시가 되므로, 10장). 오늘은 숫자를 진하게, 오늘 뒤의 칸은 숫자도 옅게. 아래에 체크가 있는 주만 `이번 주 2번`, `지난주 3번`, `10월 5일 주 1번` 같은 글. 버튼: "고치기", "쉬어 가기"(또는 "다시 시작"), "그만두기"(빨강 글자, BE가 `needs_confirm`을 주면 SP5의 확인 시트).
- 격자 칸을 누르면 그날을 체크·취소한다(오늘 포함 7일만 누를 수 있고, 그보다 앞 칸과 오늘 뒤 칸은 보기만 한다).
- **추가·고치기 시트**: 제목(필수, 40자), 영역(6개 알약 중 하나), 주기(분할 버튼 "매일" · "주 N회"), 주 N회면 1~6 알약. "추가" = `add_habit`, "저장" = `update_habit`.
- 빈 상태: "챙기고 싶은 습관을 더해 보세요. 매일 하는 것도, 주 몇 번 하는 것도 돼요."

### 6.3 체크인 상세 (SP5 5.5.3)

- 저녁 체크인의 `cards`에 `ui_habit_check {date}`가 `ui_condition_picker`(또는 사다리) 앞, `ui_confirm` 뒤에 온다(텔레그램 버튼 줄과 같은 순서)(SP3-4 6.4.5 표에 한 줄 더함: `toolCallId = h_habit_<run_id>`, 재료는 활성 습관, 빠지는 경우는 활성 습관이 없을 때). 이미 다 체크했어도 카드는 남는다(취소할 수 있게).

## 7. 문구

- 금지어(SP5 10장)를 그대로 지킨다: "연속", "스트릭", "달성률", "밀렸다", "놓쳤다", "실패". 이번에 앱·텔레그램·프롬프트 문구 검사 목록에 "끊겼", "며칠째", "남음"을 더한다.
- 새 고정 문구는 부록 A에 모았다(Dahun 확인 필요).

## 8. 보안과 개인정보

- 습관 제목은 할 일 제목과 같은 취급이다: 활동 `summary`와 확인 문구에는 들어가고, 로그에는 넣지 않는다(id와 결과만). 상태창 "최근 경험치"에는 넣지 않는다.
- 새 경로는 SP3-4 6.1의 토큰 인증, CORS, 본문 상한을 그대로 따른다.

## 9. 운영 앱 스레드와 맞출 것 (생성형 UI)

- 카탈로그에 컴포넌트 하나 `ui_habit_check`를 더한다. props `{date: "YYYY-MM-DD"}`(필수 하나). 출처는 `brain`(두뇌가 대화에서 "오늘 습관 보여 줘"에 그릴 수 있다)이고, 하네스도 체크인 카드에 같은 컴포넌트를 쓴다.
- BE가 조각마다 지금 값 `data.habits: [Habit]`를 붙인다(대화 `tool-output-available.output.data.habits`, 체크인 `cards[].data.habits`). 앱은 `data`가 없으면 줄 대신 "오늘 습관" 한 줄과 습관 화면 링크를 보인다.
- 생김새는 6.1의 습관 줄 묶음과 같은 컴포넌트(오늘 블록, 체크인 카드, 대화 세 곳에서 똑같이).
- `pin_card`는 이 컴포넌트를 받지 않는다(오늘 화면에 이미 습관 블록이 있다).
- **완성 카드로 넣는다**: 운영 앱 스레드의 채팅 생성형 UI 스펙(`2026-10-24-sp6-chat-generative-ui-design.md`, 작성 중)의 조각 체계에서 `ui_habit_check`는 "완성 카드" 하나이고, 습관 줄은 그 스펙의 "할 일 줄" 조각과 같은 체크 줄 모양을 쓴다.
- **판 번호는 머지 순서로 정한다**(운영 앱 스레드와 합의, 2026-10-24): 지금 `2026-10-24.2`. 이 기능과 채팅 개편 가운데 BE PR이 먼저 머지되는 쪽이 `.3`을 가져가고, 나중 쪽이 그다음 번호를 쓴다. 옛 앱은 모르는 컴포넌트를 글로 대신 보여 주므로 순서가 바뀌어도 깨지지 않는다(SP3-4 6.4.7).
- **누르기 규칙**(채팅 개편과 같다): 오프라인이면 읽기 전용, 대화 기록에서 다시 불러온 카드(restored)도 읽기 전용이다. 체크는 되돌릴 수 있는 가벼운 동작이라 확인 없이 바로 하고, 알림 줄(토스트)에 "되돌리기"를 붙인다.
- **화면 CSS**: 새 화면·부품의 CSS 모듈은 모두 `pages/_app.tsx`에서 불러온다(페이지 전용 CSS는 CSP 때문에 탭 이동 뒤 빠진다, `check:csp`가 막는다). 색은 테마 토큰(`--hue` 등)만 쓰고, 곧 들어올 색감 프리셋(`:root[data-palette]`)에서도 맞게 보이는지 스냅샷으로 본다.

## 10. 하지 않는 것 (다시 묻지 않게)

- 연속 기록, 최고 기록, 끊김 알림, 놓친 날 표시, 비율·%·진행 막대(ADR 0006).
- 습관을 할 일로 바꾸기, 할 일을 습관으로 바꾸기.
- 시각별 습관 알림.
- 하루 여러 번 세기(물 8잔). 필요해지면 "횟수 습관"으로 따로 설계한다.

## 11. 구현 순서 (계획에서 티켓으로 쪼갠다)

1. 스파이크: S12 도구 수 재확인(35개).
2. 마이그레이션 `012_habits.sql`(원장 CHECK 넓히기 포함) + `HabitsRepo`.
3. 도구 6개 + 확인 문구 + 활동·되돌리기 + 경험치 X11 + 내보내기.
4. API: `/today.habits`, `GET /habits`, `GET /habits/{id}`, `/actions` 다섯 동작, 스키마 재생성.
5. 텔레그램: `/habits`, 저녁 체크인 습관 버튼과 토글, 답으로 치기.
6. 두뇌: 앞머리 블록, 회고 블록, `system.md` 원칙, 회차 차례 규칙(H6·H7).
7. 카탈로그 `ui_habit_check`(운영 앱 스레드와 판 번호 맞춤), 체크인 `cards`.
8. 앱: 오늘 블록, 습관 화면, 상세·추가 시트, 카드 부품, 금지어 검사 확장.

## 12. 테스트

| 묶음 | 명령 | 확인하는 것 (기대: 모두 통과, 실패 0) |
|---|---|---|
| 마이그레이션 | `python -m pytest tests/test_migrations.py -q` | 012 적용 뒤 원장 행 수·id·값이 그대로, `PRAGMA foreign_key_check` 빈 결과, `index_list('status_xp_ledger')`에 `idx_xp_date`, `source_kind` `habit_check`만 더 받음, CHECK(`daily` ↔ `target_per_week IS NULL`), `version.schema = 12` |
| 저장소 | `python -m pytest tests/test_habits_repo.py -q` | 체크 중복 없음, 취소·복원, 주 경계(일요일 23:59 / 월요일 03:59 논리적 날짜), ISO 연도: 2027-01-01(금) → `2026-W53`, 2026-12-28~2027-01-03이 한 주, "빠진 날" 함수가 없음 |
| 도구 | `python -m pytest tests/test_habit_tools.py -q` | H1~H7 전부(회차 차례 거절, `needs_confirm`), 오늘 포함 7일 범위, 상한 10개, 같은 제목 거절(추가·이름 바꾸기·다시 시작), 소프트 삭제된 습관, 확인 문구 |
| 경험치 | `python -m pytest tests/test_habit_xp.py -q` | X11 습관·날짜마다 한 번, 체크 → 취소 → 체크에 3만, 지난 날 체크의 `logical_date`는 그 날짜, 쉬는 날 X9 그대로 |
| 되돌리기 | `python -m pytest tests/test_api_undo.py -q` | 표의 다섯 종류, 다른 날짜 체크끼리 막지 않음, 같은 날짜는 막음, 체크가 있는 습관의 추가 되돌리기는 `409 superseded`, 쉬는 습관의 체크 되돌리기 |
| API | `python -m pytest tests/test_api_habits.py tests/test_api_read.py -q` | `/today.habits`, `GET /habits`(상태 필터), `GET /habits/{id}`(빈 날·빈 주 없음, 10/24 `weeks=4` → `from` 9/28, `weeks` 상한 12, 삭제된 습관 404), `/actions` 앱 그만두기 `needs_confirm`, 시각 UTC, 스키마 재생성 |
| 텔레그램 | `python -m pytest tests/test_habit_buttons.py tests/test_telegram_commands.py -q` | 버튼 순서(사다리 회차 포함)와 두 줄 배치, 토글 후 모든 `hb:` 버튼 글자가 DB 상태로 바뀜(앱에서 먼저 체크한 것 포함), 앱에서 먼저 답한 회차는 다시 그리지 않음, "message is not modified" 무시, 다시 보내기에도 습관 줄, 답으로 침, 쉬는·삭제된 습관 버튼, `/habits` 빈 목록 |
| 두뇌 | `python -m pytest tests/test_prompts.py tests/test_dispatcher_conditions.py -q` | 앞머리 블록 유무, 회고 블록의 4주 수(0 포함), 습관 버튼 메모, 프롬프트 골든 |
| 앱 | `cd web/app && npm test && npm run build && npm run check:csp` | 오늘 블록(체크·메타 문구·빈 상태·오프라인), 습관 화면(격자: 체크한 날만 점, 7일 밖 칸 비활성), 시트, `ui_habit_check` 스키마 검증과 restored 읽기 전용, 밝게·어둡게·프리셋 스냅샷 |
| 문구 | `python -m pytest tests/test_prompts.py -q`(`banned-words` 블록), `cd web/app && npx vitest run src/lib/copy.test.ts` | 금지어 검사에 새 단어 3개, 새 문구 전체 |

## 13. 설정

새 설정은 없다. 상한 10개, 오늘 포함 7일, 경험치 숫자는 코드 상수다(경험치는 SP3-4 9장처럼 `config.toml`로 바꾸지 않는다).

## 14. 마이그레이션과 되돌림

- 012는 앞으로만 간다(SP1·SP3-4와 같다). 적용 전 SP1 백업(`store/backup.py`)이 돈다.
- 습관 기능을 끄고 싶으면 습관을 모두 그만두면 된다(블록이 "습관 추가하기" 한 줄로 줄고 체크인 버튼이 사라진다). 별도 기능 끄기 설정은 두지 않는다.

## 15. 미결 사항 (Dahun 확인)

1. 경험치 숫자: 체크 3(5.6). 주간 목표 보상은 기간 한정 보상이라 두지 않았다. 원하시면 ADR 0006을 고치는 결정이 따로 필요하다.
2. 활성 습관 상한 10개, 체크할 수 있는 날은 오늘 포함 7일(5.1, 5.3).
3. 앱의 그만두기만 확인을 받는다(5.5).
4. 회고에서 2주 넘게 안 한 습관에 목표 줄이기·쉬어 가기를 질문으로 제안한다(5.7 원칙 13).
5. 부록 A 문구.

## 부록 A. 새 고정 문구 (Dahun 확인 필요)

| 자리 | 문구 |
|---|---|
| 확인 문구 | `✓ 습관 추가: {제목} (매일)`, `✓ 습관 추가: {제목} (주 {N}회)`, `✓ 습관: {제목}`, `✓ 습관: {제목} ({M}/{D})`, `↩ 습관 체크 취소: {제목}`, `✓ 습관 쉬어 가기: {제목}`, `✓ 습관 다시 시작: {제목}`, `✓ 습관 그만두기: {제목}`, `✓ 습관 고침: {제목} ({매일 \| 주 N회})` |
| 거절 | "습관은 한 번에 10개까지 챙길 수 있어요. 하나를 쉬어 가거나 그만두면 더할 수 있어요.", "이미 있는 습관이에요.", "아직 오지 않은 날은 체크할 수 없어요.", "오늘 포함 7일 안의 날만 체크할 수 있어요.", "쉬는 중인 습관이에요. 다시 시작하면 체크할 수 있어요.", "주 몇 번인지 1~6으로 알려 주세요. 매일이면 매일 습관으로 만들어요.", "사용자가 말한 습관만 체크할 수 있어요." |
| 확인 요청 | "{제목} 습관을 그만둘까요? 기록은 남아요." |
| 텔레그램 | `/habits` 머리 "오늘 습관 ({M}/{D} {요일})", 빈 목록 "아직 습관이 없어요. '매일 물 마시기 습관 추가해 줘'처럼 말하면 만들어 드려요.", `/help` 줄 "/habits — 오늘 습관 체크" |
| 앱 메타 | "이번 주 {n}번 · 목표 {N}번", "이번 주 목표만큼 했어요", "이번 주 {n}번", "지난주 {n}번", "{M}월 {D}일 주 {n}번" |
| 앱 빈 상태 | "습관 추가하기", "챙기고 싶은 습관을 더해 보세요. 매일 하는 것도, 주 몇 번 하는 것도 돼요." |
| 경험치 라벨 | "습관 체크" |
| 두뇌 메모 | "메시지 아래에 오늘 습관 버튼이 붙습니다. 습관을 글로 하나하나 묻지 말고, '오늘 챙긴 습관은 아래에서 눌러 주세요'처럼 한 줄로 부탁합니다." |

## 변경 기록

- v1 (2026-10-24): 첫 초안. Q1~Q3 Dahun 결정, 나머지는 비서 추천.
- v2.1 (2026-10-24): 습관 ADR 번호를 0011로(자동 복구 ADR 0010과 겹쳐서).
- v2 (2026-10-24): 문서 리뷰 1·2차 반영. 주간 목표 경험치(X12) 삭제(기간 한정 보상), 체크 활동 대상을 `habit:<id>:<날짜>` 하나로, 추가 되돌리기는 체크가 있으면 거절, 텔레그램 버튼 다시 그리기 방법, 앱 체크도 답으로 침, 격자는 체크한 날만 점, `GET /habits/{id}?weeks=`, 원장 옮기기 SQL 전체, 테스트 명령, 습관 카드 순서(컨디션 앞), 다시 그리기는 모든 습관 버튼을 DB 상태로, `/habits` 버튼은 텔레그램 갈래에서.
