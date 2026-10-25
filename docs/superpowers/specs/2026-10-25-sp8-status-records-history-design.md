# SP8 상태창 기록 · 인생 히스토리 상세 설계 (추가 기능)

- 상태: 초안 v2 (검토 1차 반영, SP9 스레드와 맞춤. 나머지는 비서가 정함. Dahun 검토 대기)
- 작성일: 2026-10-25
- 상위 문서: [마스터 설계](2026-10-23-my-planner-master-design.md), [SP3-4 스펙](2026-10-24-sp3-4-life-curve-dashboard-design.md) (BE HTTP API 계약의 정본, 상태창 9장, 곡선 표 5.4), [SP5 운영 앱](2026-10-24-sp5-ops-app-design.md), [SP7 습관](2026-10-24-sp7-habits-design.md)
- 디자인: [`DESIGN.md`](../../../DESIGN.md) "종이와 잉크". 화면 초안: 캔버스 [인생 히스토리 초안](https://claude.ai/artifact/FeapQVZFNFC5Y1sgZw4MqR)의 보드 `HistoryDesktop`, `HistoryPhone`, `Pictograms`, `HomePhone2`(방향 승인, 숫자와 글은 꾸며 낸 것)
- 용어: [`GLOSSARY.md`](../../../GLOSSARY.md) (이번에 "바탕 점수", "활동 보너스", "보이는 스탯", "이룬 순간", "몸 기록", "단축어 토큰", "히스토리", "그때 사다리", "픽토그램" 추가, "사건"에 화면 이름), 결정 기록: [ADR 0013](../../adr/0013-moments-saved-without-confirmation.md) 추가
- 범위: 상태창에 쌓이는 기록 세 가지(영역 활동 → 스탯 보너스, 이룬 순간, 몸 기록)와 대시보드 인생 곡선의 히스토리 탭, 두 웹 앱이 함께 쓰는 픽토그램 28개. BE(SQLite, 하루 끝 작업, 도구 하나, API), 운영 앱(새 상태창 화면), 대시보드(상태창, 곡선 화면)를 다룬다.

## 1. 목표와 완료 조건

Dahun은 상태창이 "분기 회고 때 한 번 매긴 숫자"에서 멈춰 있지 않고, 앱에서 한 일이 미리 쌓여 보이기를 바란다. 그래서 (1) 최근 4주에 손이 간 영역은 스탯이 조금 오르고, 활동이 줄면 천천히 바탕 점수로 돌아온다. (2) 하루가 끝나면 비서가 그날 해낸 일을 0~3줄로 조용히 남긴다. (3) 아이폰 걸음 수와 잠이 건강 스탯의 근거가 된다. 그리고 인생 곡선에서 지금까지 어떻게 살아왔는지를 챕터와 사건의 목록(히스토리)으로 읽고, 화면 곳곳에 픽토그램을 쓴다.

**완료 조건 (수용 기준)**

1. 건강 영역 점수가 4(2026-Q4)이고, 지난 28일 매일 건강 습관을 체크했으면 `GET /status`의 건강 스탯은 `score: 4`, `bonus: 1.5`, `effective_score: 5.5`다. 그 뒤로 아무것도 하지 않으면 보너스는 날마다 조금씩 줄어 24일째(11/18)부터 0.0으로 보이고 28일째에는 셈에서도 빠지며, `effective_score`는 4 아래로 내려가지 않는다(5.4 예 2a, 3).
2. 영역 점수가 하나도 없는 영역도 `bonus`는 계산되지만 `effective_score`는 `null`이고, 화면은 "분기 회고에서 점수를 정하면 더해져요"라고 쓴다.
3. 논리적 날짜가 바뀐 뒤 첫 tick에서 하루 끝 작업이 어제를 정리한다. 그날 끝낸 할 일, 습관 체크, 사용자 메시지가 하나라도 있으면 두뇌가 `save_moments`를 한 번 부르고, 0~3개의 이룬 순간이 확인 없이 저장된다. 아무것도 없는 날은 두뇌를 부르지 않는다. 같은 날을 두 번 정리하지 않는다.
4. 노트북이 3일 꺼져 있다 켜지면, 놓친 날(7일 안)을 오래된 날부터 차례로 정리한다. 하루 두뇌 호출 상한에 10회 여유가 남지 않으면 멈추고 다음 날 이어 간다.
5. 앱 상태창(`/status/`)에서 이룬 순간을 밀어 "숨기기"를 누르면 목록에서 빠지고 알림 줄의 "되돌리기"로 돌릴 수 있다. "지우기"는 확인 시트("이 순간을 지울까요? 되돌릴 수 없어요.") 뒤에 행을 지운다. 대시보드는 읽기만 한다.
6. 이룬 순간은 경험치를 주지 않는다. 원장(`status_xp_ledger`)의 `source_kind`는 바뀌지 않는다(6.6).
7. 이룬 순간의 글은 SQLite에만 있다: 로그, `data/exports/`, 원문 기록, 활동 기록 `summary`, 순간 호출의 Agent SDK 세션 파일(6.3), 텔레그램, 웹 푸시 어디에도 나오지 않는다. 텔레그램 통로의 두뇌(대화·회차의 `get_status`, 회고 앞머리)는 날짜와 개수만 받는다. 글은 운영 앱과 대시보드(API), 그리고 앱 통로의 두뇌에만 간다(로그 검사·통로 테스트, 13장).
8. 아이폰 단축어가 `POST /api/v1/body`에 `BODY_TOKEN`으로 지난 3일의 걸음 수와 잠(분)을 보내면 `body_days`에 저장되고, 걸음 6,000 이상인 날과 잠 7시간 이상인 날이 건강 보너스에 더해진다. `API_TOKEN`으로는 이 경로에 쓸 수 없고, `BODY_TOKEN`으로는 다른 경로를 읽을 수 없다.
9. 대시보드 곡선 화면에 탭 `곡선 | 히스토리`가 있고, 히스토리는 챕터를 최근부터 보여 준다. 챕터마다 해, 그때 사다리 점수, 메모, 추정 표시, 안의 사건(종류 픽토그램, 영역 태그)이 있다. 민감한 사건은 "가려 둔 사건 1개 · 보기" 줄로만 보인다. 거르기(전체/높은 때/힘든 때/전환점), 1994→지금 한눈에 띠, 옆 요약이 있다.
10. 픽토그램 28개는 `web/shared/pictograms.svg` 하나가 원본이고, 앱과 대시보드는 `npm run sync:design`으로 만든 사본을 쓴다. 사본이 원본과 다르면 시험이 실패한다. 이모지 아이콘은 없다.
11. 새 문구 전체(부록 A)가 금지어 검사를 지난다. 보너스가 줄어드는 것을 알리는 문구나 표시(내려가는 화살표, "−0.3"), 비율(%)은 어디에도 없다. 디버프의 ↓는 지금처럼 바탕 점수끼리의 신호로만 쓴다.
12. 13장의 자동 테스트가 모두 통과한다.

## 2. 범위

| 포함 | 제외 (언제) |
|---|---|
| 영역 활동(완료한 할 일, 습관 체크, 몸 기록) → 스탯 보너스, 읽을 때 계산 | 보너스를 원장처럼 저장하기 (하지 않음. P6) |
| 이룬 순간: 하루 끝 작업, 두뇌 도구 `save_moments`, 숨기기·다시 보이기·지우기 | 이룬 순간 고치기(글 바꾸기) (나중. 지금은 지우고 말로 남기면 된다) |
| 몸 기록: `POST /body`, `BODY_TOKEN`, 걸음·잠 두 값 | 심박, 체중, 운동 기록 등 다른 건강 값 (하지 않음. Dahun 결정 5) |
| 상태창 화면: 대시보드 상태창 고침, 운영 앱에 상태창 화면 새로(SP9 "더보기" 화면의 한 줄). 텔레그램 `/status`는 바꾸지 않는다(D7) | 웹 푸시로 순간 알리기 (하지 않음. 하루 3회 상한, P1) |
| 인생 히스토리: 대시보드 곡선 화면 탭, `GET /curve/history`, 사건 `area`, 챕터 `ladder_remembered` | 운영 앱의 히스토리 화면 (나중. 대시보드 먼저) |
| 이미 가져온 시드에 영역·그때 사다리를 채우는 `seed-life --update-history` | 확정한 사건의 영역을 화면에서 고치기 (다음 개정) |
| 픽토그램 28개 스프라이트, 동기화, 쓰는 규칙 | 할 일·습관 줄의 픽토그램, 탭 막대 아이콘 바꾸기 (하지 않음. 조작 아이콘은 `icons.tsx` 그대로) |

## 3. Dahun 결정 (2026-10-25, 결정 카드)

| # | 질문 | 결정 |
|---|---|---|
| D1 | 무엇부터 | 셋 다, 이 순서로: (1) 영역 활동, (2) 이룬 순간, (3) 몸 기록. 티켓을 따로 나눈다 |
| D2 | 영역 활동을 어떻게 쓰나 | 스탯에 자동으로 반영한다 |
| D3 | 활동이 줄면 | 천천히 바탕으로 돌아온다. 보너스는 지난 4주 활동에서만 나오고, 옅어지며 줄고, 분기 회고에서 Dahun이 매긴 점수 아래로 **절대** 내려가지 않는다. 보너스 상한은 바탕 위 +2(비서 제안) |
| D4 | 이룬 순간 | "그냥 백그라운드에서 AI가 알아서 정리하게". 하루가 끝나면 비서가 대화, 끝낸 할 일, 습관 체크에서 정리한다. 묻지 않고 확인 버튼도 없다. 상태창에서 숨기거나 지울 수 있다(비서 약속). 사건(곡선)이 아닌 더 가벼운 종류이고, 사건 초안은 여전히 버튼이 있어야 한다 |
| D5 | 몸 기록 | 비서 추천대로: 아이폰 단축어가 BE에 걸음·잠을 보낸다(PWA는 HealthKit을 읽을 수 없다). 건강 스탯의 근거이고 같은 바탕 + 보너스 규칙을 따른다. 쓰기 경로와 토큰이 필요하고, 단축어는 Dahun이 만든다 |
| D6 | 화면 | 곡선 화면에 `곡선 | 히스토리` 탭, 픽토그램을 곳곳에(28개, 24px, 선 1.75, 이모지 없음). 캔버스 초안 방향 승인 |
| D7 | 텔레그램 (2026-10-25) | 텔레그램은 은퇴할 예정이고 새 기능은 앱 전용이다. 이룬 순간은 운영 앱과 대시보드에서만 보이고, 텔레그램 통로의 두뇌는 날짜와 개수만 받는다. 텔레그램 `/status` 화면에는 새 줄을 더하지 않는다(보너스·순간·몸 기록 모두) |
| — | 그 밖 | 이 문서의 나머지 선택은 비서가 정했고 Dahun 검토 대상이다(17장) |

## 4. 접근안과 선택

| 문제 | 안 | 판단 |
|---|---|---|
| 스탯 보너스 | A. 날마다 보너스를 표에 저장 | 버림. 레벨·스탯은 저장하지 않고 계산한다(SP3-4 5.5, 마스터 P6). 저장하면 할 일 다시 열기·영역 바꾸기 때 고칠 곳이 생긴다 |
| | **B. 읽을 때 지난 28일 데이터로 계산 (선택)** | 선택. 데이터는 수백 행 안이다. 같은 순수 함수를 `/status`와 `get_status`가 쓴다 |
| | C. 영역별 경험치로 쌓기 | 버림. 경험치는 오르기만 하므로 "천천히 바탕으로"(D3)를 만들 수 없다 |
| 이룬 순간 | A. 사건 초안으로 내기 | 버림. 날마다 버튼이 붙으면 누를 거리가 쌓인다(P2). 사건은 인생 단위의 일이다 |
| | **B. 새 표에 확인 없이 저장 (선택)** | 선택(ADR 0013). 숨기기·지우기로 되돌릴 수 있고 경험치·곡선에 닿지 않는다 |
| | C. 기억 카드(SP2)로 두기 | 버림. 기억 카드는 회상용이고 화면에 보이지 않는다. SP2도 아직이다 |
| 몸 기록 | A. PWA가 HealthKit 읽기 | 불가능. 웹에는 HealthKit API가 없다 |
| | **B. 아이폰 단축어 → `POST /body` (선택)** | 선택. 단축어 자동화가 매일 한 번 보낸다. tailnet 안에서만 닿는다 |
| | C. 사용자가 걸음을 직접 말하기 | 버림. 매일 묻게 되고(P1) 근거로 약하다 |

## 5. 1단계: 영역 활동 → 스탯 보너스

### 5.1 척도

- **바탕 점수**는 지금 코드의 스탯 그대로다: 영역마다 가장 최근 분기의 영역 점수(`curve_area_scores.score`, 정수 1~10, 사용자가 매김). `status/snapshot.py _stats`의 `score`다.
- **활동 보너스**는 0.0~2.0, 소수 한 자리다. 같은 1~10 척도 위에 얹는다.
- **보이는 스탯** `effective_score = min(10, 바탕 + 보너스)`, 소수 한 자리. 바탕이 없으면 `null`.
- 바탕과 보너스는 늘 따로 보인다(5.6). 사용자가 매긴 숫자가 계산 값에 묻히지 않게 하려는 것이다.

### 5.2 활동 점수

영역 `a`, 논리적 날짜 `day`의 그날 점수 `p(a, day)`:

| 출처 | 점수 | 셈 |
|---|---|---|
| 끝낸 할 일 | 할 일 하나에 1을 그 할 일의 영역 수 `n`으로 나눠 영역마다 `1/n` | `tasks.status = 'done'`, `deleted_at IS NULL`, 날짜 = `logical_date(completed_at)`. 영역이 없는 할 일은 셈하지 않는다. 첫 걸음도 같다. 우선순위인지는 보지 않는다 |
| 습관 체크 | 체크 하나에 0.5, 그 습관의 영역 | `habit_checks.date`. 쉬는·그만둔 습관의 지난 체크도 센다. 소프트 삭제한 습관(`deleted_at`)은 뺀다 |
| 몸 기록 (3단계, 건강만) | 걸음 ≥ 6,000이면 0.5, 잠 ≥ 420분이면 0.5 | `body_days.date` (7.5) |

- **하루 상한**: `p(a, day) = min(3, 그날 합)`. 하루에 할 일을 몰아 끝낸 날이 4주를 끌고 가지 않게 한다.
- 지금 상태로 센다: 끝냈다가 다시 연 할 일, 영역을 바꾼 할 일은 바뀐 대로 계산된다(저장하지 않으므로 고칠 것도 없다).

### 5.3 공식

오늘(논리적 날짜, SP1의 04:00 경계)을 `T`, `d = (T − day)`의 날 수라고 하면 창은 `d = 0..27`(오늘 포함 28일)이다.

```
w(d)   = (28 − d) / 28                      # 오늘 1, 27일 전 1/28, 28일 전 0
S(a)   = Σ_{d=0..27} p(a, T − d) × w(d)      # 가중 활동 점수
bonus  = round_half_up( min(2, S(a) / 5), 1) # 상한 +2. S = 10이면 상한
effective_score = min(10, base + bonus)      # base 없으면 null
```

- `S`는 `fractions.Fraction`으로 계산하고, 마지막에 `x = min(Fraction(2), S / 5)`를 `(Decimal(x.numerator) / Decimal(x.denominator)).quantize(Decimal("0.1"), ROUND_HALF_UP)`로 반올림한다(`Decimal(Fraction)`은 TypeError다. 부동소수 반올림 오차로 1.45가 1.4가 되지 않게).
- **부드럽게 줄어드는 이유**: 같은 활동의 무게가 날마다 1/28씩 줄어 28일째에 0이 된다. 날마다 보너스가 바뀌는 폭은 대개 0.1~0.2다. 계단처럼 한 번에 떨어지는 날이 없다.
- **바탕 아래로 내려가지 않는 이유**: `p ≥ 0`, `w ≥ 0`이라 `bonus ≥ 0`이다. 보이는 스탯은 언제나 `base` 이상이다.
- 상수(`status/activity.py`): `WINDOW_DAYS = 28`, `TASK_POINT = 1`, `HABIT_POINT = 0.5`, `BODY_STEPS_MIN = 6000`, `BODY_SLEEP_MIN = 420`, `BODY_POINT = 0.5`, `DAY_CAP = 3`, `BONUS_FULL = 10`, `BONUS_MAX = 2`. 경험치 상수처럼 `config.toml`로 바꾸지 않는다.

**ADR 0006과의 관계 (벌이 아니다)**: 보너스가 줄어드는 것은 깎는 장치가 아니다. (1) 줄어도 사용자가 매긴 바탕 점수 아래로는 가지 않는다. (2) 경험치·레벨·칭호는 건드리지 않는다. (3) 줄었다고 알리지 않는다: 화면에 내려가는 표시(아래 화살표, "−0.3", "줄었어요"), 지난주 보너스와의 비교, 남은 날 수가 없다. 보너스는 "요즘 손이 간 곳"을 보여 주는 표시이고, 손이 덜 간 곳은 바탕 점수로 보일 뿐이다. 디버프는 지금처럼 바탕 점수끼리만 비교한다(보너스는 디버프를 만들지도 지우지도 않는다).

### 5.4 계산 예 (오늘 = 2026-10-25 일요일)

| # | 상황 | `S` | `bonus` | 보이는 스탯 |
|---|---|---|---|---|
| 1 | 커리어 할 일(영역 하나)을 지난 4주 월·수·금마다 하나씩, 12개. 바탕 6 | 5.79 | 1.2 | 7.2 |
| 2 | 건강 습관을 28일 매일 체크(0.5 × 28일). 바탕 4 | 7.25 | 1.45 → **1.5** | 5.5 |
| 2a | 2처럼 하다 10/25 뒤로 아무것도 안 함. 10/28 / 11/1 / 11/8 / 11/17 / 11/18 / 11/22 | 5.80 / 4.13 / 1.88 / 0.27 / 0.18 / 0 | 1.2 / 0.8 / 0.4 / 0.1 / 0.0 / 0.0 | 5.2 / 4.8 / 4.4 / 4.1 / 4.0 / 4.0 |
| 2′ | 2에 더해 매일 걸음 ≥ 6,000 (하루 1.0) | 14.5 | 2.0 (상한) | 6.0 |
| 3 | 2′처럼 하다 10/25 뒤로 아무것도 안 함. 10/28 / 11/1 / 11/8 / 11/15 / 11/21 / 11/22 | 11.6 / 8.25 / 3.75 / 1.0 / 0.04 / 0 | 2.0 / 1.7 / 0.8 / 0.2 / 0.0 / 0.0 | 6.0 / 5.7 / 4.8 / 4.2 / 4.0 / 4.0 |
| 4 | 오늘 하루에 건강 할 일 10개 | 3 (하루 상한) | 0.6 | 바탕 + 0.6 |
| 5 | 오늘 커리어·배움 두 영역의 할 일 하나 | 각 0.5 | 각 0.1 | 각 바탕 + 0.1 |
| 6 | 10/25 02:30(한국)에 끝낸 할 일 | 논리적 날짜 10/24, `d = 1`, 무게 27/28 | | |
| 7 | 바탕 9, 보너스 1.5 | | 1.5 | 10.0 (10을 넘지 않음. `bonus`는 1.5 그대로) |
| 8 | 영역 점수가 없는 영역, 보너스 1.2 | | 1.2 | `null` ("점수를 정하면 더해져요") |

### 5.5 가장자리

- **영역 점수가 아직 없음**: `score`, `effective_score`는 `null`, `bonus`와 `activity`는 그대로 준다. 상태창의 "요즘 손이 간 영역"에는 나오고, 스탯 줄에는 "분기 회고에서 점수를 정하면 더해져요".
- **할 일 영역이 여럿**: 위 표처럼 `1/n`씩 나눈다. 영역을 많이 붙여도 할 일 하나의 힘은 1이다.
- **04:00 논리적 날짜**: 할 일은 `completed_at`(UTC)을 `clock.logical_date`로 바꾼 날짜, 습관 체크는 저장된 날짜(이미 논리적 날짜), 몸 기록은 보낸 날짜(아이폰의 달력 날짜, 7.3). 창의 시작은 `T − 27`의 04:00(한국)이고, 질의는 그보다 하루 넉넉히 읽고 파이썬에서 거른다.
- **분기가 바뀜**: 새 분기 영역 점수를 매기면 바탕이 바로 바뀌고 보너스는 같은 창에서 계속 계산된다. 지난 분기 점수만 있으면 지금처럼 그 분기 표시와 함께 바탕으로 쓴다.
- **멈춤(`/pause`) 기간**: 셈은 그대로다. 쉬는 동안 보너스가 옅어지는 것도 바탕 아래로 가지 않는다.
- **설치 직후**: 지난 28일 데이터가 이미 있으면 바로 보너스가 보인다(SP1부터의 할 일·SP7 습관 체크를 쓴다).

### 5.6 저장소, 계산 자리, API

- `status/activity.py`: 순수 함수 `area_points(tasks, checks, body, today, *, tz, boundary) -> dict[area, dict[date, Fraction]]`(하루 상한을 적용한 점수, 할 일 날짜는 `logical_date(completed_at, tz, boundary)`), `activity_counts(tasks, checks, body, today, *, tz, boundary) -> dict[area, ActivityCounts]`(창 안의 가중하지 않은 개수: 상한을 적용한 점수에서는 다시 셀 수 없어 따로 센다), `area_bonus(points, today, counts) -> dict[area, Bonus]`(`Bonus(score_s, bonus, counts)`, 영역 6개 모두). 입출력 없음. (SP8 계획 결정 4)
- `store/repos/status.py`에 읽기 함수 `activity_rows(from_utc, from_day, to_day) -> ActivityRows`: 끝낸 할 일과 영역(`task_areas`, `completed_at >= from_utc`, 호출 쪽이 `T − 28`의 04:00(한국)을 넘겨 하루 넉넉히 읽는다), 습관 체크와 습관 영역(`from_day = T − 27` ~ `to_day = T`), 몸 기록. 쓰기는 없다. `body_days`는 SP8-06(014)에서 생기므로 SP8-00의 `activity_rows`는 몸 기록을 `[]`로 돌려주고 `activity.body_days`는 늘 0이다. 몸 기록 질의는 SP8-06이 더한다.
- `status_snapshot`의 `stats[]`에 필드를 더한다(필드 추가라 `/api/v1` 그대로, 기존 `score`의 뜻은 바뀌지 않는다):

```json
{ "area": "health", "label": "건강", "score": 4, "period": "2026-Q4",
  "prev_score": 6, "prev_period": "2026-Q3", "debuff": true, "recovery_quest": "저녁에 20분 걷기",
  "bonus": 1.5, "effective_score": 5.5,
  "activity": {"tasks": 0, "habit_checks": 28, "body_days": 0} }
```

- `bonus`: 0.0~2.0 숫자. `effective_score`: 숫자 또는 `null`. `activity`: 지난 28일 동안 그 영역의 끝낸 할 일 수, 습관 체크 수, 몸 기록이 셈에 든 날 수(건강만, 다른 영역은 0). **가중하지 않은 개수**이고 화면의 보조 글에 쓴다.
- 두뇌 `get_status`도 같은 스냅샷을 쓴다(10.3). 텔레그램 `/status`는 SP8에서 바뀌지 않는다(D7).
- `GET /schema`를 다시 만들고 앱·대시보드 `types.gen.ts`를 다시 생성한다.

## 6. 2단계: 이룬 순간

### 6.1 `013_moments.sql`

```sql
-- 013: 이룬 순간 (SP8 스펙 6.1, ADR 0013). 개인 글이라 이 DB에만 둔다(내보내기·로그·원문 기록·활동 summary 없음).
CREATE TABLE status_moments (
    id           INTEGER PRIMARY KEY,
    date         TEXT NOT NULL CHECK (date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),  -- 논리적 날짜
    slot         INTEGER NOT NULL CHECK (slot BETWEEN 1 AND 3),
    text         TEXT NOT NULL CHECK (length(text) BETWEEN 1 AND 60),
    area         TEXT NULL CHECK (area IS NULL OR area IN
        ('career', 'finance', 'health', 'relationships', 'learning', 'quality_of_life')),
    sources_json TEXT NOT NULL DEFAULT '[]',   -- ["task:12", "habit:3", "condition", "chat"]. 글은 넣지 않는다
    hidden_at    TEXT NULL,                    -- 숨김. NULL이면 보인다
    created_at   TEXT NOT NULL,
    UNIQUE (date, slot)
);
CREATE INDEX idx_moments_date ON status_moments (date);

CREATE TABLE status_moment_days (            -- 날마다 정리했는지(중복 방지, 따라잡기)
    date        TEXT PRIMARY KEY,
    state       TEXT NOT NULL CHECK (state IN ('pending', 'done', 'empty', 'failed')),
    saved       INTEGER NOT NULL DEFAULT 0,  -- 처음 저장한 개수. 지워도 그대로(다시 만들지 않는 근거)
    attempts    INTEGER NOT NULL DEFAULT 0,
    updated_at  TEXT NOT NULL
);
```

- `state`: `pending`(아직, 또는 다시 해 볼 것), `done`(두뇌가 정리함, 0개 포함), `empty`(데이터가 없어 두뇌를 부르지 않음), `failed`(두 번 해도 안 됨. 다시 하지 않는다).
- 원장 표, 곡선 표는 건드리지 않는다. 적용 뒤 `version.schema`는 13이다.

### 6.2 하루 끝 작업과 따라잡기

1. **언제**: 하루 한 번 작업(`Runner._run_daily`, 논리적 날짜가 바뀐 뒤 첫 tick, 대개 04:00 직후)에 `queue_moments`를 더한다. 이 작업은 두뇌를 직접 부르지 않고, 정리할 날을 골라 디스패처에 `_MomentsJob(date)`을 넣는다.
2. **어느 날**: 어제부터 거꾸로 7일(`MOMENTS_LOOKBACK_DAYS = 7`)까지, `app_state.moments_since`(처음 작업이 돈 날의 전날) 이후, `status_moment_days`에 행이 없거나 `pending`인 날. 오래된 날부터 넣는다. 7일보다 오래된 날은 고르지 않는다(행도 만들지 않는다). 노트북이 일주일 넘게 꺼져 있었으면 그 앞날은 정리되지 않을 뿐이다(SP1 따라잡기와 같은 생각).
3. **데이터가 없는 날**: 그날 끝낸 할 일, 습관 체크, 사용자 메시지가 모두 없으면 두뇌를 부르지 않고 `empty`로 적는다. 컨디션만 있는 날도 `empty`다(순간으로 쓸 거리가 아니다). SP7은 7일 전까지 지난 날 체크를 받지만, `empty`나 `done`으로 적은 날에 나중에 체크가 생겨도 **다시 정리하지 않는다**(의도: 한 날은 한 번만 정리하고 지난 날을 다시 들추지 않는다).
4. **차례**: 디스패처의 직렬 작업자가 처리하되, **가장 낮은 차례**다. 기다리는 사용자 메시지나 회차가 있으면 그것을 먼저 한다. 한 번에 한 날씩.
   - **실행 직전에 다시 읽는다**: `_MomentsJob`은 두뇌를 부르기 직전에 그날의 `status_moment_days.state`를 다시 읽고, `done`·`empty`·`failed`이면 아무것도 하지 않는다(대기열에 남은 작업이 다음 날 작업과 겹쳐도 두뇌 호출을 쓰지 않는다).
   - 대기열은 메모리에만 있다. 재시작으로 작업이 사라지면, 그날 하루 작업은 이미 돌았으므로(`last_daily_jobs_date`) 다음 날 작업이 `pending`이거나 행이 없는 날을 다시 고른다.
5. **두뇌를 부르지 않고 멈추는 경우**(행은 `pending` 그대로, `attempts`도 그대로, 다음 날 작업이 다시 고른다): 그날 두뇌 호출 수 ≥ `daily_brain_calls − 10`(사용자 몫 10회를 남긴다), 로그인·결제 문제(`brain.auth`가 `ok`가 아님), 사용 한도 대기(`limited_until`), 안전 모드.
6. **결과 판정**: 성공과 실패는 두뇌의 상태(`BrainResult.status`)가 아니라 **호출이 끝난 뒤 그날의 `status_moment_days.state`**로 정한다.
   - `done`이면 성공이다(두뇌가 `max_turns`나 오류로 끝났어도). `attempts`는 그대로다.
   - 두뇌가 `rate_limited`나 `auth_error`로 끝나고 아직 `pending`이면, 지금 회차와 같이 `_set_limited`와 `brain.auth`를 기록하고, `attempts`는 그대로 두고, 그 패스의 남은 날을 멈춘다.
   - 그 밖에 아직 `pending`이면(오류, 시간 초과, `max_turns`, 모두 M1·M2 오류로 저장 못 함) `attempts + 1`. 2회가 되면 `failed`로 바꾼다. `failed`로는 `pending` 행만 바꾼다(`UPDATE … WHERE state = 'pending'`). 그래서 이미 `done`인 날이 덮이지 않는다.
   - 회차처럼 사용자에게 알리지 않는다.
7. 멈춤(`/pause`) 중에도 정리한다. 보내는 메시지가 없어서 하루 3회 상한(`daily_proactive_messages`)에 들지 않는다.

### 6.3 두뇌 호출과 도구 계약

- **호출 모양**: 새 세션(`session_id = None`, 이어 쓰지 않음), `RunContext(kind = "moments", run_id = None, inbound_id = None)`, 지시문은 `harness/prompts/moments.md` 하나(`system.md`의 대화 원칙은 싣지 않는다. 금지어 블록만 하네스가 붙인다), `max_turns = 3`(첫 `save_moments`가 M2 오류를 받아도 고쳐 다시 부르고 끝맺을 턴이 남게), 입력 중 표시는 보내지 않는다. 호출은 하루 두뇌 호출 수에 든다(`brain_calls`).
- **세션 저장을 끈다**: 순간 호출은 이어 쓰지 않으므로 `ClaudeAgentOptions.extra_args = {"no-session-persistence": None}`로 CLI가 세션 jsonl(`~/.claude/projects/…`)을 쓰지 않게 한다. 설치된 판(`requirements.lock`의 `claude-agent-sdk==0.2.173`)에서 확인한 것: SDK는 `extra_args`의 값이 `None`인 열쇠를 `--<flag>`로 그대로 넘기고(`_internal/transport/subprocess_cli.py`), 함께 든 CLI는 `--no-session-persistence`("sessions will not be saved to disk and cannot be resumed")를 안다. 도움말은 "`--print`에서만"이라고 하지만, SDK가 쓰는 모양(`--output-format stream-json --input-format stream-json`, `--print` 없음)에 이 플래그를 붙여 띄워 보니 거절 없이 시작했다. 그래서 **플래그 방식을 고른다**(호출 뒤 파일 지우기는 쓰지 않는다). 실제로 파일이 안 생기는지는 로그인한 두뇌로만 볼 수 있으므로 SP8-03 첫 단계 스파이크 S-SP8-1과 노트북 수용(SP8-11)에서 "순간 호출 뒤 `~/.claude/projects` 아래에 새 파일이 없다"를 확인한다. 스파이크가 실패할 때만 "호출 뒤 그 `session_id`의 jsonl을 지운다"로 바꾸고 이 절을 고친다. 대화 호출은 지금처럼 세션을 저장한다(이어 쓰기 때문, SP1).
- **도구**: 이 호출에는 `mcp__planner__save_moments` **하나만** 준다(ADR 0005 그대로: 파일·셸·웹 없음). `save_moments`는 대화 도구 목록에 없다(텔레그램 28개, 앱 35개 그대로, S12 재확인 불필요).
- **입력**(하네스가 지시문 뒤에 붙인다):

```
## 날짜
2026-10-24 (토)

## 끝낸 할 일
- [task:12] 포트폴리오 사례 2번 다듬기 · 커리어
- [task:15] 고정비 적기 · 경제

## 체크한 습관
- [habit:3] 물 마시기 · 건강

## 컨디션
4/5

## 사용자 메시지 (두 통로, 오래된 것부터)
- 14:02 드디어 사례 하나 끝냈다
```

  - 끝낸 할 일은 그날 논리적 날짜에 끝낸 것(초안·소프트 삭제 뺌) 최대 20개, 습관 체크는 그날 것 전부, 사용자 메시지는 그날 원문 기록(`TranscriptStore.read_range`, 이미 `redact()`를 거친 글)의 **사용자 줄만**, 합쳐 6,000자(넘으면 오래된 줄부터 뺀다). 비서의 말은 넣지 않는다(비서가 한 말이 사용자의 순간이 되지 않게).
  - 대괄호 안의 참조(`task:<id>`, `habit:<id>`)와 `condition`, `chat`이 `sources`에 쓸 수 있는 값의 전부다.
  - **메모(SP9)는 입력이 아니다**: SP9 "앱 탭·메모·일정"의 메모는 Dahun이 직접 쓰는 글이고 이룬 순간과 따로다. 하루 끝 작업은 메모를 읽지 않고, 순간과 메모는 서로를 가리키지 않는다(열쇠도 `sources` 값도 없다).
- **도구 입력**:

| 도구 | 입력 | 하는 일 |
|---|---|---|
| `save_moments` | `date`(YYYY-MM-DD), `moments`: 0~3개의 `{text, area?, sources}` | 그날의 이룬 순간을 저장하고 그날을 `done`으로 적는다. 0개도 된다 |

- **인터페이스**(코드로 막는다. 프롬프트에 맡기지 않는다):
  - `domain.RunContext`에 `kind: Literal["chat", "run", "moments"] = "chat"`을 더한다(회차 호출은 `"run"`). 순간 호출의 활동 통로는 `activity_channel = "scheduler"`다.
  - `Brain.run(prompt, *, session_id, run_ctx, fork_session=False, system_prompt=None, max_turns=None, persist_session=True)`: 앞의 넷은 지금 그대로이고, `ClaudeBrain`은 `system_prompt`가 있으면 `system.md` 대신, `max_turns`가 있으면 설정값 대신 쓰고, `persist_session=False`면 `extra_args`에 `no-session-persistence`를 넣는다. 시험용 두뇌(`tests/fakes.py`)도 같은 인자를 받는다.
  - `mcp_adapter.tool_names_for`(지금은 `channel`을 받는다)를 `RunContext`를 받게 바꾸고, `ctx.kind == "moments"`이면 `["save_moments"]`만 돌려준다. 다른 `kind`에는 `save_moments`를 넣지 않는다. `build_planner_tools`가 이 목록만 서버에 싣는다. 그래서 순간 호출에서 다른 도구를 부르려 해도 서버에 없다.
  - `Tools.save_moments(ctx, date, moments)`는 `ctx.kind != "moments"`이면 `{"error": "쓸 수 없는 도구예요."}`(두 번째 방어).
- **검증**(하네스, 도구 안):
  - M1 `date`는 이 작업의 날짜와 같아야 한다. 아니면 `{"error": "이 날짜만 정리할 수 있어요."}`.
  - M2 `moments`는 0~3개. `text`는 앞뒤 공백을 뺀 1~60자, 줄바꿈·제어 문자 없음. `area`는 6개 영역 중 하나이거나 없음. `sources`는 1~5개이고 모두 입력에 나온 참조여야 한다. 어기면 아무것도 저장하지 않고 오류를 돌려준다("이룬 순간은 하루 3개까지예요.", "근거로 쓸 수 없는 항목이 있어요."). 두뇌는 같은 호출 안에서 고쳐 다시 부를 수 있다(`max_turns = 3`). 끝까지 저장하지 못하면 그날은 `pending`으로 남고 6.2-6을 따른다.
  - M3 금지어(`ui.banned_words()`, SP5 10장 + 이번에 더하는 말, 9.4)가 든 항목은 그 항목만 버린다(오류로 돌려주지 않는다. 버린 수만 로그에).
  - M4 그날이 이미 `done`이면 바꾸지 않고 `{"already": true}`.
  - M5 저장과 `status_moment_days(done, saved = n)`, 활동 한 줄(`moments_saved`)은 한 트랜잭션이다(SP3-4 4.3 단일 작성자: 두뇌 갈래의 도구 쓰기).
- **두뇌가 도구를 한 번도 부르지 않고 `ok`로 끝남**: 하네스가 `done`, `saved = 0`으로 적는다("쓸 거리가 없었다"로 본다). `save_moments`를 불렀지만 모두 M1·M2 오류였으면 `pending` 그대로다(6.2-6).
- **`moments.md` 지시문의 규칙**(요지, 전문은 SP8-03에서 프롬프트 골든과 함께):
  1. 그날 사용자가 **한 일, 해낸 일, 이어 간 일, 즐긴 일**만 쓴다. 하지 않은 일, 못 한 일, 비교("지난주보다"), 횟수 세기("3일째")는 쓰지 않는다.
  2. 한 줄 60자 안, 해요체 과거형("포트폴리오 사례 하나를 끝까지 다듬었어요"). 숫자는 사용자 데이터에 있는 것만.
  3. 0~3개. 억지로 채우지 않는다. 평범한 날은 0개도 괜찮다.
  4. 병명·진단, 금액, 다른 사람의 이름이나 사적인 일은 쓰지 않는다.
  5. 할 일 제목을 그대로 베끼기보다 무엇을 해냈는지로 쓴다. 근거가 된 참조를 `sources`에 넣는다.
  6. 반드시 `save_moments`를 한 번 부른다(0개여도). 글로 답하지 않는다.

### 6.4 숨기기, 지우기, 보관

| 동작 | 어디서 | 위험·확인 | 되돌리기 | 활동 `kind` / `target` / `summary` |
|---|---|---|---|---|
| 숨기기 `hide_moment {id}` | 운영 앱 상태창 | low | 24시간 안 되돌리기(다시 보임) | `moment_hidden` / `moment:<id>` / "이룬 순간 숨김 (10/24)" |
| 다시 보이기 `unhide_moment {id}` | 앱 "숨긴 순간" 묶음 | low | 되돌리기(다시 숨김) | `moment_unhidden` / 같음 / "이룬 순간 다시 보임 (10/24)" |
| 지우기 `delete_moment {id}` | 앱 상태창 | `confirm`(앱 통로 `needs_confirm`) | 없음(행을 지운다) | `moment_deleted` / 같음 / "이룬 순간 지움 (10/24)" |
| 정리(하루 끝 작업) | 디스패처 | low, `actor = secretary`, `channel = scheduler` | 없음(숨기기·지우기로) | `moments_saved` / `moments:<date>` / "이룬 순간 {n}개 정리 (10/24)" |

- 모두 `POST /actions`(SP3-4 6.4.2)의 새 `action`이다. 확인 요청 summary: "이 순간을 지울까요? 되돌릴 수 없어요."
- **활동 `summary`에 순간의 글을 넣지 않는다**(날짜만). 할 일 제목은 `summary`에 들어가지만, 이룬 순간은 비서가 대화에서 뽑은 개인 글이라 더 좁게 다룬다(1장 완료 조건 7).
- 지운 날은 다시 정리하지 않는다(`status_moment_days.state = done` 그대로). "다시 정리해 줘" 기능은 없다.
- 이미 지운 순간을 가리키는 동작은 `404 not_found`, 이미 숨긴 순간의 숨기기는 바꾸지 않고 `{"already": true}`.
- **보관**: 지우기 전까지 둔다(기록을 쌓아 두려는 것이 D4의 뜻이다). 숨긴 순간도 그대로 둔다. `status_moment_days`는 60일이 지난 행을 하루 한 번 작업에서 지운다(글이 없는 관리용 행이고, 7일 창 밖이다).
- **사람용 md 없음**: ADR 0003(SQLite가 원본, md는 사람용)의 예외다. 이룬 순간은 `data/exports/`에 내보내지 않는다. DB 백업(`store/backup.py`)에는 SQLite 파일째 들어간다.
- 텔레그램에서는 숨기거나 지울 수 없다(텔레그램에는 글을 보내지 않는다, 6.7). 대화에서 "그 순간 지워 줘"라고 하면 두뇌는 "앱 상태창에서 밀어서 지울 수 있어요"라고 안내한다(`system.md` 원칙 15).

### 6.5 API

| 메서드 | 경로 | 내용 |
|---|---|---|
| GET | `/status` | 필드 `moments: [Moment]`(지난 14일, 숨기지 않은 것, 최근 날짜부터, 같은 날은 `slot` 순, 최대 20개)와 `moments_hidden: n`(같은 14일의 숨긴 수)을 더한다 |
| GET | `/moments?before=YYYY-MM-DD&days=14&include_hidden=false` | `{"from", "to", "items": [Moment]}`. `to` = `before`의 전날(없으면 오늘), `from` = `to − (days − 1)`. `days` 1~60. `include_hidden=true`면 숨긴 것도 `hidden: true`로 |
| POST | `/actions` | `hide_moment`, `unhide_moment`, `delete_moment`(`args: {"id"}`) |

공통 모양 `Moment`:

```json
{ "id": 41, "date": "2026-10-24", "text": "포트폴리오 사례 하나를 끝까지 다듬었어요", "area": "career",
  "sources": ["task"], "hidden": false }
```

- `sources`는 참조의 **종류만** 준다(`task`, `habit`, `condition`, `chat`, 중복 없이). id는 주지 않는다(그 사이 지운 할 일을 가리킬 수 있다).
- 되돌리기 표(SP3-4 6.4.3)에 `moment_hidden`(`hidden_at`을 NULL로), `moment_unhidden`(이전 `hidden_at`으로)을 더한다. 대상 `moment:<id>`가 같으면 U3로 서로 막는다. `moment_deleted`, `moments_saved`는 `not_undoable`.
- 대시보드는 `GET /status`의 `moments`만 읽는다(쓰지 않는다).

### 6.6 경험치: 주지 않는다

이룬 순간은 경험치를 주지 않는다. 원장 `source_kind`도 바꾸지 않는다.

- **두 번 세지 않는다**: 순간의 근거(할 일 완료 X1·X2, 습관 체크 X11, 컨디션 X4)는 이미 경험치를 받았다.
- **비서의 판단이 레벨을 정하지 않게**: 순간은 두뇌가 0~3개를 고른다. 경험치를 주면 같은 하루라도 두뇌가 몇 개를 썼는지에 따라 레벨이 달라진다. 경험치는 사용자가 한 일에만 쌓는다(ADR 0006의 white-hat 동기: 자기 행동이 그대로 보상이 된다).
- **오르기만 하는 원장과 맞지 않는다**: 순간은 지울 수 있다. 지운 순간의 경험치를 남기면 이상하고, 빼면 ADR 0006(경험치는 줄지 않는다)을 어긴다.
- 그 대신 순간은 상태창에 "이룬 순간"으로 보이는 것 자체가 보상이다. 칭호도 주지 않는다(칭호는 확정한 사건에만, SP3-4 9.4).

### 6.7 사건(곡선)과의 관계

- 하루 끝 작업은 사건 초안을 **만들지 않는다**. `save_moments` 말고 다른 도구가 없다.
- 순간에서 사건이 되는 길은 지금의 초안 + 버튼 흐름 하나뿐이다: 대화(또는 주간 회고)에서 두뇌가 순간을 보고 "곡선에 높은 때로 남길까요?"라고 묻고, 사용자가 원하면 `add_milestone`(초안) → `✓ 저장` / `✗ 빼기`(SP3-4 11.3). 초안 만료(3일)도 그대로다.
- 이것을 위해 두뇌가 순간을 보는 자리는 둘이다: `get_status` 결과의 `moments`(지난 7일만, 10.3)와 주간 회고 앞머리 `## 이번 주 이룬 순간`. **글은 앱 통로(`RunContext.channel == "app"`)에서만 준다.** 텔레그램 통로에서는 둘 다 날짜와 개수만 주므로(D7) 순간에서 사건을 묻는 일은 앱 대화와 앱으로 보낸 회고에서만 일어난다. 회차 차례에서는 묻기만 하고, `add_milestone`은 사용자가 답한 차례에 부른다(SP3-4 10장 원칙 9 그대로).
- 순간과 사건 사이에 연결 키를 두지 않는다. 같은 일이 순간과 사건 둘 다로 남아도 괜찮다(층이 다르다: 하루와 인생).

### 6.8 비용과 로그

- 하루 1회 호출(데이터가 있는 날만), 입력은 지시문 약 1,500자 + 데이터 최대 약 7,000자, `max_turns = 3`. 노트북이 켜지면 최대 7회(따라잡기). 하루 상한 60회 중 사용자 몫 10회를 늘 남긴다.
- 로그: `moments_job` 한 줄에 `date`, `state`, `saved`, `rejected`(M3로 버린 수), `duration_ms`만. 두뇌 호출 로그(`brain_call`)는 지금 규칙 그대로(본문·도구 인자 없음, `tool_names`에 `save_moments`). 순간의 글, 할 일 제목, 메시지는 남기지 않는다.

## 7. 3단계: 몸 기록 (아이폰 단축어)

### 7.1 `014_body.sql`

```sql
-- 014: 몸 기록 (SP8 스펙 7.1). 걸음 수와 잠(분) 두 값만. 56일 지난 행은 하루 한 번 작업이 지운다.
CREATE TABLE body_days (
    date          TEXT PRIMARY KEY CHECK (date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    steps         INTEGER NULL CHECK (steps IS NULL OR steps BETWEEN 0 AND 100000),
    sleep_minutes INTEGER NULL CHECK (sleep_minutes IS NULL OR sleep_minutes BETWEEN 0 AND 1440),
    updated_at    TEXT NOT NULL,
    CHECK (steps IS NOT NULL OR sleep_minutes IS NOT NULL)
);
```

- 보관 56일(`BODY_KEEP_DAYS`): 보너스 창(28일)과 화면(지난 7일)에 넉넉하다. 몸 기록은 쓸 만큼만 둔다.

### 7.2 경로와 토큰

`POST /api/v1/body` (아이폰 단축어용)

- **토큰**: `.env`의 `BODY_TOKEN`(`python -m my_planner gen-token`으로 하나 더 만든다, 43자 이상). `Authorization: Bearer <BODY_TOKEN>`.
  - 이 경로는 `BODY_TOKEN`만 받는다. `API_TOKEN`은 `401`이다. `BODY_TOKEN`은 다른 모든 경로에서 `401`이다(쓰기 하나만 되는 좁은 토큰: 폰 단축어에 넣어 두는 값이라 새어도 걸음 수를 덮어쓰는 것 말고는 할 수 없다).
  - `BODY_TOKEN`이 없거나 43자 미만이거나 `API_TOKEN`과 같으면 이 경로를 열지 않는다(`404`, 경고 `body_token_missing` 한 줄). 다른 경로는 그대로다.
  - 인증 실패 세기(1분 10회 → `429`)는 다른 경로와 함께 센다. 비교는 `hmac.compare_digest`.
  - **구현 규칙**: 지금 `auth` 미들웨어(`api/server.py`)는 토큰 하나(`deps.token`)만 비교한다. 이것을 "경로 틀로 기대 토큰을 고른다"로 바꾼다: `route_template(request) == "/api/v1/body"`이면 `deps.body_token`, 그 밖은 `deps.token`. 다른 쪽 토큰은 맞는 값이어도 `401`이다. 경로가 꺼져 있으면(`body_token` 없음) 이 경로를 등록하지 않으므로, `API_TOKEN`을 보내면 `auth`를 지난 뒤 라우팅이 `404`를 주고 `BODY_TOKEN`만 보내면 먼저 `401`이다.
  - `record_body_days`는 `ACTIONS`의 동작이지만 `/actions`에서 부를 수 없다: `_callable_from`이 이 동작을 `/body` 처리 함수가 만드는 요청(`channel = "body"`)에서만 받는다. 그래서 `API_TOKEN`으로 `/actions`를 거쳐 몸 기록을 쓸 수 없다(1장 완료 조건 8).
- **닿는 길**: 지금 경로들과 같다. 아이폰 Tailscale이 켜져 있을 때 `https://<노트북>.<tailnet>.ts.net/api/v1/body`. 브라우저가 아니라서 CORS 미들웨어는 이 경로를 건너뛴다(CORS 헤더를 붙이지 않고 사전 요청 `OPTIONS`도 받지 않는다).
- **중복 방지**: `client_msg_id`를 받지 않는다(SP3-4 6.1의 쓰기 규칙의 예외). 같은 날짜를 다시 보내면 덮어쓰므로 결과가 같다. 단축어에는 UUID 만들기가 마땅치 않다.
- **본문 상한** 4KB: 이 경로에만 둔다(`body_limit` 미들웨어가 경로 틀이 `/api/v1/body`이면 4KB, 그 밖은 지금의 `api.max_body_kb`).
- **쓰기 길**: 즉시 갈래(`apply_action("record_body_days", …)`, `actor = user`, 요청 `channel = "body"`)로 단일 작성자를 지킨다. 활동 기록은 남기지 않는다(날마다 같은 줄이 쌓여 기록 화면을 덮는다. 고칠 수도 되돌릴 수도 없는 센서 값이다). 경험치도 주지 않는다(사용자가 한 행동이 아니라 자동 전송이다).

### 7.3 본문과 검증

```json
{ "days": [
    {"date": "2026-10-24", "steps": 8123, "sleep_minutes": 412},
    {"date": "2026-10-23", "steps": 5310},
    {"date": "2026-10-25", "sleep_minutes": 395}
] }
```

- **날짜의 뜻**: `steps`는 그 달력 날(아이폰 기준 00:00~24:00)의 걸음 합. `sleep_minutes`는 **그 날 아침에 끝난 밤**의 잠든 시간 합(깨어 있음·침대에 있음 제외). 04:00 논리적 날짜와 몇 시간 어긋나는 것은 받아들인다(걸음은 대부분 낮에 걷는다).
- **검증**(하나라도 어기면 아무것도 쓰지 않고 `400 invalid_request`, `message`에 한 줄):
  - 최상위 키는 `days` 하나. 다른 키가 있으면 거절("걸음 수와 잠만 받아요.").
  - `days` 1~7개, 날짜가 겹치지 않음.
  - 항목 키는 `date`, `steps`, `sleep_minutes`만. `steps`나 `sleep_minutes` 중 하나는 있어야 한다. `null`은 받지 않는다(빼면 그 값은 그대로 둔다).
  - `date`는 `YYYY-MM-DD`, **한국 달력의 오늘**(`Asia/Seoul` 자정 기준, 논리적 날짜가 아니다) 이하, 그 오늘 − 13일 이상("지난 14일 안의 날만 받아요."). 00:00~03:59에 손으로 돌려도 아이폰의 오늘 날짜가 미래로 거절되지 않게 한다. 그 시각에 받은 오늘 날짜는 그 날짜 그대로 저장하고, 보너스 셈(5.2)에서는 `d = −1`이라 창 밖이다가 04:00 뒤 `d = 0`이 된다.
  - `steps`는 정수 0~100,000, `sleep_minutes`는 정수 0~1,440.
- **쓰기**: 날짜마다 `INSERT … ON CONFLICT(date) DO UPDATE`로 보낸 값만 바꾼다. 한 요청은 한 트랜잭션.
- **응답** `200`: `{"saved": 3}`. 값은 돌려주지 않는다.
- **로그**: 경로 틀과 상태 코드(SP3-4 14장), 그리고 `body_received {days: n}`. 걸음·잠 숫자는 로그에 없다.

### 7.4 건강 보너스에 들어가는 길

- 5.2 표의 셋째 줄 그대로: 날마다 걸음 ≥ 6,000이면 0.5, 잠 ≥ 420분이면 0.5. 건강 영역의 그날 점수에 더해 하루 상한 3 안에서 합친다. 같은 바탕 + 보너스 규칙이다(D5).
- `stats[health].activity.body_days`: 지난 28일 중 둘 중 하나라도 점수를 낸 날 수.
- 기준에 못 미친 날은 0점일 뿐이다. "부족", "목표" 같은 말은 쓰지 않는다.

### 7.5 데이터가 없을 때

- 행이 없으면 건강 보너스는 할 일·습관에서만 나온다. 아무것도 깎이지 않는다.
- `GET /status`의 `body`는 지난 56일에 행이 없으면 `null`. 있으면:

```json
{ "last_date": "2026-10-24", "days_7": 6, "steps_avg_7": 6800, "sleep_avg_7": 410 }
```

  `days_7`: 지난 7일 중 행이 있는 날 수. `steps_avg_7`, `sleep_avg_7`: 그 값이 있는 날만의 평균(정수, 없으면 `null`).
- 화면: 대시보드는 `body`가 `null`이면 건강 근거 줄을 그리지 않는다. 앱은 연결 안내 한 줄을 보인다(부록 A). 마지막 기록이 오래돼도 경고하지 않고 "마지막 기록 10/20"만 쓴다.
- 노트북이 꺼져 있던 날: 단축어 요청이 실패한다. 단축어는 매일 지난 3일을 다시 보내므로 사흘 안의 빈칸은 다음 날 채워진다.

### 7.6 Dahun이 할 설정 (README "iPhone 단축어" 절로 옮긴다, SP8-07)

1. 노트북에서 `python -m my_planner gen-token` → 나온 값을 `.env`에 `BODY_TOKEN=…`으로 넣는다(`API_TOKEN`과 다른 값). 작업 스케줄러에서 my-planner를 다시 시작한다. `/health`는 그대로 `ok`.
2. 아이폰에서 Tailscale이 켜져 있는지 본다(운영 앱이 열리면 된다).
3. 단축어 앱 › 새 단축어 "몸 기록 보내기":
   1. **건강 샘플 찾기**: 유형 "걸음", 시작일 "최근 3일", 일별로 묶기 → 날마다 합계.
   2. **건강 샘플 찾기**: 유형 "수면 분석", 값 "잠듦", 시작일 "최근 3일" → 끝난 날짜별로 지속 시간(분)을 더한다.
   3. 두 결과로 `days` 목록(사전 목록)을 만든다. 날짜는 형식 `yyyy-MM-dd`.
   4. **URL 콘텐츠 가져오기**: URL `https://<노트북>.<tailnet>.ts.net/api/v1/body`, 방법 POST, 헤더 `Authorization: Bearer <BODY_TOKEN>`, `Content-Type: application/json`, 본문 JSON `{"days": …}`.
4. 단축어를 한 번 손으로 실행해 건강 접근("걸음", "수면")을 허용한다. 결과에 `{"saved": n}`이 보이면 된다. 운영 앱 상태창의 몸 기록 줄이 바뀐다.
5. 단축어 › 자동화 › 새 개인용 자동화 › "특정 시간" 매일 09:00 › "바로 실행"(묻지 않기) › "몸 기록 보내기".
6. 이 단축어는 **공유하지 않는다**. 단축어는 iCloud로 기기 사이에 동기화되고, 공유하면 헤더의 `BODY_TOKEN`도 함께 나간다. 새었다고 생각되면 11장 `BODY_TOKEN` 줄의 절차(새 값 → `.env` → BE 다시 시작 → 단축어 헤더 고침)로 바꾼다. README에도 이 두 문장을 적는다.

정확한 단축어 동작 이름과 수면 합산 순서는 SP8-07에서 실제 아이폰으로 만들어 보고 README에 화면 순서대로 적는다(이 절은 그 뼈대다).

## 8. 인생 히스토리 (대시보드)

### 8.1 `015_curve_history.sql`

```sql
-- 015: 히스토리용 칸 (SP8 스펙 8.1). 둘 다 비워 둘 수 있다. 시드 가져오기와 대화 초안이 채운다.
ALTER TABLE curve_milestones ADD COLUMN area TEXT NULL CHECK (area IS NULL OR area IN
    ('career', 'finance', 'health', 'relationships', 'learning', 'quality_of_life'));
ALTER TABLE curve_chapters ADD COLUMN ladder_remembered INTEGER NULL
    CHECK (ladder_remembered IS NULL OR ladder_remembered BETWEEN 0 AND 10);  -- 그 시기를 돌아보며 기억하는 사다리 칸
```

- SQLite의 `ADD COLUMN`은 CHECK를 받고 기존 행(NULL)에 대해 검사한다. 표를 옮기지 않는다. 적용 뒤 `version.schema`는 15다.
- 사건의 `area`는 **하나**다(할 일과 달리). 사건은 삶의 한 장면이라 대표 영역 하나로 충분하고, 히스토리 태그가 한 줄에 들어간다.
- `ladder_remembered`는 히스토리의 "그때 사다리 6"이다(캔버스 `HistoryDesktop`). 월별 사다리 점수(`curve_ladder_scores`)는 비서를 쓰기 시작한 뒤에만 있으므로, 지난 시기에는 기억하는 점수 하나가 필요하다.

**누가 채우나**

| 길 | `curve_milestones.area` | `curve_chapters.ladder_remembered` |
|---|---|---|
| 시드 가져오기 `seed-life` | `events[].area?`(6개 영역 코드. 틀리면 그 항목 `invalid`) | `chapters[].ladder?`(정수 0~10) |
| 이미 가져온 시드 `seed-life --update-history <파일> [--dry-run]` | `origin = seed`이고 `area IS NULL`인 사건을 `date_text`와 `title`이 같은 시드 항목으로 찾아 채운다 | `seed_key`로 찾고 `NULL`일 때만 채운다 |
| 대화 사건 초안 `add_milestone` | 새 입력 `area?`. 두뇌는 사용자의 말에서 영역이 분명할 때만 넣는다 | — |
| 연말 회고 챕터 초안 `propose_chapter` | — | 새 입력 `ladder?`. 사용자가 **말한 숫자만**(SP3-4 원칙 10) |

- `--update-history`에서 `date_text + title`이 같은 시드 항목이 둘 이상이면(또는 DB에 그런 사건이 둘 이상이면) 그 항목은 건너뛰고 이유 `ambiguous`로 센다.
- `--update-history`는 `life_seed_imported_at`이 있어도 돈다. 이미 값이 있는 칸은 덮어쓰지 않는다. 같은 잠금(`state/my-planner.lock`), 같은 확인 규칙(민감·`storage` 항목은 `confirmed: true`일 때만), 같은 출력 규칙(개수와 이유별 개수만, 내용 없음)이다. 끝나면 `app_state.life_seed_history_updated_at`을 적고, 다시 돌리면 코드 4.
- 확정한 사건의 영역을 화면이나 말로 고치는 길은 이번에 없다(2장 제외).
- 사건 초안 버튼(텔레그램 `✓ 저장: {제목}`)과 확인 문구는 바뀌지 않는다. 영역이 있으면 확정 문구 끝에 영역을 붙인다: "✓ 저장: 제주 여행 (2019, 높은 때, 삶의 질)".

### 8.2 API

**`GET /curve`** (필드 추가): `milestones[]`에 `area`(또는 `null`), `origin`(`seed` | `chat` | `review`)과 `kind_certainty`, `chapters[]`에 `ladder_remembered`(또는 `null`).

**`GET /curve/history?include_sensitive=false`** (새 경로, 대시보드용)

```json
{
  "since_year": 1994,
  "chapters": [
    { "id": 5, "title": "지금", "theme": null, "start": "2026-10", "end": null, "sketch": "…",
      "certainty": "fact",
      "ladder": {"value": 6, "source": "remembered"},
      "events": [ {"id": 31, "date": "2026-10", "precision": "month", "kind": "turning_point",
                   "kind_certainty": "fact", "title": "…", "note": "…", "area": "quality_of_life",
                   "origin": "chat", "certainty": "fact", "sensitive": false} ],
      "hidden_sensitive": {"count": 0, "years": []} }
  ],
  "unassigned": { "events": [], "hidden_sensitive": {"count": 0, "years": []} },
  "summary": { "chapters": 5, "events": 10,
               "highest": {"chapter_id": 2, "title": "…", "ladder": 6},
               "turning_points": {"count": 4, "years": [2012, 2019, 2023, 2026]},
               "longest": {"chapter_id": 1, "title": "…", "years": 19},
               "records_since": 2026 }
}
```

- 확정한 챕터·사건만. 챕터는 `start` 최근부터, 사건은 챕터 안에서 `sort_date` 최근부터. `chapter_id`가 없는 사건은 `unassigned`.
- `ladder`: `ladder_remembered`가 있으면 `{"value", "source": "remembered"}`. 없고 그 챕터 기간에 월별 사다리 `now`가 있으면 그 평균(소수 한 자리) `{"value", "source": "recorded"}`. 둘 다 없으면 `null`.
- `include_sensitive=false`(기본): 민감 사건은 `events`에서 빼고 `hidden_sensitive`에 개수와 해(중복 없이, 오름차순)만 준다. `true`면 `events`에 `sensitive: true`로 넣고 `hidden_sensitive`는 `{"count": 0, "years": []}`.
- `summary`: `chapters`, `events`(보이는 사건 수. 민감 사건은 `include_sensitive=true`일 때만 셈), `highest`(`ladder.value`가 가장 큰 챕터, 같으면 최근 챕터, 없으면 `null`), `turning_points`(보이는 전환점 수와 해), `longest`(기간이 가장 긴 챕터, 해 수는 `end − start`를 달로 센 뒤 12로 나눠 반올림, 끝나지 않은 챕터는 오늘까지), `records_since`(첫 컨디션 또는 사다리 기록의 해, 없으면 `null`). `since_year`: 가장 이른 챕터 시작 또는 사건의 해.
- 6.2 경로표에 더한다: `GET /curve/history` · 대시보드 · 쓰기 없음. 대시보드가 쓰는 `GET`은 일곱 개가 된다.

### 8.3 히스토리 탭 화면 (`/curve`, 캔버스 `HistoryDesktop`, `HistoryPhone`)

- **탭**: 곡선 화면 머리 아래 분할 버튼 `곡선 | 히스토리`(각 픽토그램 `curve`, `list`). 고른 탭은 주소 `?tab=history`로 남긴다(정적 내보내기에서도 된다. 새로 고침해도 같은 탭). 기본은 곡선. 머리 부제: "지금까지 걸어온 길 · 챕터 {n}개 · 사건 {m}개 · {since_year}년부터".
- **데스크톱(720px 이상)**: 왼쪽 본문(챕터 목록), 오른쪽 옆 요약(8.6). 한눈에 띠는 옆 요약 맨 위. **폰**: 한눈에 띠 → 거르기 → 챕터 목록 → 옆 요약 순으로 한 열.
- **챕터 하나**(종이 위에 이어지는 목록, 카드 상자 없음):
  - 머리 줄: 픽토그램 `chapter`, 제목(`headline`), 해 "2019 – 2022"(끝나지 않으면 "2026 –"), 추정이면 태그 `estimate` "추정".
  - 둘째 줄(`caption`, `--muted`): `ladder` 픽토그램 + "그때 사다리 6"(`remembered`) 또는 "사다리 평균 6.3"(`recorded`), " · 사건 {n}개".
  - 메모 줄: `sketch`. 없고 추정 챕터면 "기억으로 그린 시기예요."
  - 사건 줄(52px 이상): 왼쪽 36px 원(`--raised`) 안에 종류 픽토그램(`high`, `low`, `turning_point`), 제목(`body`), 날짜 "2019.03"(해만 기억하면 "2018"), 메모(`caption`), 태그들: 종류 이름("높은 때", 종류가 추정이면 "높은 때 · 추정"), 영역 태그(영역 픽토그램 영역색 + 영역 이름 `--text-2`), `origin = chat`이면 `assistant` 픽토그램 + "비서가 만듦"(`--hue`, DESIGN.md "비서가 한 일에만"). 사건 날짜 자체가 추정이면 날짜 앞에 "추정".
  - 줄을 누르면 지금의 사건 팝오버(`MilestonePopover`)를 연다.
- **폰의 오래된 챕터**: 최근 챕터 4개만 펼치고, 그 앞은 접힌 줄 "{제목} · {해} 더 보기"로 보인다. 누르면 펼친다(그 탭에서만 기억).
- **정렬**: 오른쪽 위 글자 버튼 "최근부터 ▾" ↔ "오래된 것부터 ▾". 기본 최근부터. 저장하지 않는다.
- **빈 상태**: 챕터와 사건이 모두 없으면 "시드를 가져오거나 대화에서 사건을 남기면 여기에 쌓여요."
- `unassigned`가 있으면 맨 끝(정렬이 오래된 것부터면 맨 앞)에 묶음 "시기를 정하지 않은 사건".

### 8.4 거르기

- 알약 넷(44px, `aria-pressed`): "전체"(`list`), "높은 때"(`high`), "힘든 때"(`low`), "전환점"(`turning_point`). 하나만 고른다. 기본 전체.
- 브라우저에서 거른다(같은 응답). 고른 종류의 사건이 없는 챕터도 머리 줄은 남기고 사건 자리에 "이 시기에는 고른 종류의 사건이 없어요."(지나온 길이 끊겨 보이지 않게).
- 거르기와 정렬은 그 탭에서만 기억한다(곡선 탭의 확대 단위 기억과 같은 방식, `localStorage`에 두지 않는다).

### 8.5 민감한 사건

- 기본은 가린다(`include_sensitive=false`). 챕터 안 사건 자리 끝에 한 줄: `eyeoff` 픽토그램 + "가려 둔 사건 {n}개 · {해들}" + 글자 버튼 "보기".
- "보기"를 누르면 `include_sensitive=true`로 한 번 다시 받아 **그 챕터의** 민감 사건만 펼친다. 펼친 민감 사건 줄에는 태그 `eye` "민감"이 붙고, 줄 끝 글자 버튼 "가리기"로 다시 접는다.
- 위쪽 거르기 줄 끝의 토글 "민감한 사건 가림"(켜짐이 기본)을 끄면 모든 챕터를 펼친다. 이 토글은 곡선 탭의 "민감한 사건 보기"와 **같은 상태**(그 탭에서만 유지, 저장하지 않음, SP3-4 13.4)다.
- 한눈에 띠와 옆 요약은 가린 사건을 그리거나 세지 않는다(펼쳤을 때만).
- 민감 사건의 제목·메모는 펼치기 전 응답에 들어 있지 않다(BE가 빼고 준다). 브라우저에 남지 않게 하려는 SP3-4 14장 원칙 그대로다.

### 8.6 한눈에 띠와 옆 요약

- **한눈에 띠**(제목 "한눈에 보는 지난 길", 부제 "챕터마다 기억한 사다리 점수와 사건이에요. 점선은 기억으로 그린 시기예요."): 맨 SVG(`viewBox` 폭 = 실제 폭). x축은 `since_year`부터 오늘까지, 눈금은 첫 해, 10년 단위, 올해. 챕터마다 기간 폭의 `--raised` 띠(1px `--rule` 테두리, 추정 챕터는 점선 테두리)와 그 안의 짧은 가로선 하나(높이 = `ladder.value` 0~10, 2px `--text`, 없으면 선 없음). 사건은 띠 위 그 날짜 자리에 16px 종류 픽토그램(`--text`). 곡선 아래 칠하기, 영역색 면은 없다(DESIGN.md). 같은 내용의 화면 읽기용 표(챕터, 해, 사다리, 사건 수)를 함께 둔다.
- **옆 요약**(목록 줄, `caption` 머리 + `headline` 값): `level` "가장 높았던 챕터 · {제목} · 사다리 {n}", `turning_point` "전환점 · {n}번 · {해들}", `chapter` "가장 길었던 챕터 · {제목} · {n}년", `review` "기억과 기록 · {records_since}년부터는 매일 기록으로 그려요". 값이 `null`인 줄은 뺀다. 맨 아래 도움 상자(`assistant`): "대화에서 나온 일을 사건 초안으로 만들어 두면, 확인 버튼을 눌러야 여기에 올라와요. 지난 챕터도 '이 시기 같이 정리하자'라고 말하면 돼요."
- 비율, 순위표, 점수 비교 문구("가장 낮았던")는 쓰지 않는다.

### 8.7 사건 종류 이름 바꾸기

화면 전체에서 사건 종류의 이름을 캔버스 초안대로 바꾼다: 고점 → **높은 때**, 저점 → **힘든 때**, 전환점 → 전환점. 바꾸는 곳: 대시보드 `labels.ts kinds`, 앱 사건 초안 카드, 텔레그램 사건 초안·확정 문구, 프롬프트의 예시 말("곡선에 높은 때로 남길까요?"). 칭호 틀은 그대로("「{제목}」의 순간"). 코드 값(`high`, `low`, `turning_point`)과 용어집의 표제어는 바뀌지 않고, 용어집에 화면 이름을 적는다. 곡선 차트의 작은 점 표식 ▲▼◆는 8px 크기에서 알아보기 쉬워 그대로 둔다(픽토그램은 팝오버와 히스토리에). BE·텔레그램·프롬프트 쪽 이름 바꾸기는 SP8-08, 화면 쪽은 SP8-09다(14장).

## 9. 픽토그램

### 9.1 28개

| id | 이름 | 쓰임 |
|---|---|---|
| `career` `finance` `health` `relationships` `learning` `quality_of_life` | 영역 6개 | 영역 태그, 요즘 손이 간 영역, 이룬 순간 줄 |
| `high` `low` `turning_point` | 높은 때, 힘든 때, 전환점 | 사건 줄, 거르기, 한눈에 띠 |
| `chapter` | 챕터 | 챕터 머리, 옆 요약 |
| `condition` | 컨디션 | 한눈에 홈 HP 칸 |
| `ladder` | 사다리 | 그때 사다리, 홈 사다리 칸 |
| `level` | 레벨 | 상태창 레벨, 옆 요약 |
| `quest` | 퀘스트 | 메인·일일 퀘스트 머리 |
| `review` | 회고 | 다음 회고, 기억과 기록 |
| `todo` | 할 일 | 한눈에 홈 우선순위 머리 |
| `habit` | 습관 | 홈 이번 주 습관 머리 |
| `memory` | 기억 | 이룬 순간 머리 |
| `future` | 5년 뒤 | 사다리 5년 뒤 |
| `eye` `eyeoff` | 보임, 가림 | 민감한 사건 |
| `assistant` | 비서가 만듦 | 비서가 만든 사건, 도움 상자 |
| `home` `curve` `status` `list` | 한눈에, 인생곡선, 상태창, 목록 | 대시보드 내비게이션, 탭, 거르기 "전체" |
| `estimate` | 추정 | 추정 태그 |
| `settings` | 설정 | 대시보드 설정 링크 |

모양은 캔버스 `Pictograms` 보드(생성기 `ICONS` 사전)의 그림이 원본 초안이다. 초안 열쇠 `life`는 `quality_of_life`, `turn`은 `turning_point`로 이름을 바꿔 영역·사건 코드 값과 같게 한다.

### 9.2 어디에 두고 어떻게 맞추나 (`global.css`와 같은 방식)

- **원본**: `web/shared/pictograms.svg`. `<svg xmlns="http://www.w3.org/2000/svg">` 안에 `<symbol id="p-<id>" viewBox="0 0 24 24">` 28개. 선 그림만(`path`, `circle`, `rect`), `fill`·`stroke` 색 속성과 `style` 속성 없음(색은 쓰는 쪽의 `currentColor`). 찍는 점 표시(`h.01`)처럼 굵기가 다른 선만 `stroke-width`를 가진다.
- **사본**: 앱과 대시보드의 `npm run sync:design`(`scripts/sync-design.mjs`)이 `global.css`와 함께 원본을 읽어 `src/components/pictograms.gen.tsx`를 만든다(생성 파일 머리말). 이 파일은 (1) `PictogramName` 타입(28개 id), (2) 문서에 한 번 그리는 `<PictogramSprite />`(숨긴 `<svg>` 안에 `<symbol>`들, JSX), (3) `<Pictogram name size label? />`(`<svg><use href="#p-<id>"/></svg>`, `fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"`)을 내보낸다.
- **스프라이트 자리**: 앱·대시보드의 `pages/_document.tsx` `<body>` 첫 요소. 정적 HTML에 들어가므로 외부 요청이 없고 오프라인(운영 앱 서비스 워커)에서도 그려진다. 인라인 스크립트·`style=`가 없어 `check:csp`를 지난다(숨김은 `global.css`의 `.pictogram-sprite` 클래스).
- **시험**: `scripts/sync-design.test.mjs`가 생성 파일이 원본에서 다시 만든 것과 같은지, id 목록이 9.1 표(지금 28개)와 정확히 같은지, `style`·`fill` 색·`<script>`·`foreignObject`가 없는지 본다. Vercel이 앱을 `web/app` 루트로 빌드하는 까닭(DESIGN.md)도 같다.
- 바꿀 때는 `web/shared/pictograms.svg`, DESIGN.md 표, 두 앱의 생성 파일을 같은 커밋에서 고친다.
- **SP9와 맞춘 것**: 이 스프라이트는 나중에 SP9("앱 탭·메모·일정")의 탭 아이콘 셋(스케줄, 메모, 더보기)을 받아들인다. 그때 id가 31개가 되고, 9.1 표와 DESIGN.md 표는 SP9 티켓이 함께 고친다. SP8의 시험은 "9.1 표의 id와 정확히 같다"를 보므로 개수를 따로 박지 않는다.

### 9.3 쓰는 규칙 (DESIGN.md "Pictograms" 절로 더한다, SP8-01)

1. 24px 격자, 선 1.75, 둥근 끝·둥근 이음, 채우지 않음. 크기는 16 / 20 / 24 셋. 16px에서는 선 2.
2. 색은 `currentColor`. 기본 `--text` 또는 `--muted`. 영역 픽토그램만 영역색(`--area-*`)으로 그릴 수 있다(작은 표식이라 "점·작은 태그"와 같은 취급, 면 칠하기 아님). 비서 표시(`assistant`)만 `--hue`.
3. **혼자 뜻을 전하지 않는다**: 늘 옆에 이름 글자가 있다(영역 이름, 종류 이름). 글자가 있으면 픽토그램은 `aria-hidden`. 글자 없이 쓰는 곳(한눈에 띠의 사건 표식)은 `role="img"`와 `aria-label`, 그리고 같은 내용의 표.
4. 이모지 아이콘을 쓰지 않는다(DESIGN.md Don't). 조작 아이콘(더하기, 체크, 닫기, 보내기, 펼침)은 지금의 `icons.tsx`가 맡고 픽토그램과 섞지 않는다. 앱 탭 막대 아이콘은 SP8에서는 그대로이고, SP9가 탭을 바꿀 때 스프라이트로 옮긴다(9.2).
5. 원(36px, `--raised`) 안에 넣는 것은 사건 줄과 홈 머리처럼 "줄의 얼굴"일 때만. 카드 안에 카드처럼 겹치지 않는다.
6. DESIGN.md "대시보드" 절의 "사건에 영역도 '비서가 만듦' 표시도 없다"는 문장을 고친다: 이제 히스토리는 영역 태그와 비서 표시를 쓴다(곡선 차트의 점은 그대로 ▲▼◆).

## 10. 상태창 화면

### 10.1 대시보드 상태창 (`/status`, `StatusScreen`)

```
┌──────────────────────────────────────────────┐
│ ★ Lv. 6   ████████░░░░░░░░  130 / 400 XP      │
├──────────────────────────────────────────────┤
│ 스탯 (2026-Q4)                                 │
│ 커리어   ██████▭░░░  7.2   바탕 6 · 요즘 +1.2   │
│ 건강     ████▭▭░░░░  5.5   바탕 4 · 요즘 +1.5  ↓ 디버프 (Q3 6) │
│          └ 몸 기록 · 지난 7일 걸음 평균 6,800 · 잠 평균 6시간 50분 │
│ 배움     ░░░░░░░░░░  —     요즘 +0.4 · 분기 회고에서 점수를 정하면 더해져요 │
├───────────────────────┬──────────────────────┤
│ 요즘 손이 간 영역        │ 이룬 순간               │
│ (건강) 건강  +1.5       │ 10월 24일 (토)          │
│   습관 28번             │ (커리어) 포트폴리오 사례…  │
│ (커리어) 커리어 +1.2     │ (건강) 아침마다 물을…     │
│   할 일 12개            │ 10월 23일 (금) …        │
└───────────────────────┴──────────────────────┘
```

- **스탯 줄**: 막대는 바탕 칸을 `--primary`로 채우고, 보너스 칸(올림한 칸 수)은 채우지 않은 1px `--text` 테두리 칸으로 이어 그린다(색이 아니라 모양으로 구분). 숫자는 `effective_score`(없으면 "—"), 옆 `caption` "바탕 {n} · 요즘 +{b}". 보너스가 0이면 "바탕 {n}"만. 디버프 표시와 회복 퀘스트는 지금 그대로.
- **건강 근거 줄**: 건강 줄 아래 `caption`. `body`가 있으면 "몸 기록 · 지난 7일 걸음 평균 {n} · 잠 평균 {h}시간 {m}분"(없는 값은 그 부분을 뺀다). `body`가 `null`이면 그리지 않는다.
- **요즘 손이 간 영역**(패널, 픽토그램 `status`): `bonus > 0`인 영역을 큰 순서로(같으면 SP1 영역 순서). 줄마다 영역 픽토그램(영역색) + 영역 이름 + "+{b}", 둘째 줄 "4주 동안 할 일 {n}개 · 습관 {m}번 · 몸 기록 {k}일"(0인 항목은 뺀다). 빈 상태: "4주 안에 끝낸 할 일이나 습관 체크가 생기면 여기에 보여요."
- **이룬 순간**(패널, 픽토그램 `memory`): `moments`를 날짜 머리("10월 24일 (토)")로 묶고, 줄마다 영역 픽토그램(영역이 없으면 `memory`) + 글. 아래 `caption` "숨기거나 지우는 것은 운영 앱 상태창에서 할 수 있어요." 빈 상태: "하루가 끝나면 비서가 그날 해낸 일을 몇 줄로 남겨 둬요."
- 내려가는 표시, 지난 보너스와의 비교, 비율은 그리지 않는다(5.3).
- 한눈에 홈(`index`, 캔버스 `HomePhone2`)과 내비게이션에 픽토그램을 더한다: 내비게이션 `home` `todo` `curve` `status`, 홈 칸 머리 `condition`, `ladder`, `level`, `todo`, `habit`, `chapter`, `review`. 홈 "지금 챕터" 칸의 링크 "히스토리 보기"는 `/curve?tab=history`로 간다. 홈의 숫자·배치는 바꾸지 않는다.

### 10.2 운영 앱 상태창 (`/status/`, 새 화면, SP9 "더보기"의 한 줄, "‹ 더보기")

질문: **요즘 무엇에 손이 갔고, 무엇을 해냈나?**

| 블록 | 데이터 | 동작 |
|---|---|---|
| 큰 제목 "상태창" | | |
| 레벨 줄: `level` 픽토그램, "Lv. {n}", XP 막대(6px), "{into} / {next} XP" | `GET /status` | |
| 스탯 (그룹 목록) | `stats[]` | 줄마다 영역 픽토그램 + 이름, 오른쪽 `effective_score`, 둘째 줄 "바탕 {n} · 요즘 +{b}". 건강 줄 아래 몸 기록 줄 |
| 요즘 손이 간 영역 | `stats[]`의 `bonus > 0` | 10.1과 같은 줄 |
| 이룬 순간 (이어지는 종이) | `moments` | 줄을 왼쪽으로 밀면 "숨기기", "지우기"(빨강 글자). 줄 끝 44px "더 보기" 버튼이 같은 두 동작의 작은 시트를 연다(밀기를 못 쓰는 경우) |
| 숨긴 순간 (있을 때만, 접힘) "숨긴 순간 {n}개" | `GET /moments?include_hidden=true` | 줄마다 "다시 보이기" |
| "지난 순간 더 보기" | `GET /moments?before=` | 14일씩 더 |

- **숨기기**: `POST /actions hide_moment` → 줄이 접히고(200ms) 알림 줄 "숨겼어요"와 "되돌리기". **지우기**: BE가 `needs_confirm`을 주면 SP5의 확인 시트("이 순간을 지울까요? 되돌릴 수 없어요." / "지우기" / "그대로 두기").
- 몸 기록 줄: `body`가 있으면 10.1과 같은 글, 아래 "마지막 기록 {M}/{D}". 없으면 "아이폰 단축어로 걸음과 잠을 보내면 건강 스탯의 근거가 돼요. 설정은 README의 'iPhone 단축어'를 봐 주세요."
- **들어가는 길**(SP9 스레드와 합의): SP9가 만드는 "더보기" 화면의 한 줄 "상태창"(`status` 픽토그램)이고, 상태창의 뒤로 링크는 "‹ 더보기"다. 오늘 화면에서는 링크하지 않는다. SP9의 더보기 화면이 SP8-02보다 늦게 머지되면, 그 사이에는 주소 `/status/`로만 열리고 뒤로 링크는 "‹ 오늘"로 두었다가 SP9 머지 때 바꾼다.
- 오프라인: 상태창은 스냅샷에 넣지 않는다(SP5 스냅샷은 `GET /today`만). 오프라인이면 `OfflineNotice`와 "연결되면 상태창을 보여 드릴게요."
- 화면 CSS 모듈은 `pages/_app.tsx`에서 불러온다(SP7 9장 규칙). 색은 역할 토큰과 영역 토큰만. 라이트·다크·프리셋 스냅샷.

### 10.3 두뇌 (텔레그램 `/status`는 그대로)

- 텔레그램은 은퇴할 예정이라(D7) 텔레그램 `/status` 화면은 SP8에서 고치지 않는다. 보너스·이룬 순간·몸 기록 줄을 더하지 않고, 지금처럼 바탕 점수를 보여 준다.
- `get_status`(두뇌): `stats[]`의 새 필드, `body`, 그리고 지난 7일의 순간. **통로에 따라 다르다**(D7): 앱 통로(`RunContext.channel == "app"`)는 `moments: [Moment]`(글 포함), 텔레그램 통로는 `moments: [{"date", "count"}]`(날짜와 개수만, 글 없음). 하네스가 도구 결과를 만들 때 고른다(두뇌에게 맡기지 않는다). 순간을 대화에 옮겨 말할 때는 사용자가 물었을 때만(`system.md` 원칙 16).
- `system.md`에 더할 원칙:
  15. 이룬 순간은 비서가 하루 끝에 조용히 남기는 기록이다. 사용자가 지우고 싶어 하면 앱 상태창에서 밀어서 숨기거나 지울 수 있다고 안내한다. 대화에서 직접 고치지 않는다.
  16. 보너스와 이룬 순간은 사용자가 물을 때 말한다. 보너스가 줄었다거나, 순간이 없던 날을 세어 말하지 않는다. 텔레그램 대화에서는 순간의 글을 받지 않으므로 개수만 말하고 "운영 앱 상태창에서 볼 수 있어요"라고 안내한다.
- 주간 회고 앞머리(`harness/context.py`)에 `## 이번 주 이룬 순간`과 `## 요즘 손이 간 영역`(`bonus > 0` 영역과 값)을 더한다. 이룬 순간 블록은 회고가 가는 실제 통로로 정한다: 앱이면 날짜와 글, 텔레그램이면 날짜와 개수만(`- 10/24 2개`). 회고 지시문(`review_week.md`)에 한 줄: "앞머리에 이룬 순간의 글이 있으면 그 가운데 인생 곡선에 남길 만한 것 하나만 '곡선에 남길까요?'라고 묻는다(초안은 사용자가 답한 뒤). 글이 없으면 묻지 않는다."

## 11. 보안과 개인정보

| 항목 | 규칙 |
|---|---|
| 이룬 순간 | SQLite `status_moments`에만. 로그, `data/exports/`, 원문 기록, 활동 `summary`, 텔레그램, 웹 푸시, 오류 보고(`/client-errors`), 순간 호출의 SDK 세션 파일(`no-session-persistence`, 6.3)에 글이 없다. API 응답(tailnet 안, 토큰 인증)과 **앱 통로의** 두뇌(`get_status`, 회고 앞머리)에만 나간다. 텔레그램 통로의 두뇌는 날짜와 개수만 받는다(D7). 앱 대화의 `get_status` 결과는 그 대화의 SDK 세션 파일(`~/.claude/projects/`, 대화 이어 쓰기용, SP1)에 남는다: 다른 대화 내용과 같은 취급이다(ADR 0013) |
| 두뇌 입력 | 하루 끝 작업에 주는 메시지는 원문 기록의 이미 가린(`redact`) 사용자 줄이다. 비서의 말은 주지 않는다 |
| 몸 기록 | 걸음·잠 두 값, 56일 보관. 로그에 숫자 없음. 활동 기록 없음. 내보내기 없음 |
| `BODY_TOKEN` | `.env`에만, 폰 단축어에 사용자가 넣는다. 저장소·로그·오류 응답에 없다. `POST /body`만 된다. 바꾸려면 `.env`를 고치고 BE를 다시 시작한 뒤 단축어의 헤더를 고친다 |
| 노출 범위 | 지금 그대로: `127.0.0.1` + `tailscale serve`, Funnel 없음(SP3-4 14장) |
| 두뇌 도구 | 하루 끝 작업은 `mcp__planner__save_moments` 하나(ADR 0005) |
| 테스트 자료 | 순간·사건·몸 기록은 꾸며 낸 내용만(`tests/fixtures/`). 시드 파일 내용은 저장소에 넣지 않는다 |

## 12. 하지 않는 것 (다시 묻지 않게)

- 보너스가 내려갔다는 알림, 아래 화살표, 지난주 보너스 비교, "4주 뒤 사라짐" 같은 남은 기간 표시, 비율·%.
- 이룬 순간으로 경험치·칭호 주기, 순간 개수 세기 목표("하루 3개"), 순간이 없던 날 표시.
- 순간을 확인 버튼으로 받기(ADR 0013), 순간을 사건으로 자동 올리기.
- 걸음·잠 목표, "오늘 걸음이 부족해요" 같은 말, 몸 기록 알림.
- 심박, 체중, 운동, 위치 같은 다른 건강 값.

## 13. 테스트

| 묶음 | 명령 | 확인하는 것 (기대: 모두 통과, 실패 0) |
|---|---|---|
| 보너스 공식 | `python -m pytest tests/test_status_activity.py -q` | 5.4 표의 예 1~8 그대로(`Fraction`, 1.45 → 1.5), 하루 상한 3, `1/n` 나누기, 04:00 경계(02:30 완료 → 전날), 창 경계(27일 전 들어감, 28일 전 빠짐), 다시 연 할 일·소프트 삭제 할 일·삭제된 습관 빠짐, 쉬는 습관 체크 들어감, 보너스 ≥ 0, `effective_score ≤ 10`, 영역 점수 없음 → `null` |
| 보너스 성질 | `python -m pytest tests/test_status_property.py -q` | (속성 테스트) 아무 활동 묶음에서도 `base ≤ effective ≤ min(10, base + 2)`, 하루가 지나 새 활동이 없으면 보너스가 늘지 않음, 날마다 바뀌는 폭 ≤ 0.7(하루 상한 3 → 0.6, 반올림 0.1) |
| 스냅샷 | `python -m pytest tests/test_status_snapshot.py tests/test_status_command.py -q` | `stats[]` 새 필드, 디버프가 바탕끼리만, `moments`(14일, 숨긴 것 뺌, 최대 20), `moments_hidden`, `body` |
| 마이그레이션 | `python -m pytest tests/test_migrations.py -q` | 013·014·015 적용, CHECK(순간 60자, `slot` 1~3, 걸음 범위, 둘 다 NULL 거절, 사건 `area`, `ladder_remembered` 0~10), 기존 곡선 행 그대로, `version.schema = 15`, 원장 그대로 |
| 순간 작업 | `python -m pytest tests/test_moments_job.py -q` | 고르는 날(7일, `moments_since`, `pending`만, 오래된 날부터), 데이터 없는 날 `empty`·두뇌 안 부름, `empty` 날에 나중 체크가 생겨도 다시 안 함, 실행 직전 다시 읽기(`done`이면 두뇌 안 부름), 상한 여유 10 미만이면 멈춤, `rate_limited`·`auth_error`에서 `_set_limited`·`brain.auth` 기록과 `attempts` 그대로, **결과는 호출 뒤 상태로**(M2 오류 → 고쳐 저장 → `max_turns`로 끝나도 `done`, `attempts` 그대로), 저장 없는 오류 2회 → `failed`, `failed`가 `done`을 덮지 않음, 도구를 안 부르고 `ok` → `done 0`, 사용자 메시지·회차가 먼저, 멈춤 중에도 돎, 호출의 `max_turns = 3` |
| 순간 도구 | `python -m pytest tests/test_moments_tools.py tests/test_brain_options.py -q` | M1~M5, 금지어 항목만 버림, 참조 밖 `sources` 거절, 두 번째 호출 `already`, 한 트랜잭션(도중 실패 시 순간·날 행·활동 모두 없음), 대화 도구 목록에 `save_moments` 없음, `kind = moments`에는 `save_moments`만(서버에 실린 도구 이름으로 확인), `kind != moments`의 `save_moments` 거절, **순간 호출 옵션의 `extra_args`에 `no-session-persistence`가 있고 대화 호출에는 없음**, 순간 호출의 지시문이 `moments.md`, 메모(SP9)를 읽지 않음, **`get_status`가 텔레그램 통로에서 `moments`를 날짜·개수로만 주고 글이 결과 JSON에 없음, 앱 통로에서는 글을 줌** |
| 순간 API | `python -m pytest tests/test_api_moments.py tests/test_api_undo.py -q` | `GET /moments` 범위·`include_hidden`, `sources`는 종류만, 숨기기·다시 보이기 되돌리기, 지우기 `needs_confirm` → 확인 뒤 행 없음·`not_undoable`, 지운 순간 `404`, 지운 날 다시 정리 안 함 |
| 몸 기록 API | `python -m pytest tests/test_api_body.py tests/test_api_auth.py -q` | 7.3 검증 전부(모르는 키, 8일, 겹친 날짜, 미래, 14일 밖, 범위, `null`), 한국 달력 오늘 02:30에 오늘 날짜를 받음, 덮어쓰기는 보낸 값만, `/body`에 `API_TOKEN` → 401, `BODY_TOKEN`으로 `GET /status` → 401, `API_TOKEN`으로 `/actions record_body_days` → 거절, `BODY_TOKEN`이 없거나 짧거나 `API_TOKEN`과 같으면 `API_TOKEN` 헤더로 `/body` → 404, `BODY_TOKEN`만 보내면 401, 4KB 넘으면 413(다른 경로 상한은 그대로), `/body` 응답에 CORS 헤더 없음, 실패 세기 공유, 56일 정리, 건강 보너스 반영 |
| 곡선 API | `python -m pytest tests/test_api_curve_status.py tests/test_curve_history.py -q` | `GET /curve` 새 필드, `GET /curve/history` 정렬·`unassigned`·`ladder` 출처(기억 → 기록 평균 → null)·민감 사건 빼고 개수와 해만·`summary` 각 값, 민감 사건 제목이 기본 응답 본문에 없음 |
| 시드 | `python -m pytest tests/test_seed_life.py -q` | `events[].area`, `chapters[].ladder`, 틀린 값 `invalid`, `--update-history`(이미 가져온 DB, 빈 칸만, 확인 규칙, 겹치는 항목 `ambiguous`, 출력에 내용 없음, 두 번째 코드 4, 잠금 코드 3) |
| 곡선 도구 | `python -m pytest tests/test_curve_tools.py tests/test_telegram_curve.py -q` | `add_milestone(area)`, `propose_chapter(ladder)` 검증, 확정 문구 "(2019, 높은 때, 삶의 질)" |
| 로그·개인정보 | `python -m pytest tests/test_api_logging.py tests/test_write_paths.py -q` | 시험 순간 글·걸음 숫자·`BODY_TOKEN`이 로그 파일에 없음, `data/exports/`에 순간 파일 없음, 활동 `summary`에 순간 글 없음, 새 쓰기가 모두 단일 작성자 길 |
| 프롬프트 | `python -m pytest tests/test_prompts.py -q` | `moments.md` 골든, 금지어 블록, 원칙 15·16, 회고 앞머리 두 블록(**텔레그램으로 가는 회고는 이룬 순간 블록에 날짜·개수만, 앱은 글**) |
| 대시보드 | `cd web/dashboard && npm test && npm run build && npm run check:csp && npm run sync:design && git diff --exit-code` | 히스토리 탭(주소 `?tab=history`, 거르기, 정렬, 접힌 챕터, 민감 사건 보기·가리기, 빈 상태), 한눈에 띠와 표, 옆 요약, 상태창 보너스 칸·근거 줄·두 패널, 픽토그램 스프라이트 한 번, 라이트·다크 스냅샷 |
| 앱 | `cd web/app && npm test && npm run build && npm run check:csp && npm run sync:design && git diff --exit-code` | 상태창 화면(밀기·더 보기 시트·확인 시트·되돌리기·숨긴 순간·지난 순간), 뒤로 링크("‹ 더보기", SP9 전에는 "‹ 오늘"), 오늘 화면에 상태창 링크 없음, 오프라인 안내, 프리셋 스냅샷 |
| 픽토그램 | `cd web/app && npx vitest run scripts/sync-design.test.mjs` (대시보드도) | 사본 = 원본, id 목록 = 9.1 표, `style`·색 `fill`·`script` 없음 |
| 문구 | `cd web/app && npx vitest run src/lib/copy.test.ts`, `python -m pytest tests/test_prompts.py -q` | 부록 A 전체, 정적 문구 검사의 새 금지 구("보너스가 줄", "스탯이 떨어"). `system.md` 금지어 블록과 순간 M3는 바뀌지 않음("지출이 줄었어요" 같은 순간이 버려지지 않음) |
| 이야기 | `python -m pytest tests/test_sp8_story.py -q` | 꾸며 낸 4주: 습관·할 일 → 보너스, 하루 끝 순간 2개 → 앱에서 하나 숨김·하나 지움, 단축어 3일 → 건강 근거 줄, 사흘 꺼짐 → 따라잡기, 텔레그램 `/status` 출력이 SP8 전과 같음, 텔레그램 대화의 `get_status`에 순간 글 없음, 히스토리 응답 |
| 노트북 수용 | SP8-11 체크리스트 | 실제 두뇌로 순간 호출 한 번 뒤 `~/.claude/projects` 아래에 새 jsonl이 없음(S-SP8-1), 실제 단축어 한 번 |

## 14. 티켓 (구현 순서, 계획에서 더 쪼갠다)

| # | 티켓 | 내용 |
|---|---|---|
| SP8-00 | 1단계 BE: 스탯 보너스 | `status/activity.py`(공식, 상수), `StatusRepo.activity_rows`(몸 기록은 `[]`, 5.6), `status_snapshot` 새 필드, `get_status`, 스키마·타입 재생성, SP3-4 6.3.6 `GET /status` 모양에 새 필드 적기, 13장 보너스 묶음 |
| SP8-01 | 픽토그램 | `web/shared/pictograms.svg` 28개, 두 앱 `sync-design` 확장(`pictograms.gen.tsx`), `_document` 스프라이트, `Pictogram` 부품, DESIGN.md "Pictograms" 절과 9.3-6 문장 고침 |
| SP8-02 | 1단계 화면 | 대시보드 상태창 보너스 칸·"요즘 손이 간 영역"·내비게이션·홈 픽토그램, 앱 `/status/` 화면(레벨, 스탯, 요즘 손이 간 영역, 뒤로 링크 10.2), 정적 문구 검사의 새 금지 구("보너스가 줄", "스탯이 떨어") |
| SP8-03 | 2단계 BE: 순간 만들기 | 스파이크 S-SP8-1(`no-session-persistence`로 세션 파일이 안 생기는지), `013_moments.sql`, `MomentsRepo`, `RunContext.kind`·`Brain.run` 새 인자·`tool_names_for(ctx)` 필터(6.3 인터페이스), `save_moments` 도구(M1~M5), `queue_moments` 하루 작업과 `_MomentsJob`(가장 낮은 차례, 상한 여유, 실행 직전 다시 읽기, 상태로 판정), `moments.md`(금지어 블록), ADR 0013 링크 |
| SP8-04 | 2단계 API | `/status.moments`, `GET /moments`, `/actions` 세 동작과 되돌리기, 통로별 `get_status.moments`(앱 글, 텔레그램 날짜·개수), 회고 앞머리 두 블록(통로별), `system.md` 원칙 15·16, `review_week.md` 한 줄, SP3-4 6.2 경로표·6.4.2 동작표·6.4.3 되돌리기 표에 새 줄 |
| SP8-05 | 2단계 화면 | 앱 이룬 순간 블록(밀기, 더 보기 시트, 확인 시트, 숨긴 순간, 지난 순간), 대시보드 이룬 순간 패널 |
| SP8-06 | 3단계 BE: 몸 기록 | `014_body.sql`, `POST /body`, 경로별 토큰 고르기·4KB 상한·CORS 건너뛰기(7.2), `_callable_from`로 `/actions`에서 막기, 검증(한국 달력 오늘), `record_body_days`, 56일 정리, `activity_rows`의 몸 기록 질의, `/status.body`, SP3-4 6.2 경로표에 `POST /body` |
| SP8-07 | 3단계 화면과 안내 | 대시보드·앱 건강 근거 줄, 앱 연결 안내, README "iPhone 단축어"(실제 아이폰으로 만들어 보고 화면 순서대로, 공유 금지·토큰 바꾸기 두 문장), `.env.example`에 `BODY_TOKEN` |
| SP8-08 | 히스토리 BE | `015_curve_history.sql`, 시드 `area`·`ladder`, `seed-life --update-history`(`ambiguous`), `add_milestone(area)`, `propose_chapter(ladder)`, `GET /curve` 필드, `GET /curve/history`, 사건 종류 이름 바꾸기의 BE·텔레그램·프롬프트 쪽(8.7)과 확정 문구, SP3-4 6.2 경로표에 `GET /curve/history` |
| SP8-09 | 히스토리 화면 1 | 곡선 화면 탭(`?tab=history`), 챕터 목록, 사건 줄, 거르기·정렬, 접힌 챕터, 빈 상태, 사건 종류 이름 바꾸기의 화면 쪽(8.7) |
| SP8-10 | 히스토리 화면 2 | 민감한 사건(가려 둔 줄, 보기·가리기, 토글 공유), 한눈에 띠와 화면 읽기용 표, 옆 요약과 도움 상자 |
| SP8-11 | 수용 | `test_sp8_story`, 로그·통로 검사, 두 앱 라이트·다크 스냅샷, 노트북 확인(실제 단축어, 하루 끝 순간 한 번과 세션 파일 없음) |

SP8-00은 다른 티켓을 기다리지 않는다. SP8-01은 SP8-02·05·07·09·10보다 먼저다. 순간 M3의 금지어는 `system.md` 블록을 그대로 쓰므로 SP8-03에서 따로 늘리지 않는다. **마이그레이션 번호는 SP9 스레드("앱 탭·메모·일정")와 합의했다**: SP8이 013(순간), 014(몸 기록), 015(히스토리)를 쓰고 SP9는 016부터 쓴다. SP8 안에서는 이 순서로 머지한다. 브랜치는 `develop`에서 만들고 PR도 `develop`으로(ADR 0012).

## 15. 설정

- `.env` 추가: `BODY_TOKEN`(7.2). `.env.example`에 자리 표시 값.
- `config.toml` 추가 없음. 보너스·순간·몸 기록의 숫자는 코드 상수다(`status/activity.py`, `harness/moments.py`): 바꾸면 이 문서의 표도 함께 고친다.
- `app_state` 새 열쇠: `moments_since`, `moments_paused`(16장), `life_seed_history_updated_at`.

## 16. 마이그레이션과 되돌림

- 013, 014, 015는 앞으로만 간다(SP1·SP3-4·SP7과 같다). 적용 전 SP1 백업(`store/backup.py`)이 돈다.
- 끄고 싶을 때: 보너스는 끄는 설정이 없다(바탕 아래로 가지 않으므로). 이룬 순간은 `app_state.moments_paused = "1"`이면 `queue_moments`가 날을 고르지 않는다(README에 한 줄, 화면 설정은 없음). 몸 기록은 `.env`에서 `BODY_TOKEN`을 빼면 경로가 닫힌다.
- 배포 롤백(SP6): 스키마가 바뀐 배포는 DB도 배포 직전 백업으로 돌아가므로, 롤백 사이에 저장된 순간·몸 기록은 사라질 수 있다. 몸 기록은 단축어가 3일을 다시 보내 채운다. 순간은 그날이 `pending`으로 돌아가 다시 정리된다.

## 17. 미결 사항 (비서가 정함, Dahun 검토)

Dahun이 고르지 않은 선택은 비서가 정했다. 아래 추천으로 구현하고, 바꾸고 싶으면 해당 절을 고친다.

1. **보너스 공식의 숫자**: 28일 직선 무게, 할 일 1(영역 수로 나눔), 습관 체크 0.5, 하루 상한 3, `S = 10`에서 상한 +2, 소수 한 자리(5.2, 5.3). 매일 한 가지를 하면 상한에 닿고, 주 3번이면 +1 남짓이다.
2. **디버프는 바탕 점수끼리만**: 보너스는 디버프를 만들거나 지우지 않는다(5.3). 사용자가 매긴 신호를 계산 값이 덮지 않게.
3. **이룬 순간은 경험치를 주지 않는다**(6.6, ADR 0006).
4. **숨기기·지우기는 운영 앱에서만**: 숨기기는 되돌릴 수 있고, 지우기는 확인 뒤 행 삭제. 대시보드는 읽기만, 텔레그램 `/status`에는 나오지 않는다(6.4, 10.3).
5. **순간 보관과 내보내기**: 지우기 전까지 보관, md 내보내기 없음(ADR 0003의 예외, 6.4).
6. **순간 작업의 비용 규칙**: 7일 따라잡기, 상한 여유 10회, 실패 2회까지, 입력은 사용자 메시지만 6,000자(6.2, 6.3).
7. **몸 기록 규칙**: 따로 둔 `BODY_TOKEN`, 단축어가 매일 지난 3일을 보냄, 걸음 6,000·잠 7시간에 각 0.5, 56일 보관, 경험치·활동 기록 없음, `client_msg_id` 없음(7장).
8. **챕터의 `ladder_remembered` 칸을 함께 더한다**: 히스토리의 "그때 사다리"에 필요하다. 이미 가져온 시드는 `seed-life --update-history`로 채운다(8.1).
9. **사건 종류 화면 이름**: 높은 때 / 힘든 때 / 전환점으로 모든 화면과 텔레그램 문구를 바꾼다. 곡선 차트의 ▲▼◆ 표식은 그대로(8.7).
10. **앱에 상태창 화면을 새로 둔다**(`/status/`, SP9 "더보기" 화면의 한 줄, 뒤로 링크 "‹ 더보기", SP9 스레드와 합의). 히스토리는 대시보드에만(10.2, 2장).
11. 부록 A 문구.

## 부록 A. 새 고정 문구 (Dahun 확인 필요)

| 자리 | 문구 |
|---|---|
| 스탯 보조 글 | "바탕 {n} · 요즘 +{b}", "바탕 {n}", "요즘 +{b} · 분기 회고에서 점수를 정하면 더해져요" |
| 요즘 손이 간 영역 | 머리 "요즘 손이 간 영역", 줄 "+{b}", 둘째 줄 "4주 동안 할 일 {n}개 · 습관 {m}번 · 몸 기록 {k}일", 빈 상태 "4주 안에 끝낸 할 일이나 습관 체크가 생기면 여기에 보여요." |
| 건강 근거 줄 | "몸 기록 · 지난 7일 걸음 평균 {n} · 잠 평균 {h}시간 {m}분", "마지막 기록 {M}/{D}" |
| 몸 기록 안내(앱) | "아이폰 단축어로 걸음과 잠을 보내면 건강 스탯의 근거가 돼요. 설정은 README의 'iPhone 단축어'를 봐 주세요." |
| 이룬 순간 | 머리 "이룬 순간", 날짜 머리 "{M}월 {D}일 ({요일})", 대시보드 끝 줄 "숨기거나 지우는 것은 운영 앱 상태창에서 할 수 있어요.", 빈 상태 "하루가 끝나면 비서가 그날 해낸 일을 몇 줄로 남겨 둬요.", "숨긴 순간 {n}개", "지난 순간 더 보기" |
| 순간 동작 | 버튼 "숨기기", "지우기", "다시 보이기", "더 보기", 알림 줄 "숨겼어요" + "되돌리기", "다시 보여요", 확인 시트 "이 순간을 지울까요? 되돌릴 수 없어요." / "지우기" / "그대로 두기" |
| 활동 기록 | "이룬 순간 {n}개 정리 ({M}/{D})", "이룬 순간 숨김 ({M}/{D})", "이룬 순간 다시 보임 ({M}/{D})", "이룬 순간 지움 ({M}/{D})" |
| 도구 오류 | "이 날짜만 정리할 수 있어요.", "근거로 쓸 수 없는 항목이 있어요.", "이룬 순간은 하루 3개까지예요.", "쓸 수 없는 도구예요." |
| 몸 기록 API 오류 | "걸음 수와 잠만 받아요.", "지난 14일 안의 날만 받아요.", "하루를 두 번 보냈어요.", "한 번에 7일까지 보낼 수 있어요.", "걸음 수는 0~100,000, 잠은 0~1,440분이에요.", "걸음 수나 잠 가운데 하나는 있어야 해요." |
| 앱 상태창 | 큰 제목 "상태창", 더보기 화면 줄 "상태창", 뒤로 링크 "‹ 더보기"(SP9 전에는 "‹ 오늘"), 오프라인 "연결되면 상태창을 보여 드릴게요." |
| 히스토리 탭 | 탭 "곡선", "히스토리", 부제 "지금까지 걸어온 길 · 챕터 {n}개 · 사건 {m}개 · {YYYY}년부터", 정렬 "최근부터 ▾" / "오래된 것부터 ▾", 거르기 "전체", "높은 때", "힘든 때", "전환점", 토글 "민감한 사건 가림" |
| 챕터·사건 | "그때 사다리 {n}", "사다리 평균 {x}", "사건 {n}개", "추정", "기억으로 그린 시기예요.", "비서가 만듦", "민감", "{제목} · {해} 더 보기", "이 시기에는 고른 종류의 사건이 없어요.", "시기를 정하지 않은 사건", 빈 상태 "시드를 가져오거나 대화에서 사건을 남기면 여기에 쌓여요." |
| 민감한 사건 | "가려 둔 사건 {n}개 · {해들}", "보기", "가리기" |
| 한눈에 띠 | 제목 "한눈에 보는 지난 길", 부제 "챕터마다 기억한 사다리 점수와 사건이에요. 점선은 기억으로 그린 시기예요." |
| 옆 요약 | "가장 높았던 챕터", "사다리 {n}", "전환점", "{n}번", "가장 길었던 챕터", "{n}년", "기억과 기록", "{YYYY}년부터는 매일 기록으로 그려요", 도움 상자 머리 "비서가 정리를 돕는 법", 본문 "대화에서 나온 일을 사건 초안으로 만들어 두면, 확인 버튼을 눌러야 여기에 올라와요. 지난 챕터도 '이 시기 같이 정리하자'라고 말하면 돼요." |
| 사건 종류 (바뀜) | "고점" → "높은 때", "저점" → "힘든 때". 확정 문구 "✓ 저장: {제목} ({날짜}, {종류}, {영역})"(영역이 없으면 지금처럼 "({날짜}, {종류})") |
| 시드 명령 | `--update-history` 출력 "채울 것: 사건 영역 {n}, 챕터 사다리 {m}", "건너뛸 것: {k} (…)"(이유별 개수 `sensitive_unconfirmed`, `storage_unconfirmed`, `invalid`, `ambiguous`, SP3-4 12장 형식), 두 번째 실행 "이미 채웠어요." |
| 두뇌 원칙 | `system.md` 15·16(10.3), `review_week.md` 한 줄(10.3), `moments.md` 규칙 1~6(6.3) |
| 두뇌 앞머리(텔레그램 통로) | `## 이번 주 이룬 순간` 줄 "- {M}/{D} {n}개" |
| 픽토그램 이름 (`aria-label`) | 9.1 표의 "이름" 열 |
| 금지 구 추가 | "보너스가 줄", "스탯이 떨어"(앱·대시보드 정적 문구 검사만. `system.md` 금지어 블록과 순간 M3에는 넣지 않는다: "지출이 줄었어요" 같은 좋은 말을 막지 않게) |

## 변경 기록

- SP8-00 (2026-10-25): 5.6 함수 모양을 계획 결정 4대로 고침(`area_points`·`activity_counts`의 `tz`·`boundary`, `area_bonus(points, today, counts)`, `activity_rows(from_utc, from_day, to_day)`). 공식·값은 그대로.
- v3 (2026-10-25): Dahun "텔레그램은 궁극적으로 사용안하게 될거라 굳이 넣을 필요없을 것 같은데"(SP9 스레드). 텔레그램 `/status`는 SP8에서 바꾸지 않는다(보너스·순간·몸 기록 줄 없음). 텔레그램 통로 두뇌의 날짜·개수 규칙은 그대로.
- v2 (2026-10-25): 검토 1차(BLOCKER 3, SHOULD 9, NIT 7) 반영. 텔레그램 통로는 순간의 날짜·개수만(D7), 순간 호출은 `no-session-persistence`(SDK 0.2.173 확인), `max_turns = 3`과 호출 뒤 상태로 판정, 몸 기록 경로별 토큰·`/actions` 막기·한국 달력 오늘, 6.3 인터페이스, 금지 구를 정적 검사로 좁힘, 티켓 SP8-11까지 다시 나눔. SP9와 합의: 마이그레이션 013~015(SP9는 016부터), 메모는 순간과 따로, 앱 상태창은 더보기 화면의 한 줄, 스프라이트가 SP9 탭 아이콘 셋을 받음.
- v1 (2026-10-25): 첫 초안. D1~D6 Dahun 결정(결정 카드), 나머지는 비서가 정함(17장). 캔버스 보드 `HistoryDesktop`, `HistoryPhone`, `Pictograms`, `HomePhone2` 방향 반영.
