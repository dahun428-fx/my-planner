# SP6 자동 복구 설계 (감시자 · 클라우드 수리 · 배포와 배포 롤백)

- 상태: 초안 v3 (Dahun 결정 Q1~Q7 반영, doc-reviewer 1·2차 반영, 2026-10-24)
- 작성일: 2026-10-24
- 상위 문서: [마스터 설계](2026-10-23-my-planner-master-design.md), [SP1 비서 코어](2026-10-23-sp1-secretary-core-design.md) (5.1 시작 순서, 7 로그·백업), [SP3-4 스펙](2026-10-24-sp3-4-life-curve-dashboard-design.md) (`GET /health` 6.3.1, API 계약의 정본), [SP5 운영 앱](2026-10-24-sp5-ops-app-design.md)
- 용어: [`GLOSSARY.md`](../../../GLOSSARY.md) (감시자, 업데이터, 장애, 지문, 배포 롤백을 이번에 추가). 결정 기록: [ADR 0010](../../adr/0010-full-auto-repair-in-cloud-laptop-only-deploys.md)
- 범위: BE(노트북의 my-planner), 운영 앱(`web/app/`), 대시보드(`web/dashboard/`, 생기면) 세 조각에서 장애를 감지하고, 사람 없이 고치고, 노트북에 배포하고, 실패하면 되돌린다.

## 1. 목표와 완료 조건

지금 있는 장치(SP1)는 **프로세스가 죽었을 때**만 다룬다: 작업 스케줄러 5분 감시 재시작, 시작 시 `running` 회차 복구, 놓친 회차 따라잡기, DB 무결성 실패 시 안전 모드. SP6은 **프로세스는 살아 있는데 일이 안 되는 경우**와 **코드 결함**을 다룬다. 고치는 일은 클라우드(GitHub Actions)의 Claude가 하고, 노트북은 감지·배포·배포 롤백만 한다.

**Dahun 결정 (2026-10-24)**

| # | 질문 | 결정 |
|---|---|---|
| Q1 | 어디까지 스스로 하나 | 완전 자동: 진단 → 수정 PR → 리뷰 → 머지 → 노트북 배포. 배포 뒤 확인 실패 시 자동 배포 롤백 |
| Q2 | 수리 에이전트 위치 | 클라우드. 노트북은 가린 장애 리포트를 GitHub 이슈로 올린다 |
| Q3 | 감지 대상 | BE·운영 앱·대시보드 모두. 에러(예외, 브라우저 에러, Vercel 빌드 실패) + 조용한 장애(회차 지연, 무응답, 헬스 실패). 노트북 꺼짐은 알림만 |
| Q4 | 금지선 | 없음. DB 마이그레이션, 인증, 의존성도 자동 수리 대상. 횟수 한도만 둔다 |
| Q5 | 알림 | 장애당 결과 한 번(고침 또는 못 고침) |
| Q6 | 조용한 장애 감지 | 노트북 감시자 + GitHub 하트비트. 클라우드는 tailnet 안의 BE에 닿지 않는다 |
| Q7 | 클라우드 수리 깨우기 | GitHub Actions 이벤트. 장애 이슈에 라벨이 붙으면 Claude Code 액션 실행. 하트비트 점검은 Claude 없이 Actions 정기 작업 |

**완료 조건 (수용 기준)**. 각 조건의 확인 절차는 12장.

1. BE에 일부러 넣은 결함이 배포되면, 첫 발생 후 10분 안에 `incident` 이슈가 하나 열리고, 같은 결함이 다시 나도 이슈는 늘지 않고 본문의 발생 수만 오른다.
2. 이슈에 `incident` 라벨이 붙으면 Actions가 수리를 시작하고, 결함을 재현하는 테스트 + 수정이 담긴 PR이 CI를 통과해 머지된다. 사람은 아무것도 누르지 않는다.
3. 머지 뒤 20분 안에 노트북 업데이터가 새 `main`을 배포하고, 확인이 통과하면 이슈를 닫고 주 통로로 "고쳤어요" 알림을 **한 번** 보낸다.
4. 배포 뒤 확인이 실패하면 업데이터가 직전에 배포된 커밋(`prev_sha`)으로 되돌리고(스키마가 바뀐 배포면 DB도 배포 직전 백업으로), 비서가 다시 답하며, 이슈에 `rolled-back`이 붙고 다음 수리 시도가 시작된다.
5. 같은 장애에 수리가 2번 **실패**(머지 못 함 또는 배포 롤백)하거나 오늘 자동 머지가 3번에 이르면 그 장애의 수리를 멈추고 `needs-dahun`을 붙이고 "못 고쳤어요" 알림을 한 번 보낸다.
6. 노트북을 끈 채 회차 예정 시각이 지나면, 그 회차 시각 + 15분 + GitHub cron 지연 안에(보통 30분 안) 텔레그램으로 "노트북 응답 없음"이 한 번 온다. 그날은 다시 오지 않는다.
7. 운영 앱에서 던져진 브라우저 에러가 BE를 거쳐 1번과 같은 길로 이슈가 되고, 수리 PR이 머지되면 Vercel이 다시 배포하고, 5.1의 웹 확인이 통과하면 이슈가 닫히고 "고쳤어요" 알림이 한 번 온다.
8. GitHub에 올라간 장애 이슈 어디에도 할 일 제목, 대화 본문, 컨디션 값, 메모, 사용자 폴더 경로(`C:\Users\…`)가 없다.

## 2. 전체 그림

```
노트북 (Windows, tailnet)                         GitHub (private repo)                     GitHub Actions
┌─────────────────────────────┐   이슈·라벨·댓글   ┌────────────────────────┐  issues:labeled  ┌──────────────────────┐
│ my-planner (BE, 기존 작업)    │ ───────────────▶ │ incident 이슈           │ ───────────────▶ │ repair.yml           │
│  ├ 로그 jsonl (이미 가림)     │                  │ heartbeat 이슈(본문 갱신) │                  │  claude-code-action  │
│  └ POST /client-errors (신규)│   하트비트        │                        │ ◀─────────────── │  재현 테스트 → 수정   │
│ my-planner-medic (신규 작업)  │ ───────────────▶ │ main                   │   PR (앱 신원)    │  셸 단계: CI 확인 → 머지│
│  ├ 감시자: 2분마다 점검        │                  └────────────────────────┘                  ├ ci.yml (PR·main)     │
│  └ 업데이터: 5분마다 main 확인  │ ◀── git fetch ──  main (CI 성공 커밋만 배포)                  ├ heartbeat.yml (cron) │
│      백업 → 배포 → 확인 → 롤백  │                                                            ├ vercel-failure.yml   │
└─────────────────────────────┘                   Vercel ◀── main 머지마다 자동 배포             └ repair-sweep (cron)  │
```

**원칙**

- 수리 에이전트는 노트북에 닿지 않는다. 노트북이 받는 것은 `ci.yml`이 성공한 `main` 커밋뿐이다.
- 감시자·업데이터(합쳐 **medic**)는 **결정적**이고 Claude를 부르지 않는다. BE와 다른 프로세스·다른 작업 스케줄러 작업이며, **표준 라이브러리만** 쓴다(`urllib`, `sqlite3`, `subprocess`, `json`). `my_planner` 패키지와 venv의 외부 패키지를 가져오지 않는다. 그래서 BE 코드나 의존성이 깨져도 medic은 돌고, `pip install` 중 venv 파일을 잠그지 않는다. 코드 위치: `src/my_planner_medic/`.
- BE가 단일 쓰기 주체라는 ADR 0007은 그대로다. medic은 `planner.db`에 쓰지 않고 자기 DB `state/medic.db`만 쓴다. 예외는 배포 롤백 때 `planner.db` 파일을 백업으로 바꾸는 것 하나이고, 그때 BE 작업은 꺼져 있다.
- 마스터 2절의 "상시 프로세스 하나"는 비서(BE)에 대한 결정이다. medic은 비서가 아니라 비서를 지키는 두 번째 작업이다(마스터 2절에 한 줄 추가).

## 3. 감지

### 3.1 신호

| 신호 | 출처 | 지문(fingerprint) |
|---|---|---|
| BE 예외 | `state/logs/my-planner.jsonl`의 `level` ERROR 이상 + `exc_type` | `be:` + 예외 종류 + `exc_where` 중 `my_planner` 안 가장 깊은 프레임의 `상대경로:함수` (없으면 마지막 프레임). 예: `be:KeyError src/my_planner/tools/todos.py:list_todos` |
| BE 경고 폭주 | 같은 로그의 WARNING 중 `logger`가 `my_planner*`인 것, 같은 이벤트 이름이 1시간에 20번 이상. `third_party_log`(외부 라이브러리, 대개 네트워크)는 세지 않는다 | `be-warn:` + 이벤트 이름 |
| 브라우저 에러 | 운영 앱·대시보드 → `POST /api/v1/client-errors`(3.3) → BE 로그 `client_error` | `<app>:` + 에러 이름 + 경로 틀(`route`) |
| 헬스 실패 | 감시자의 `GET http://127.0.0.1:8787/api/v1/health` (`.env`의 `API_TOKEN`으로 인증). **연속 3번**(6분) 실패일 때만 | `health:unreachable`(연결 안 됨·10초 초과), `health:auth`(401, 토큰 문제), `health:safe_mode`. `api_bind_error`가 로그에 있으면 `health:bind` |
| 회차 지연 | `/health`의 `runs_today[]`에서 `scheduled_for` + 15분이 지났는데 `status`가 `pending` | `late_run:` + `loop` |
| 무응답 | `/health`의 `inbound_pending_oldest_at`(3.4)이 10분보다 오래됨 | `no_reply` |
| Vercel 빌드 실패 | `main` 커밋의 Vercel 커밋 상태 `failure` (Actions가 직접 받음, 3.5) | `vercel:` + 상태 컨텍스트 |
| `main` CI 실패 | `main` 푸시의 `ci.yml` 실패 (Actions가 직접 받음, `workflow_run`). 머지된 조합이 깨져 배포가 멈추는 것을 막는다 | `ci:main` |

**코드 밖 사유는 수리하지 않는다.** 코드 밖 사유는 `polling: down`(네트워크), `brain.auth`가 `login`/`billing`, `limited_until`이 미래, `paused_until`이 미래(사용자가 멈춤)다. 이 중 하나라도 있으면 그동안 헬스 실패, 회차 지연, 무응답을 모두 세지 않는다(`/health`가 이 사유로만 `degraded`인 것도 실패가 아니다). 이 셋은 SP1(마스터 5.6)이 이미 하루 한 번 알리므로 medic은 따로 알리지 않는다. `health:safe_mode`도 SP1 5.1의 알림이 있으므로 이슈만 열고(기록용) 수리 라벨은 달지 않는다. 이 이슈에는 `incident` 대신 `record` 라벨만 단다(수리 트리거와 sweep이 집지 않는다). 자동 DB 복원은 하지 않는다(무결성 실패는 디스크 문제일 수 있다).

**API가 꺼져 있으면**: `.env`에 `API_TOKEN`이 없거나 `config.toml`의 `[api].enabled`가 `false`면 medic은 헬스·회차 지연·무응답 점검을 끄고 로그 신호만 본다. 그 상태를 하루 한 번 텔레그램으로 알린다("자동 복구가 API 없이 로그만 보고 있어요").

**절전 직후**: 직전 점검과 10분 이상 벌어졌으면 노트북이 막 깨어난 것으로 보고, 따라잡기가 끝나도록 10분 동안 회차 지연·무응답·헬스 실패를 세지 않는다. 업데이터가 배포·배포 롤백하는 동안과 그 뒤 3분도 세지 않는다.

**경로 가리기**: `exc_where`는 절대 경로다(`logging_setup.py`). medic은 저장소 루트 아래 경로는 저장소 기준 상대 경로로, 그 밖(venv의 라이브러리 등)은 `site-packages/` 뒤만 남기고, 나머지는 `<외부>`로 바꾼다.

### 3.2 감시자 동작

- 2분마다: 로그 파일에서 지난 위치 이후 줄을 읽고(자정 회전 파일 `my-planner.jsonl.YYYY-MM-DD` 포함, 위치는 `medic.db`), `/health`를 부르고, 신호를 지문으로 묶는다.
- 지문마다 `incidents` 행 하나(상태는 4.4 표).
- 새 지문이면 이슈를 연다(4.1). 열린 지문이면 10분에 한 번만 이슈 본문의 발생 수·마지막 시각을 고친다(본문 수정은 알림을 만들지 않는다).
- `resolved` 뒤 24시간 안에 같은 지문이 다시 나면 새 이슈 대신 그 이슈를 다시 열고 `recurred` 라벨을 단다. 실패 수는 이어진다.

### 3.3 브라우저 에러 보고 (BE API 추가)

`POST /api/v1/client-errors` (토큰 인증, 기존 64KB 제한). 본문:

```json
{"app": "app", "version": "a792f21", "route": "/today", "name": "TypeError",
 "frames": ["app-today.js:1:2345"], "at": "2026-10-24T11:00:00Z"}
```

- 에러 **메시지는 보내지 않는다**(사용자 글이 들어 있을 수 있다). `route`는 동적 조각을 `[id]`로 바꾼 경로 틀이다. `frames`는 자체 번들의 청크 이름에서 빌드 해시를 지운 것(`app-today.<hash>.js` → `app-today.js`)과 줄:열만.
- BE는 DB에 쓰지 않고 로그에 `client_error` 이벤트(필드 `app`, `version`, `route`, `name`, `frames`)로 남기고 `204`를 준다. 필드 길이를 넘으면 `422`.
- 앱은 같은 이름+경로를 한 번 열린 동안 한 번만, 분당 최대 5개 보낸다. 오프라인이면 버린다.

### 3.4 `/health` 추가 필드

`inbound_pending_oldest_at`: 받은 메시지 중 아직 답을 만들지 않은 가장 오래된 것의 시각, 없으면 `null`. SP3-4 6.3.1 표에 한 줄 더한다(이 PR에서 고침).

### 3.5 하트비트와 Vercel

- 감시자는 30분마다 고정 이슈 "heartbeat"(라벨 `heartbeat`)의 **본문**을 `last_seen: <UTC>, sha: <배포된 커밋>, next_run: <다음 회차 예정 시각 UTC>`로 바꾼다. `next_run`은 `config.toml`의 `[schedule]`과 `timezone`으로 계산한 다음 회차 예정 시각이다(오늘 남은 것이 없으면 내일 것). medic은 `tomllib`(표준 라이브러리)로 읽는다.
- `heartbeat.yml`(15분 cron, Claude 없음)은 `last_seen`이 45분보다 오래되었고 **`next_run`이 이미 지났으면** 텔레그램으로 "노트북 응답이 없어요. 꺼짐·잠자기·고장 중 하나예요. 지나간 회차는 켜지면 따라잡아요."를 보낸다. Asia/Seoul 하루에 한 번만 보낸다(이슈에 `stale-YYYY-MM-DD` 라벨로 표시). 회차가 지나지 않은 잠자기에는 보내지 않는다(P1).
- 알림 시각은 `max(last_seen + 45분, next_run)` 뒤 첫 cron 실행이다. GitHub cron은 부하에 따라 수십 분 늦을 수 있다(완료 조건 6).
- Vercel 빌드 실패는 노트북을 거치지 않는다. `vercel-failure.yml`이 `status` 이벤트(컨텍스트가 `Vercel`로 시작, `failure`, 브랜치 `main`)를 받아 같은 지문의 열린 이슈가 없으면 `incident` 이슈를 연다(10장 S4). 같은 워크플로가 `workflow_run`(`ci`, 브랜치 `main`, `failure`)도 받아 `ci:main` 지문으로 같은 일을 한다. 둘 다 이슈는 `REPAIR_PAT`으로 연다(4.2).

## 4. 클라우드 수리

### 4.1 장애 이슈 형식

제목 `[incident] <지문>`, 라벨 `incident` + 조각 라벨(`be`, `app`, `dashboard`). 본문은 medic이 만드는 고정 틀이며 **허용 목록**(7장)만 담는다:

- 지문, 처음·마지막 시각, 발생 수, 배포된 커밋
- 예외 종류와 가린 호출 스택(3.1)
- 직전 30분 로그 중 `ts`, `level`, `logger`, `msg`(이벤트 이름), `exc_type`, 가린 `exc_where` 열만
- `/health` 중 `status`, `polling`, `brain.auth`, `runs_today[].loop/status/scheduled_for`, `errors.by_event`, `version`

### 4.2 GitHub 신원

워크플로 안의 기본 `GITHUB_TOKEN`으로 만든 이슈·푸시·머지는 **다른 워크플로를 깨우지 않는다**. 그래서 쓰기는 모두 다른 신원으로 한다.

| 쓰기 | 신원 |
|---|---|
| medic이 이슈 열기·라벨·본문 수정 | 노트북 `.env`의 `MEDIC_GITHUB_TOKEN` (fine-grained PAT, 이 저장소만: Issues 읽기·쓰기, Contents 읽기, Actions 읽기, Commit statuses 읽기) |
| `vercel-failure.yml`의 이슈 열기, `repair.yml`의 라벨·머지, `repair-sweep` | 저장소 시크릿 `REPAIR_PAT` (fine-grained PAT, 이 저장소만: Issues·Pull requests·Contents 읽기·쓰기, Actions 읽기) |
| 수리 브랜치 푸시·PR 열기 | `claude-code-action`이 쓰는 Claude GitHub App 토큰. 안 되면 `REPAIR_PAT`(10장 S1) |

PAT은 만료일을 1년으로 두고, 만료 30일 전부터 `heartbeat.yml`이 하루 한 번 텔레그램으로 알린다(만료일은 저장소 변수 `PAT_EXPIRES`). medic의 `git fetch`는 같은 `MEDIC_GITHUB_TOKEN`을 Git 자격 증명으로 쓴다.

### 4.3 `repair.yml`

- **트리거**: `issues`의 `labeled` 하나만. 라벨이 `incident`, `rolled-back`, `recurred` 중 하나일 때. (라벨을 단 채 이슈를 열면 `opened`와 `labeled`가 둘 다 와서, `opened`는 쓰지 않는다.) 그리고 `repair-sweep`(30분 cron)이 열린 `incident` 이슈 중 `needs-dahun`·`repairing`·`merged`가 없는 것을 골라 `workflow_dispatch`(입력 `issue`)로 부른다(이벤트를 놓쳤거나 줄이 밀린 경우). 또 `repairing`인데 그 이슈의 `repair.yml` 실행이 진행 중이 아니면(취소·시간 초과로 죽은 시도) 그 시도를 정리한다: 열린 수리 PR이 CI 성공 상태면 머지 단계만 다시 돌리고(같은 PR 재사용), 아니면 PR을 닫고 브랜치를 지우고 `repairing`을 떼고 `failed-N`을 하나 올린다.
- **동시성**: `concurrency: repair-${{ github.event.issue.number || inputs.issue }}`, `cancel-in-progress: false`. 서로 다른 장애는 동시에 고칠 수 있고, 머지 단계는 `concurrency: repair-merge`로 하나씩 한다(같은 그룹 대기 하나만 남는 GitHub 동작 때문에 머지는 대기 대신 `repair-sweep`이 다시 집는다).
- **시작 전 검사**(셸, Claude 없음): 저장소 변수 `AUTO_REPAIR`가 `off`면 멈춤. 이슈 라벨의 실패 수(`failed-1`, `failed-2`)가 `REPAIR_MAX_FAILURES`(저장소 변수, 기본 2) 이상이거나, 오늘(Asia/Seoul) `auto-repair` 라벨로 머지된 PR이 `REPAIR_MAX_MERGES_PER_DAY`(기본 3) 이상이면 `needs-dahun`을 달고 실패 알림(6장) 후 멈춤. 통과하면 `repairing` 라벨을 단다.
- **Claude 단계**: `anthropics/claude-code-action`, 인증은 시크릿 `CLAUDE_CODE_OAUTH_TOKEN`(Dahun의 구독 로그인, 10장 S1). 프롬프트는 `.github/repair-prompt.md`. 순서:
  1. 이슈 본문으로 원인을 찾고 **실패하는 테스트를 먼저** 쓴다. 재현하지 못하면 진단만 이슈 댓글로 남기고 끝낸다(실패로 셈).
  2. 고치고 `ruff check`, `pytest`, 바뀐 웹 앱의 `npm test`·`npm run build`를 통과시킨다.
  3. 브랜치 `auto-repair/<이슈>-<시도>`로 PR을 연다. 본문 첫 줄 `Repairs #<이슈>`, 원인·수정·재현 테스트·되돌리는 법. 라벨 `auto-repair`.
  4. `.claude/agents/code-reviewer.md` 리뷰를 돌려 BLOCKER/SHOULD를 고친다(기존 작업 규칙과 같다).
  5. 재시도(`rolled-back`, `recurred`)이고 조각이 `app`/`dashboard`면 "직전 수리 PR을 `git revert`하는 것부터 검토"를 더한다.
- **머지 단계**(셸, Claude 없음): PR 머리 커밋의 `ci.yml` 실행이 끝날 때까지 기다려 결과를 `GET /actions/runs?head_sha=`로 직접 확인한다. 필수 검사 설정이 없을 수 있어서 `--required` 검사에 기대지 않는다(10장 S6). 성공이면 `REPAIR_PAT`으로 `gh pr merge <PR> --squash --body "Repairs #<이슈>"`로 머지하고(squash 커밋 본문은 저장소 설정에 따라 PR 본문을 담지 않으므로 명시한다) 이슈의 `repairing`을 `merged`로 바꾼다. CI가 실패하면 Claude 단계를 한 번 더 돌린다(같은 시도 안에서 최대 1회). 그래도 실패면 `failed-N` 라벨을 하나 올리고 `repairing`을 뗀다 → `repair-sweep`이 다음 시도를 집는다.
- 금지선은 두지 않는다(Q4). 머지는 **CI 성공 확인**이 필수이고, 그것을 Claude가 아니라 셸 단계가 한다. 저장소 플랜이 브랜치 보호를 지원하면 `main`에 `ci.yml` 필수 검사도 건다.

### 4.4 장애 상태

| 상태 (`medic.db`) | GitHub 라벨 | 누가, 언제 |
|---|---|---|
| `open` | `incident` | medic이 새 지문을 볼 때 |
| `repairing` | `repairing` | `repair.yml` 시작 전 검사 통과 |
| `merged` | `merged` | `repair.yml` 머지 단계. medic은 `main` 커밋 메시지의 `Repairs #N`으로 커밋과 이슈를 잇는다 |
| `deploying` | (없음) | 업데이터가 그 커밋을 포함한 배포를 시작 |
| `resolved` | 이슈 닫힘 | BE: 5장 6단계 확인 통과. 웹: 5.1 웹 확인 통과. 결과 알림 "고쳤어요" |
| `open` (다시) | `rolled-back`, `failed-N` +1 | 확인 실패로 배포 롤백. 롤백한 배포에 `Repairs #N` 커밋이 없으면(사람 커밋) 롤백을 일으킨 새 지문으로 새 이슈를 열고, 그 이슈 본문에 롤백한 커밋 범위를 적는다 |
| `gave_up` | `needs-dahun` | 실패 수 한도, 하루 머지 한도, 롤백 뒤 확인까지 실패. 결과 알림 "못 고쳤어요" |

"시도"는 실패 수로 센다. 성공하면 끝나므로 시작 수와 같지 않다.

### 4.5 `ci.yml` (신규, 지금 저장소에는 CI가 없다)

PR과 `main` 푸시에서: BE는 `windows-latest`(필수)와 `ubuntu-latest`에서 `pip install -r requirements.lock` → `pip install -e . --no-deps` → `ruff check` → `pytest`. 웹은 바뀐 앱만 `npm ci && npm test && npm run build`. medic 테스트(`tests/medic/`)는 BE 테스트와 함께 돈다.

## 5. 노트북 배포와 배포 롤백 (업데이터)

medic 프로세스 안에서 5분마다:

1. `git fetch origin main`. 새 커밋이 없으면 끝. 작업 폴더가 깨끗하지 않으면(손으로 고친 파일) 배포하지 않고 하루 한 번 알림.
2. 새 머리 커밋의 `ci.yml` 실행이 `success`인지 `GET /repos/{owner}/{repo}/actions/runs?head_sha=<sha>&event=push`로 확인한다. 진행 중이면 다음 회차에, 실패면 그 커밋은 건너뛰고 더 새 커밋을 기다린다. `medic.db`의 `bad_shas`에 있는 커밋도 건너뛴다.
3. **재시작이 필요한가**: `prev_sha..new_sha` 사이에 바뀐 파일이 `src/`, `requirements.lock`, `pyproject.toml`, `config.toml`, `scripts/` 중 하나에도 없으면 `git merge --ff-only`만 하고 끝(문서·웹만 바뀐 커밋). 웹 장애의 해결은 5.1이 맡는다.
4. **기다리기**: `/health`의 `runs_today`에 `running` 회차가 있거나 `inbound_pending_oldest_at`가 있으면 다음 회차로 미룬다. 30분 넘게 미뤄지면 그냥 진행한다.
5. **배포**: `PRAGMA user_version`을 `schema_before`로 읽음(읽기 전용 연결) → `medic.db`에 `deploy_in_progress = {prev_sha, new_sha, schema_before, started_at}`를 적는다 → `Disable-ScheduledTask my-planner` → `Stop-ScheduledTask my-planner`(진행 중 두뇌 호출은 SP1 5.1 복구에 맡김) → DB를 `state/backups/pre-deploy-<prev_sha>.db`로 백업(SQLite 백업 API) → `git merge --ff-only` → `requirements.lock`이 바뀌었으면 `pip install -r requirements.lock` → `pip install -e . --no-deps`(`/health`의 `version`이 패키지 정보에서 나온다) → `Enable-ScheduledTask my-planner` → `Start-ScheduledTask my-planner`.
   - 끄기를 먼저 하는 이유: 작업의 5분 감시 트리거와 `RestartOnFailure`가 배포 도중 BE를 다시 띄우지 않게(README 백업 복구 절차와 같다).
6. **확인**(최대 13분): `/health`가 3분 안에 `status: ok`(3.1의 코드 밖 사유만 있는 `degraded`도 통과)로 답하고, 그 뒤 `verify_minutes`(10분) 동안 **새 지문**의 ERROR, `late_run`, `no_reply`가 없고, **이번 배포가 `Repairs #N`으로 고친 지문**도 다시 나지 않으면 성공. 성공하면 `deploy_in_progress`를 지우고, 이 배포에 `Repairs #N`으로 들어간 장애를 `resolved`로 바꾸고 이슈를 닫고, 장애마다 "고쳤어요" 알림(6장).
7. **배포 롤백**(확인 실패): `Disable-` → `Stop-ScheduledTask my-planner` → `git reset --hard <prev_sha>` → 의존성 다시 설치(5단계와 같은 두 명령) → **스키마가 바뀐 배포에서만**(`schema_before` ≠ 지금 `user_version`) DB 되돌림: 지금 `planner.db`, `planner.db-wal`, `planner.db-shm` 셋을 함께 `state/backups/failed-<new_sha>/`로 옮기고 `pre-deploy-<prev_sha>.db`를 `planner.db`로 복사 → `Enable-` → `Start-ScheduledTask my-planner` → 확인을 한 번 더. `new_sha`를 `bad_shas`에 넣고 4.4 표대로 이슈를 고친다.
   - 스키마가 그대로면 DB는 건드리지 않는다. 회차·전달 기록이 되돌아가 같은 회차가 다시 나가는 일을 막으려는 것이다.
8. 배포 롤백 뒤 확인까지 실패하면 더 손대지 않고 `gave_up` + 실패 알림. 이때는 텔레그램으로 직접 보낸다(BE가 안 될 수 있다). BE 작업은 켜 둔 채 둔다.

**시작 시 복구**: medic이 시작할 때 `deploy_in_progress`가 남아 있으면(배포 도중 medic이 죽음) 7단계 배포 롤백을 끝까지 하고, 마지막에 `my-planner` 작업이 꺼져 있으면 반드시 켠다. medic이 어떤 길로 끝나도 `my-planner` 작업이 꺼진 채 남지 않게 하는 것이 이 규칙의 목적이다.

**medic 자신의 갱신**: 배포에 `src/my_planner_medic/`이 바뀌었으면 확인 성공 뒤 medic이 스스로 끝나고, `my-planner-medic` 작업의 5분 감시 트리거가 새 코드로 다시 띄운다. 새 medic이 시작 직후 60초 안에 3번 연속 죽으면 작은 실행기 `scripts/medic_boot.py`(표준 라이브러리, 20줄)가 `state/medic-last-good.json`의 커밋으로 `src/my_planner_medic/`만 되돌린다(`git checkout <sha> -- src/my_planner_medic`). 그 배포의 `new_sha`를 `bad_shas`에 넣고, 되돌린 경로의 차이는 깨끗함 검사(1단계)에서 빼며, 다음 배포 때 `git merge` 전에 `git checkout HEAD -- src/my_planner_medic`으로 정리한다. 이것도 안 되면 하트비트가 끊겨 3.5의 알림이 간다. `my-planner-medic` 작업이 실행하는 파일은 `medic_boot.py`이고, 이것이 medic을 띄운다.

**보관**: `pre-deploy-*.db`는 최근 5개, `failed-*/`는 최근 3개만 남긴다(medic이 지움. `store/backup.py`의 일일 백업 보관 규칙과 따로다).

**받아들이는 손실**: 스키마가 바뀐 배포를 되돌리면 배포와 롤백 사이(최대 약 15분)에 쓴 할 일·컨디션이 사라진다. 그 사이 대화 원문은 `data/transcripts/`에 남고, 실패 DB는 `failed-<sha>/`에 WAL과 함께 남아 손으로 되살릴 수 있다.

### 5.1 운영 앱·대시보드 (웹 확인)

Vercel이 `main` 머지마다 배포한다. Vercel 토큰은 두지 않는다. medic은 `merged` 상태의 웹 장애(`app`, `dashboard`, `vercel` 지문)마다:

1. 그 `Repairs #N` 커밋(또는 더 새 `main` 커밋)의 Vercel 커밋 상태가 `success`가 될 때까지 기다린다(`GET /commits/{sha}/status`, Commit statuses 읽기 권한).
2. 그 뒤 `web_verify_minutes`(60분) 동안 같은 지문의 `client_error`가 없으면 `resolved`: 이슈를 닫고 "고쳤어요" 알림. `vercel:` 지문은 1번의 `success`만으로 `resolved`.
3. 같은 지문이 다시 나면 `rolled-back` 대신 `failed-N` +1과 `recurred` 라벨 → 다음 시도(재시도 프롬프트는 "직전 수리 PR을 `git revert`하는 것부터 검토").
4. 3시간 안에 Vercel 상태가 `success`가 되지 않으면 `failed-N` +1.

앱을 아무도 열지 않으면 `client_error`가 안 나므로 2번은 "쓰는 동안 재발 없음"이 아니라 "60분 동안 보고 없음"이다(받아들임).

**모든 `main` 커밋이 배포된다**: 업데이터는 수리 PR만이 아니라 CI가 성공한 모든 `main` 커밋을 배포한다. 노트북에서 손으로 `git pull`하던 일이 없어진다.

## 6. 알림

장애 하나에 결과 알림 **한 번**(Q5). 시작 알림은 없다.

| 결과 | 문구 (틀) | 보내는 길 |
|---|---|---|
| 고침 | "🔧 자동으로 고쳤어요: <PR 제목>. <PR 링크>" | medic → BE `POST /api/v1/internal/notify` → 실제 통로(앱 푸시, 안 되면 텔레그램) |
| 못 고침 | "⚠️ 자동으로 못 고쳤어요: <지문>. 지금은 <이전 버전으로 돌려 둠/그대로>. <이슈 링크>" | BE가 답하면 위와 같은 길, 아니면 medic이나 Actions가 텔레그램 API로 직접 |
| 노트북 응답 없음 | 3.5 | `heartbeat.yml` → 텔레그램 |
| PAT 만료 임박 | "GitHub 토큰이 <날짜>에 만료돼요" | `heartbeat.yml` → 텔레그램 |

`POST /api/v1/internal/notify`: 기존 API 토큰 인증(원격 주소 검사는 `tailscale serve`가 127.0.0.1로 프록시하므로 쓰지 않는다). 본문 `{"text": …, "kind": "recovery"}`. BE는 기존 전달 경로(`harness/delivery`, 실제 통로 선택)로 보내고 DB에는 쓰지 않는다(`run_deliveries`는 회차 전용이라 맞지 않다). 보낸 사실은 로그 이벤트 `recovery_notice_sent`(필드 `channel`)로만 남긴다. 두뇌는 거치지 않는다.

**P1(피로를 늘리지 않는다)과 마스터 5.5의 하루 3회**: 복구 알림은 비서가 먼저 거는 "연락"이 아니라 시스템 알림이라 하루 3회 상한에 세지 않는다. 대신 복구 알림끼리 하루 최대 `max_notices_per_day`(5)개로 묶고, 넘치면 그날 남은 것은 다음 아침 브리핑 앞에 한 줄 묶음으로 붙인다. 마스터 5.5에 이 예외를 한 줄 더한다.

기록: GitHub 이슈·PR이 정본이다. 대시보드·운영 앱의 "복구 기록" 화면은 2단계(9장).

## 7. 개인 데이터 (P5)

P5는 "GitHub에는 코드와 문서만"이다. 장애 이슈는 그 예외이고, 마스터 P5에 "가린 진단 정보(SP6 7장 허용 목록)만 이슈로 올린다"를 더한다. 이슈에 올라가는 것은 **허용 목록**뿐이다: 지문, 예외 종류, 가린 파일·줄·함수, 이벤트 이름, 수준, 로거 이름, 횟수, 시각, 커밋, 4.1의 `/health` 필드, 3.3의 `client_error` 필드. 로그 줄의 그 밖의 필드는 버린다. 기존 로그도 본문을 남기지 않지만(SP1 7) 이중으로 막는다.

## 8. 비밀값과 설정

| 어디 | 이름 | 누가 넣나 |
|---|---|---|
| 저장소 시크릿 | `CLAUDE_CODE_OAUTH_TOKEN` | Dahun (노트북에서 `claude setup-token`) |
| 저장소 시크릿 | `REPAIR_PAT` | Dahun (4.2 권한) |
| 저장소 시크릿 | `TELEGRAM_BOT_TOKEN`, `OWNER_TELEGRAM_ID` | Dahun (`.env`와 같은 값) |
| 저장소 변수 | `AUTO_REPAIR`(`on`/`off`, 끄는 스위치), `REPAIR_MAX_FAILURES`(2), `REPAIR_MAX_MERGES_PER_DAY`(3), `PAT_EXPIRES` | Dahun / 기본값 |
| 노트북 `.env` | `MEDIC_GITHUB_TOKEN` (4.2) | Dahun |
| `config.medic.toml` | 노트북 쪽 값 (아래). BE의 `Settings`는 모르는 절을 거부하므로(`extra="forbid"`) `config.toml`과 나눈다 | Git |

`config.medic.toml` 기본값 (Claude가 정함): `enabled = true`, `watch_interval_s = 120`, `deploy_interval_s = 300`, `heartbeat_minutes = 30`, `late_run_grace_minutes = 15`, `no_reply_minutes = 10`, `health_fail_streak = 3`, `verify_minutes = 10`, `web_verify_minutes = 60`, `max_notices_per_day = 5`, `keep_pre_deploy = 5`, `keep_failed = 3`. 실패·머지 한도는 Actions가 읽으므로 저장소 변수에만 둔다(정본 하나).

## 9. 나누기 (단계)

- **1단계(이 스펙)**: medic(감시자 + 업데이터 + 배포 롤백 + `medic_boot.py`), 워크플로 5개(`ci`, `repair`, `repair-sweep`, `heartbeat`, `vercel-failure`)와 `.github/repair-prompt.md`, BE `POST /client-errors`·`POST /internal/notify`·`/health` 필드, 운영 앱 에러 보고, 작업 스케줄러 작업 `my-planner-medic`(실행 파일 `scripts/medic_boot.py`, 로그온 + 5분 감시 트리거; `register_task.ps1`, `check_tasks.ps1`, 새 XML 틀 `task_my-planner-medic.xml.tmpl`), README "자동 복구" 절(시크릿 넣기, 끄는 법, 손으로 되살리기).
- **2단계**: 대시보드·운영 앱의 "복구 기록" 화면(`GET /api/v1/incidents`), 대시보드 에러 보고(대시보드가 생긴 뒤), 소스맵으로 브라우저 스택 풀기.

## 10. 미리 확인할 것 (스파이크)

| # | 질문 | 실패하면 |
|---|---|---|
| S1 | `claude-code-action`이 `CLAUDE_CODE_OAUTH_TOKEN`(구독)으로 private 저장소에서 브랜치 푸시·PR 열기가 되고, **그 PR이 `ci.yml`을 깨우는가** | PR 열기를 `REPAIR_PAT`으로. 구독 토큰이 안 되면 API 키로 바꾸고 ADR 0001에 예외를 적는다 |
| S2 | 기존 테스트가 `windows-latest`에서 통과하는가 | 실패 테스트를 고치는 티켓을 먼저 둔다 |
| S3 | medic(일반 권한, `pythonw`)이 `Disable-/Stop-/Enable-/Start-ScheduledTask my-planner`를 할 수 있는가 | `my-planner` 작업을 같은 사용자가 등록했으면 될 것으로 본다. 안 되면 BE에 토큰 인증 종료 엔드포인트를 두고, 끄기는 작업 XML의 감시 트리거 대신 medic이 맡는다 |
| S4 | Vercel 커밋 상태가 `status` 이벤트로 Actions를 깨우는가 | `repair-sweep` cron이 `main` 머리 커밋의 상태를 읽는다 |
| S5 | BE를 멈춘 뒤 `git merge`·`pip install`이 Windows 파일 잠금 없이 되는가(medic은 venv 패키지를 불러오지 않으므로 잠그지 않아야 한다) | venv를 커밋별 폴더로 두고 작업 XML이 가리키는 경로를 바꾸는 방식으로 |
| S6 | 저장소 플랜(GitHub Free, private)에서 브랜치 보호·룰셋을 쓸 수 있는가 | 쓸 수 없어도 4.3 머지 단계의 셸 확인이 막는다. 쓸 수 있으면 함께 건다 |

## 11. 위험과 대가

- **금지선이 없다(Q4)**: 수리가 테스트를 약화하거나 인증을 느슨하게 할 수 있다. 막는 것은 CI(셸 단계가 확인), 리뷰 에이전트, 실패·머지 한도, `AUTO_REPAIR` 스위치, 배포 전 DB 백업뿐이다. Dahun이 받아들인 대가다.
- **고친 것이 다른 것을 망가뜨림**: 확인 창(10분) 밖에서 나는 결함은 새 장애로 다시 잡힌다. 한도가 무한 반복을 막는다.
- **구독 사용량**: 수리 한 번이 Claude 실행 하나다. 하루 머지 3개 한도와 실패 2회 한도가 상한 역할도 한다.
- **노트북 꺼짐과 고장을 구분 못 함**: 알림 문구가 셋 다 말한다.
- **medic 자신의 결함**: `medic_boot.py`가 마지막 방어선이고, 그것도 안 되면 하트비트 알림으로 Dahun이 안다.

## 12. 확인 절차 (완료 조건별)

모두 결함 주입 브랜치를 `main`에 머지한 뒤 실제 노트북에서 한다. 단위 테스트는 `pytest tests/medic -q` → `N passed`.

| 조건 | 절차 | 기대 결과 |
|---|---|---|
| 1 | 테스트가 닿지 않는 개발용 텔레그램 명령 `/medic_probe`(환경 변수 `MEDIC_PROBE=1`일 때만 등록, `raise KeyError("probe")`)를 넣은 PR을 머지하고, 배포 확인(10분)이 끝난 뒤 노트북에서 `MEDIC_PROBE=1`을 켜고 `/medic_probe`를 두 번 | 10분 안에 `gh issue list -l incident` → 이슈 1개, 제목 `[incident] be:KeyError src/my_planner/bot/…`, 본문 발생 수 2 |
| 2 | 위 이슈 | `gh pr list -l auto-repair --state merged` → 1개, PR에 재현 테스트 추가, `ci.yml` success (수리는 명령을 지우거나 고친다. 어느 쪽이든 통과) |
| 3 | 위 머지 뒤 | 20분 안에 이슈 닫힘, 주 통로 알림 "🔧 자동으로 고쳤어요" 1개, `/health`의 `version.app`이 새 커밋 |
| 4 | `MEDIC_PROBE_HEALTH=1`일 때만 `/health`가 500을 주는 분기를 넣은 PR을 머지(CI는 통과), 노트북에서 그 변수를 켜고 다음 배포(문서 한 줄 수정 + `src/` 주석 한 줄)를 머지 | 확인 실패 → `git -C <repo> rev-parse HEAD`가 `prev_sha`. 사람 커밋이므로 4.4대로 `health:…` 지문의 새 이슈가 열리고 본문에 롤백한 커밋 범위, `repair.yml` 새 실행 |
| 5 | `AUTO_REPAIR=on`, 재현 불가능한 지문의 가짜 이슈를 `MEDIC_GITHUB_TOKEN`으로 열기 | 2번 실패 뒤 `needs-dahun`, 알림 "⚠️ 자동으로 못 고쳤어요" 1개 |
| 6 | 저녁 체크인 30분 전 노트북 종료 | 체크인 시각이 지나고 마지막 하트비트 뒤 75분 안에 텔레그램 "노트북 응답이 없어요" 1개. 같은 날 다시 없음 |
| 7 | 운영 앱에 개발용 "에러 던지기" 버튼(빌드 플래그로만 보임)을 누름 | 10분 안에 `[incident] app:Error /settings` 이슈. 수리 머지 → Vercel `success` → 60분 뒤 이슈 닫힘, 알림 1개 |
| 8 | `pytest tests/medic/test_redaction.py` (할 일 제목·대화·메모·`C:\Users\dahun` 경로가 든 가짜 로그와 health로 이슈 본문 생성) | 그 문자열이 본문에 하나도 없음, `1 passed` |
