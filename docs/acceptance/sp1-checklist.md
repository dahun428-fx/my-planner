# SP1 7일 수용 테스트 체크리스트

스펙 1장 완료 조건 1~6을 노트북에서 7일 동안 실제로 써 보며 확인한다. 매일 저녁(또는 다음 날 아침) 한 줄씩 채운다. 문제가 보이면 GitHub 이슈로 남기고 표의 "이슈" 칸에 번호를 적는다.

## 시작 전 준비

- [ ] 텔레그램 봇 만들기(BotFather), 토큰은 `E:\my-planner\.env`에만 저장 (채팅에 붙여 넣지 않기)
- [ ] `.env`의 주인 계정 ID 확인
- [ ] `powershell -ExecutionPolicy Bypass -File scripts\register_task.ps1`
- [ ] `powershell -ExecutionPolicy Bypass -File scripts\check_tasks.ps1` → 전부 OK
- [ ] 노트북 시간대가 Asia/Seoul인지 확인
- [ ] 자동 테스트: `.venv\Scripts\pytest -q` 통과 (완료 조건 6)
- [ ] 시작일 기록: `____-__-__`

## 완료 조건

| # | 조건 (스펙 1장) | 확인 방법 |
|---|---|---|
| 1 | 7일 동안 `morning_brief`, `evening_checkin`, `review(week)` 예정 회차가 모두 `done` 이거나, 5.4 규칙에 맞는 `skip_reason`을 가진 `skipped` | 아래 SQL 1·2 |
| 2 | 비서 제안은 확정 전까지 목록에 없음. 자연어로 추가·완료·날짜 이동·내려놓기·우선순위 지정, 변경마다 확인 문구 | 텔레그램에서 직접 해 보고 `/today`로 확인 |
| 3 | 다른 계정·그룹 채팅 메시지에는 반응 없음 | 다른 계정(또는 그룹)에서 봇에게 메시지 1회 |
| 4 | 재부팅 후 로그인, 절전 복귀, 전원 분리 후에도 저절로 다시 동작 | 각각 한 번씩 해 보고 `state/logs`의 시작·복귀 로그 확인 |
| 5 | 모든 대화가 원문 기록에 남고 인증·식별 정보는 가려짐 | `data/transcripts/` 해당 날짜 파일 열어 보기, 가짜 비밀번호 한 번 보내 보기 |
| 6 | 자동 테스트 전부 통과 | 시작 전 준비에서 확인 |

## 날짜별 기록

| 날짜 | 1 회차 | 2 할 일 | 3 잠금 | 4 상시 실행 | 5 원문 기록 | 메모 | 이슈 |
|---|---|---|---|---|---|---|---|
| D1 |  |  |  |  |  |  |  |
| D2 |  |  |  |  |  |  |  |
| D3 |  |  |  |  |  |  |  |
| D4 |  |  |  |  |  |  |  |
| D5 |  |  |  |  |  |  |  |
| D6 |  |  |  |  |  |  |  |
| D7 |  |  |  |  |  |  |  |

칸에는 `OK`, `FAIL`, `-`(그날 확인 안 함)을 쓴다. 7일 안에 일요일이 한 번은 들어가야 `review(week)`를 볼 수 있다. 조건 3·4는 7일 중 한 번씩만 확인해도 된다.

## 확인용 SQL

`state/planner.db`를 DB Browser for SQLite나 `sqlite3`로 열어 실행한다. `?`에는 시작일 UTC 시각(예: `2026-10-26T00:00:00+00:00`)을 넣는다.

**1. 회차 상태 집계**

```sql
SELECT loop, status, skip_reason, count(*)
FROM runs
WHERE scheduled_for >= ?
GROUP BY 1, 2, 3;
```

**2. 완료 조건 1 위반 후보** (끝나지 않았거나 이유 없이 건너뛴 회차)

```sql
SELECT id, loop, scheduled_for, status, skip_reason
FROM runs
WHERE scheduled_for >= ?
  AND loop IN ('morning_brief', 'evening_checkin', 'review')
  AND NOT (status = 'done' OR (status = 'skipped' AND skip_reason IS NOT NULL))
ORDER BY scheduled_for;
```

결과가 비어 있어야 한다. 나오는 줄이 있으면 그 회차의 `scheduled_for` 전후 로그(`state/logs`)를 보고 이슈로 남긴다.

`skip_reason`으로 나올 수 있는 값과 뜻(스펙 5.4): `merged_into_return`(오래 꺼졌다 켜져 복귀 인사로 합침), `late`(한계 시각을 넘김), `paused`(`/pause` 중), `daily_cap`(하루 두뇌 호출 60회), `auth`(로그인·결제 문제), `rate_limit`(사용 한도).

## 결과

- [ ] 조건 1~6 모두 OK
- 발견한 이슈:
- 끝낸 날짜와 결론:
