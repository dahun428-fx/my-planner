# 아이콘 목록 (icons.svg)

픽토그램 124개. 모두 24px 격자, 선 1.75, 둥근 끝, `currentColor`입니다.

```html
<svg class="ic" aria-hidden="true"><use href="#i-curve"/></svg>
```

- 크기: `ic`(1.25em) · `ic--sm`(1em) · `ic--lg`(28px) · `ic--xl`(40px). 색은 글자색을 따릅니다.
- 원본은 `icons.svg`입니다. 고친 뒤 `python3 docs/deliverables/assets/build-icons.py`로 `icons.js`를 맞춥니다(foundation 에이전트만).
- 없는 아이콘은 페이지 맨 위 숨긴 `<svg>`에 페이지 전용 `<symbol>`로 그립니다(같은 24px · 1.75 · round 규칙, id는 `p-`로 시작 권장).

## 영역

| id | 뜻 |
|---|---|
| `i-career` | 커리어 영역(career) |
| `i-finance` | 경제 영역(finance) |
| `i-health` | 건강 영역(health) |
| `i-relationships` | 관계 영역(relationships) |
| `i-learning` | 배움 영역(learning) |
| `i-quality-of-life` | 삶의 질 영역(quality_of_life). 휴식도 여기에 든다 |

## 회차와 명령

| id | 뜻 |
|---|---|
| `i-sun` | 아침 브리핑 회차 |
| `i-moon` | 저녁 체크인 회차 |
| `i-calendar-week` | 주간 회고 회차. 사이트 로고로도 쓴다 |
| `i-return` | 복귀 인사(오래 쉬고 돌아왔을 때) |
| `i-pause` | 멈춤(/pause) |
| `i-plan` | 계획 모드(/plan) |

## 할 일

| id | 뜻 |
|---|---|
| `i-task` | 할 일 |
| `i-draft` | 초안 할 일(확정 전) |
| `i-priority` | 우선순위(주기당 최대 3개) |
| `i-first-step` | 첫 걸음(15~30분짜리 시작 행동) |
| `i-condition` | 컨디션 1~5 |
| `i-check` | 확인·완료 |
| `i-x` | 빼기·닫기 |
| `i-plus` | 추가 |

## 구성 요소

| id | 뜻 |
|---|---|
| `i-chat` | 대화 |
| `i-telegram` | 텔레그램 메시지·채널 |
| `i-brain` | 두뇌(Claude Agent SDK) |
| `i-harness` | 하네스(메시지와 회차를 두뇌에 잇는 코어) |
| `i-plug` | 도구 서버(MCP) |
| `i-tool` | 도구 함수 하나 |
| `i-command` | 텔레그램 명령(/today 등) |

## 저장과 기록

| id | 뜻 |
|---|---|
| `i-user` | 사용자(Dahun) |
| `i-bot` | 비서 봇 |
| `i-database` | 데이터베이스(SQLite) |
| `i-file-md` | 마크다운 파일·원천 문서 |
| `i-folder` | 폴더 |
| `i-backup` | 백업 |
| `i-log` | 시스템 로그 |
| `i-transcript` | 원문 기록(날짜별 md) |
| `i-redact` | 민감 정보 가리기 |

## 시간과 실행

| id | 뜻 |
|---|---|
| `i-clock` | 시각·작성일 |
| `i-timer` | 타이머(tick) |
| `i-laptop` | 노트북(Windows 11, BE가 도는 곳) |
| `i-power` | 절전 깨우기·전원 |
| `i-scheduler` | Windows 작업 스케줄러 |
| `i-refresh` | 다시 시도 |

## 상태와 표시

| id | 뜻 |
|---|---|
| `i-lock` | 잠금·보안 |
| `i-shield` | 보호·상한 |
| `i-warning` | 주의 |
| `i-info` | 정보 |
| `i-decision` | 결정(ADR) |
| `i-question` | 미정·확인 필요 |
| `i-test` | 테스트 |

## 문서

| id | 뜻 |
|---|---|
| `i-doc-requirements` | 문서: 요구사항 정의서 |
| `i-doc-architecture` | 문서: 아키텍처 설계서 |
| `i-doc-flow` | 문서: 업무 흐름도(BPMN) |
| `i-doc-behavior` | 문서: 동작 명세(상태·순서도) |
| `i-doc-screen` | 문서: 화면설계서 |
| `i-doc-schema` | 문서: 데이터베이스 설계서 |
| `i-doc-interface` | 문서: 인터페이스 정의서 |
| `i-doc-test` | 문서: 시험 결과서 |
| `i-doc-manual` | 문서: 운영 매뉴얼 |
| `i-doc-schedule` | 문서: 일정·로드맵 |
| `i-doc-glossary` | 문서: 용어집 |

## 길 찾기

| id | 뜻 |
|---|---|
| `i-menu` | 문서 목록 열기(폰) |
| `i-chevron-down` | 펼치기 |
| `i-chevron-right` | 다음·하위로 |
| `i-arrow-right` | 이동 |
| `i-external` | 바깥 링크(GitHub 등) |
| `i-link` | 링크 |

## BPMN

| id | 뜻 |
|---|---|
| `i-bpmn-start` | BPMN 시작 이벤트(얇은 원) |
| `i-bpmn-end` | BPMN 종료 이벤트(굵은 원) |
| `i-bpmn-timer` | BPMN 타이머 시작 이벤트 |
| `i-bpmn-message` | BPMN 메시지 이벤트 |
| `i-bpmn-task` | BPMN 작업(둥근 사각형) |
| `i-bpmn-xor` | BPMN 배타 게이트웨이(하나만 고름) |
| `i-bpmn-and` | BPMN 병렬 게이트웨이(모두 진행) |
| `i-bpmn-flow` | BPMN 시퀀스 흐름(실선 화살표) |
| `i-bpmn-msgflow` | BPMN 메시지 흐름(점선 화살표) |
| `i-bpmn-lane` | BPMN 풀·레인(맡는 쪽) |

## ERD

| id | 뜻 |
|---|---|
| `i-erd-one` | ERD 정확히 하나 |
| `i-erd-zero-one` | ERD 0 또는 하나 |
| `i-erd-one-many` | ERD 하나 이상 |
| `i-erd-zero-many` | ERD 0 이상 |

## v2 시스템·배포

| id | 뜻 |
|---|---|
| `i-dashboard` | 웹 대시보드(읽기 전용, Vercel) |
| `i-browser` | 웹 브라우저 창 |
| `i-phone` | 아이폰(운영 앱을 여는 기기) |
| `i-pwa` | 홈 화면 앱(PWA, 운영 앱) |
| `i-api` | BE HTTP API(/api) |
| `i-cors` | 허용 출처(CORS) 검사 |
| `i-token` | API 토큰(접근 열쇠). 값은 문서에 적지 않는다 |
| `i-push` | 웹 푸시 알림 |
| `i-tailscale` | Tailscale 사설망(tailnet). BE는 이 안에서만 열린다 |
| `i-vercel-cloud` | Vercel 정적 호스팅(운영 앱·대시보드) |
| `i-github` | GitHub 저장소·브랜치·PR |

## v2 인생 곡선·상태창

| id | 뜻 |
|---|---|
| `i-curve` | 인생 곡선 |
| `i-ladder` | 사다리 점수(0~10, 월 1회) |
| `i-radar` | 영역 점수(레이더 차트) |
| `i-milestone` | 사건(마일스톤) |
| `i-chapter` | 챕터(인생의 한 시기) |
| `i-xp` | 경험치(XP). 오르기만 한다 |
| `i-level` | 레벨 |
| `i-title-badge` | 칭호 배지 |

## v2 운영 앱·습관

| id | 뜻 |
|---|---|
| `i-habit` | 습관과 습관 체크(SP7) |
| `i-undo` | 되돌리기 |
| `i-activity` | 활동 기록(누가 무엇을 바꿨나) |
| `i-card` | 카드(화면 조각) |
| `i-pin` | 오늘 화면에 고정한 카드 |
| `i-genui` | 생성형 UI(비서가 고르는 미리 만든 부품) |
| `i-stream` | 스트리밍 응답(SSE) |

## v2 자동 복구·운영

| id | 뜻 |
|---|---|
| `i-medic` | 감시자(medic, SP6 자동 복구) |
| `i-repair` | 자동 수리(GitHub Actions의 Claude) |
| `i-heartbeat` | 하트비트(살아 있음 신호) |
| `i-rollback` | 배포 롤백(이전 커밋으로) |
| `i-ci` | CI 자동 검사 |
| `i-incident` | 장애 이슈 |
| `i-wifi-off` | 연결 끊김·오프라인 스냅샷 |
| `i-review` | 검토 |
| `i-seed` | 시드 가져오기(seed-life) |
| `i-export` | 내보내기(md) |

## v2 표준 표기(C4·UML)

| id | 뜻 |
|---|---|
| `i-c4-person` | C4 사람(Person) |
| `i-c4-system` | C4 소프트웨어 시스템 |
| `i-c4-container` | C4 컨테이너(앱·프로세스·DB) |
| `i-c4-ext` | C4 외부 시스템(점선) |
| `i-uml-state` | UML 상태(둥근 사각형) |
| `i-uml-initial` | UML 시작 상태(찬 원) |
| `i-uml-final` | UML 끝 상태(테 두른 찬 원) |
| `i-seq-lifeline` | 시퀀스 생명선과 활성 막대 |
