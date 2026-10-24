# SP6 운영 앱 대화의 생성형 UI 넓히기 상세 설계

- 상태: 초안 v2 (Dahun 결정과 문서 리뷰 반영), Dahun 검토 대기
- 작성일: 2026-10-24
- 상위 문서: [마스터 설계](2026-10-23-my-planner-master-design.md), [SP3-4 스펙](2026-10-24-sp3-4-life-curve-dashboard-design.md) (BE HTTP API 계약의 **정본**, 이 문서는 6.4.1, 6.4.7, 10장을 넓힌다), [SP5 운영 앱 스펙](2026-10-24-sp5-ops-app-design.md) (화면, 6장 생성형 UI 규칙, 7장 부품 목록, 9장 성능)
- 용어: [`GLOSSARY.md`](../../../GLOSSARY.md) (이번에 "기본 부품", "완성 카드", "조립 카드" 셋을 더한다, 14장 BE-1), 결정 기록: [`docs/adr/`](../../adr/) (새 ADR 없음. ADR 0005 "두뇌는 planner 도구만"의 범위 안이다. 습관 기록 SP7이 0010을 쓰므로, 나중에 SP6에 ADR이 필요해지면 0011이다)
- 범위: 운영 앱 **대화 시트** 안의 화면 조각을 넓힌다. 조각을 고르는 두뇌 규칙, 조각의 모양(카탈로그), BE가 붙이는 지금 값, 앱 컴포넌트까지. 오늘 화면의 고정 카드와 체크인 카드는 바꾸지 않는다(2장).
- 구현: BE(카탈로그 `tools/ui.py`, 두뇌 도구, 프롬프트, 하네스의 조각 내보내기, 카탈로그 판, 기준 SSE)는 **SP3-4 BE 스레드**가 PR로, 앱 컴포넌트(`web/app/`)는 **운영 앱 스레드**가 PR로 만든다(14장).

## 1. 목표와 완료 조건

지금 대화의 화면 조각은 할 일 목록, 고르기, 요약 카드 셋뿐이라 비서가 바꾼 결과, 날짜 제안, 기간 보기, 숫자를 글로만 말한다. 이 하위 프로젝트는 **미리 만든 부품 조각을 비서가 골라 화면에 내놓게** 한다(Dahun의 원칙: "UI는 조각으로 미리 만들어 두고, 어떤 UI를 화면에 낼지는 AI가 정한다. AI가 코드를 쓰지 않는다").

세 층이다.

| 층 | 무엇 | 누가 고르나 |
|---|---|---|
| 기본 부품 (`ui_element`) | 제목, 짧은 글, 숫자, 진행 막대, 할 일 줄, 태그, 글머리 목록, 버튼 줄, 구분선, 묶음. 10개(5장) | 조립 카드 안에서 두뇌가 |
| 완성 카드 | 자주 쓰는 경우를 기본 부품으로 미리 짜 둔 카드. 기존 `ui_todo_list`, `ui_todo_draft`, `ui_choice`, `ui_summary_card` + 새 `ui_date_choice`, `ui_result`, `ui_period_list` (6장) | 두뇌가 이름으로 |
| 조립 카드 `ui_block` | 기본 부품을 12개까지 세로로 쌓은 카드. 묶음 한 단계까지 (7장) | 두뇌가 부품을 하나씩 |

**완료 조건 (수용 기준)**

1. 앱 대화에서 "다음 주에 치과 예약 추가해 줘"처럼 날짜가 분명하지 않은 할 일을 말하면, 비서가 할 일을 날짜 없이 추가하고 날짜 후보 2~4개가 담긴 `ui_date_choice`를 낸다. 후보 하나를 누르면 `POST /actions move_task`로 그 날짜가 잡히고 알림 줄에 확인 문구와 "되돌리기"가 보인다. 카드 안에서 제목이나 다른 필드를 고치는 칸은 없다. 이 답에는 `ui_result`가 나오지 않고, `add_task`의 회색 확인 칸(되돌리기 포함)이 그대로 보인다.
2. 비서가 대화 중 할 일 1~2개를 바꾸면 그 답에 `ui_result`가 나오고, 줄마다 바뀌기 전과 뒤(예: "10월 25일 (일) → 10월 27일 (화)")와 되돌릴 수 있으면 "되돌리기"가 보인다. 줄마다 할 일 하나에 활동 하나일 때 "되돌리기"가 있고, 카드가 그 답의 활동을 모두 그렇게 덮으면 같은 답의 회색 확인 칸(`data-activity`)은 보이지 않는다(그 밖은 확인 칸이 남아 되돌리기를 맡는다, 6.3, 11.4). 3개 이상을 바꾸면 `ui_period_list`가 나오고 바뀐 줄이 `--hue` 막대로 표시된다.
3. "이번 주 운동 몇 번 했지?"처럼 숫자나 진행을 물으면 비서가 `ui_block`(숫자·진행 막대 부품)으로 답하고, 답 글은 카드를 다시 읽어 주지 않는 한두 문장이다.
4. 조각의 모든 버튼은 8장 표의 다섯 가지(체크·완료, 확정, 되돌리기, 이어 말하기, 앱 화면 열기)만 한다. 빼기, 우선순위, 시각 바꾸기 버튼은 어떤 조각에도 없다. 할 일을 가리키는 값은 id뿐이고 제목과 상태는 BE가 붙인 지금 값으로만 그린다.
5. BE는 카탈로그 스키마와 7.3의 쌓기 규칙에 맞지 않는 조각을 도구 오류로 돌려주고 스트림에 보내지 않는다. 앱은 같은 공유 고정 자료(`tests/fixtures/ui_props/`)로 같은 판정을 한다(13장 양쪽 스키마 테스트).
6. 새 이름을 모르는 옛 앱은 그 조각을 기존 `UnknownPart`로 보이고 멈추지 않는다. 기존 카드 넷의 props는 바뀌지 않는다.
7. 다시 연 대화의 조각(`restored`)은 읽기 전용이다: 체크, 확정, 되돌리기, 이어 말하기가 꺼지고, 앱 화면 열기만 된다(6.5).
8. 첫 화면 자바스크립트가 180KB(gzip) 이하로 남고(`npm run size`), `npm run build && npm run check:csp`가 통과하고, CSP 아래 Playwright 시험에서 새 카드가 모두 그려지고 위반이 0건이다. 밝게·어둡게와 색 프리셋 6개에서 스크린샷을 남긴다(13장).
9. 새 고정 문구(부록 A)에 금지어가 없고(`lint-copy`), 조각 props의 글에도 금지어가 있으면 BE가 거절한다(10.3).

## 2. 범위

| 포함 | 제외 (언제) |
|---|---|
| 기본 부품 10개 (앱 컴포넌트) | 대화 편의: 멈춤, 복사, 다시 답하기, 대화 목록 (다음 단계) |
| 완성 카드 3개 추가(`ui_date_choice`, `ui_result`, `ui_period_list`)와 기존 4개를 기본 부품으로 다시 짜기 | 습관 기록 (별도 스레드) |
| 조립 카드 `ui_block` | 음성, 사진 입력 (다음 단계) |
| 두뇌 도구 4개, `channel_app.md` 규칙, 도구 설명 | 새 조각을 고정 카드로 올리기 (`pin_card`는 지금처럼 `ui_todo_list`, `ui_choice`, `ui_summary_card`만, 11.6) |
| 하네스가 붙이는 지금 값(`data`), 쌓기 규칙 검증, 카탈로그 판 올리기, 기준 SSE | 오늘 화면, 체크인 화면의 바뀜 (새 조각은 대화에만 나온다) |
| 앱 레지스트리, 컴포넌트, CSS, 크기 예산, 시험 | 텔레그램 (`ui_*`는 지금처럼 가지 않는다) |
| | 카드 안에서 제목·필드 고치기 (하지 않음, Dahun 결정) |
| | AI가 쓴 화면 코드, HTML, 링크 주소 (하지 않음, 12장) |

**관련, 다른 곳에서 정함**

| 무엇 | 어디서 | 이 문서와 닿는 곳 |
|---|---|---|
| 색 프리셋 6개 × 밝게·어둡게 (`:root[data-palette]` + `data-theme`) | 운영 앱 스레드의 별도 티켓 | 부품은 토큰만 쓴다(5.1). 스크린샷 행렬(13장) |
| `ui_habit_check {date}` (두뇌·하네스 완성 카드: 습관 체크 줄, 원 + 제목 + "이번 주 n번 · 목표 m번", 누르면 `/actions check_habit`·`uncheck_habit`, BE가 `data.habits`를 붙임) | 습관 기록 스레드의 스펙 | 할 일 줄 부품의 체크 줄 모양(`CheckRow`, 5.3.5)을 그대로 다시 쓴다. 카탈로그 판 규칙(10.5)을 따른다. 이 문서는 정하지 않는다 |

## 3. Dahun 결정 (2026-10-24)

| # | 질문 | 결정 |
|---|---|---|
| G1 | 생성형 UI의 원칙 | UI는 조각으로 미리 만들어 두고, 어떤 UI를 화면에 낼지는 AI가 정한다. AI가 코드를 쓰지 않는다 |
| G2 | 접근 | 섞는다: (a) 기본 부품 약 10개, (b) 같은 부품으로 짠 완성 카드, (c) 부품을 쌓는 조립 카드 `ui_block`(12개까지, 묶음 한 단계, 스키마로 검증) |
| G3 | 날짜가 분명하지 않은 할 일 추가 | 비서가 날짜를 제안하고 Dahun은 고르기만 한다(고르기 모양 카드). 카드 안에서 제목·필드를 고치지 않는다 |
| G4 | 비서가 할 일을 바꾼 뒤 | 1~2개 → `ui_result`, 3개 이상 → `ui_period_list`, 숫자·진행 → `ui_block`. 카드가 보여 주는 것을 글로 되풀이하지 않는다 |
| G5 | 버튼이 할 수 있는 일 | 체크·완료, 확정, 되돌리기, 이어 말하기, 앱 화면 열기만. 빼기, 우선순위, 날짜·시각 다시 잡기 같은 무거운 일은 기존 확인 흐름(`needs_confirm`, `ui_confirm`). 할 일은 id로만 가리키고 BE가 지금 값으로 바꾼다(`ui_todo_refs`처럼). 쓰기에 자유 입력을 믿지 않는다 |
| G6 | 맡는 곳 | BE는 SP3-4 BE 스레드가 PR로, 앱 컴포넌트는 `web/app`. 옛 앱은 안전하게 물러선다(모르는 조각 → `UnknownPart`) |
| G7 | 제외 | 대화 편의(멈춤, 복사, 다시 답하기, 대화 목록), 습관 기록, 음성·사진 입력 |

**성공의 모습**: 2주 동안 앱 대화에서 할 일을 바꿀 때 Dahun이 비서의 글을 다 읽지 않고 카드만 보고 맞는지 안다. 날짜를 직접 써 넣는 일이 줄어든다.

## 4. 구조

### 4.1 전체 그림

```
두뇌 (앱 대화)                       하네스 (BE)                                   운영 앱 (대화 시트)
mcp__planner__ui_result {task_ids} ─▶ call_tool                                   
                                      1. 카탈로그 스키마 + 쌓기 규칙 (tools/ui.py)
                                      2. 뜻 검사: 이번 답에서 바뀐 할 일인가 (core.py)
                                      3. 한 답 두 개 상한 (10.4)
                                      ── 맞지 않으면 도구 오류, 조각 없음 ──▶ 두뇌가 고쳐 다시 부름
                                      4. 지금 값 붙이기 (_stream_output, 10.2)
                                      tool-input-available {input = props} ─────▶ parts.ts → UiPart
                                      tool-output-available {ok, data} ─────────▶  레지스트리 이름 확인
                                                                                   카탈로그 스키마 + checkBlock
                                                                                   → 컴포넌트 (기본 부품으로 그림)
                                                                                   → 모르면 UnknownPart
                                      버튼 ◀──── POST /actions · /activity/{id}/undo · /chat ── 8장의 다섯 가지만
```

- 조각의 모양은 지금처럼 `tool-input-available.input`(props)과 `tool-output-available.output.data`(BE가 붙인 지금 값)다(SP3-4 6.4.1). 새 조각도 같은 길이라 SSE 형식, `parts.ts`의 읽기, `localParts` 저장은 바뀌지 않는다.
- 두뇌가 받는 도구 결과는 지금처럼 `{"ok": true}`다. `data`는 스트림에만 붙는다(두뇌가 지금 값을 다시 읽느라 토큰을 쓰지 않게).

### 4.2 접근안과 선택

| 안 | 내용 | 판단 |
|---|---|---|
| A. 기본 부품만 | 두뇌가 모든 화면을 부품으로 조립 | 버림. 결과·기간처럼 자주 쓰는 화면을 매번 다르게 짜서 모양이 흔들리고, 되돌리기 id·지금 값처럼 BE만 아는 것을 부품 props로 담을 수 없다 |
| B. 완성 카드만 | 경우마다 카드 하나 | 버림. 숫자·진행처럼 모양이 열린 경우마다 카드를 새로 만들어야 한다 |
| **C. 섞기 (G2)** | 자주 쓰는 경우는 완성 카드, 나머지는 `ui_block` | **선택**. 완성 카드와 조립 카드가 같은 부품으로 그려져 모양이 같다 |

### 4.3 맡는 곳

| 일 | 맡는 곳 | 파일 |
|---|---|---|
| props 모양(Pydantic → JSON Schema), 쌓기 규칙, 금지어·글자 검사, 판 | BE | `src/my_planner/tools/ui.py` |
| 두뇌 도구 4개와 뜻 검사(읽기만) | BE | `src/my_planner/tools/core.py` |
| 도구 설명, 앱 대화에만 주기, 지금 값 붙이기, 한 답 상한 | BE | `src/my_planner/tools/mcp_adapter.py` |
| 기간 보기 순수 함수, `TodoRef`에 필드 둘 | BE | `src/my_planner/store/views.py` |
| 두뇌 규칙 | BE | `src/my_planner/harness/prompts/channel_app.md` |
| 공유 고정 자료, 기준 SSE | BE가 만들고 앱이 제자리에서 읽는다 | `tests/fixtures/ui_props/`, `tests/fixtures/app_golden/` |
| 기본 부품, 완성 카드, 조립 카드, 레지스트리, CSS, 문구 | 앱 | `web/app/src/ui/`, `web/app/src/lib/copy.ts`, `web/app/src/pages/_app.tsx` |

## 5. 기본 부품 (10개)

### 5.1 공통 규칙

- **색**: 의미 토큰(`--surface`, `--text`, `--text-2`, `--muted`, `--raised`, `--rule`, `--border`, `--primary`, `--on-primary`, `--hue`)만 쓴다. 16진수 색, 영역별 색, 프리셋 이름에 기대는 규칙을 두지 않는다. 그래서 색 프리셋 6개 × 밝게·어둡게(`:root[data-palette]` + `data-theme`)에서 고칠 것 없이 바뀐다. SP6은 새 토큰을 만들지 않는다. 꼭 필요해지면 색 프리셋 티켓이 12벌 모두에 함께 더한다.
- **`--hue`는 비서가 한 일에만**(SP5 5.1): `ui_period_list`의 바뀐 줄 표시와 `ui_result`의 바뀜 표시에만 쓴다. 숫자, 진행 막대, 버튼에는 쓰지 않는다.
- **크기**: SP5 5.2의 다섯 단계(30 / 16 / 15 / 13 / 11)와 굵기 400·600만 쓴다(700은 화면 제목 전용). 숫자는 `tabular-nums`.
- **글**: props의 글은 모두 React 글 마디로 넣는다(`dangerouslySetInnerHTML` 없음). 글자 수 상한은 유니코드 코드 포인트로 센다(Pydantic `max_length`와 JSON Schema `maxLength`가 같은 방법으로 센다). 앱은 상한을 다시 재지 않고 스키마 검사만 믿는다.
- **줄바꿈**: `text.md`만 `\n`을 받는다(4개까지). 다른 글에 제어 문자가 있으면 BE가 거절한다(10.3).
- **움직임**: 없다. 체크 표시만 SP5 규칙(낙관적 반영)대로 바로 바뀐다.
- **CSP**: 인라인 `style` 속성을 쓰지 않는다. 진행 막대는 `<progress>` 요소로 그려 폭을 계산해 넣을 일이 없다.

### 5.2 한눈에

| # | `type` | props | 그림 | 상한 |
|---|---|---|---|---|
| 1 | `heading` | `text` | 15/600 `--text`, `<h4>` | 1~40자 |
| 2 | `text` | `md` | 16/400 `--text`, 줄 간격 1.45, `**굵게**`만 | 1~280자, `\n` 4개 |
| 3 | `stat` | `label`, `value`, `delta?{text, trend}` | 이름 13 `--muted`, 값 30/600, 변화 13 `--text-2` | 이름 1~16자, 값 1~10자, 변화 1~8자 |
| 4 | `progress` | `label`, `value`, `max` | 이름 + 오른쪽 "n/m", 6px 막대 | `max` 1~100, `0 ≤ value ≤ max` 정수 |
| 5 | `todo_rows` | `task_ids`, `checkable?` | 체크 줄(`CheckRow`) | 1~10개, 서로 다름 |
| 6 | `tags` | `items[{text} \| {area}]` | 24px 알약, `--raised` 위 `--text-2` 13 | 1~6개, 글 1~12자 |
| 7 | `bullets` | `items[]` | 점 목록 15 `--text` | 1~6줄, 줄마다 1~80자 |
| 8 | `buttons` | `items[{label, do}]` | 44px 알약 버튼 가로 줄(넘치면 다음 줄) | 1~3개, 이름 1~16자 |
| 9 | `divider` | 없음 | 1px `--rule` | |
| 10 | `group` | `layout`, `children` | `row`: 같은 폭 칸, `stack`: 안쪽 묶음 | 7.2 |

모든 부품은 `{"type": "<이름>", …}` 모양이고 정한 키 밖의 키가 있으면 거절한다(`extra="forbid"`).

### 5.3 부품별

#### 5.3.1 `heading`

```json
{"type": "heading", "text": "이번 주 운동"}
```

- 카드 제목(`<h3>`, `Part`의 `title`) 아래 단계라 `<h4>`다. 위 여백 12px, 아래 4px. 첫 부품이면 위 여백 없음.
- 접근성: 제목 요소라 화면 낭독기의 제목 이동으로 찾을 수 있다.

#### 5.3.2 `text`

```json
{"type": "text", "md": "이번 주는 **화요일**이 가장 비어 있어요.\n수요일은 일정이 둘이에요."}
```

- 마크다운은 **두 가지만** 읽는다: `**…**` → `<strong>`(600), `\n` → 줄바꿈(`<br>`). 짝이 맞지 않는 `**`, `#`, `[]()`, `<…>`, `` ` ``, `*`, `_`는 글자 그대로 보인다. 파서는 앱의 순수 함수 `parseMiniMd(md): MiniLine[]`이고 `MiniLine = {text, strong}[]`(줄 하나의 조각들)이다. `\n`으로 줄을 나누고 줄마다 정규식 `/\*\*([^*\n]+?)\*\*/g` 한 번으로 끝난다.
- 링크는 없다(12장). 주소처럼 보이는 글도 그냥 글이다.

#### 5.3.3 `stat`

```json
{"type": "stat", "label": "컨디션 평균", "value": "3.6", "delta": {"text": "0.4", "trend": "up"}}
```

- `value`는 글이다(두뇌가 "3회", "7.5시간"처럼 단위를 붙인다). 숫자 계산은 앱이 하지 않는다.
- `trend`: `up` | `down` | `same`. 변화 글 앞에 `↑` `↓` `→` 글자를 붙인다. **색은 늘 `--text-2`**다. 내려감을 빨강으로, 올라감을 초록으로 칠하지 않는다(P4 벌 대신 신호).
- 접근성: 한 부품을 `role="group"` + `aria-label="{label} {value}, {변화 낭독}"`으로 읽는다. 변화 낭독은 부록 A(`지난번보다 올라감 {text}` 등).
- 두뇌 규칙(9.2): 값은 이번 차례의 도구 결과나 Dahun이 말한 숫자만.

#### 5.3.4 `progress`

```json
{"type": "progress", "label": "운동", "value": 3, "max": 5}
```

- 이름(15 `--text`) 왼쪽, "3/5"(13 `--text-2`, `tabular-nums`) 오른쪽, 아래 `<progress value max>` 6px. 막대 바탕 `--raised`, 채움 `--primary`. 비율(%)은 보이지 않는다(SP5 금지어 "달성률", P4).
- `value > max`는 BE가 거절한다(넘친 막대를 그리지 않는다).
- 접근성: `<progress>`에 `aria-label="{label} {value}/{max}"`. 막대와 글이 같은 뜻이라 색만으로 뜻을 전하지 않는다.
- 두뇌 규칙(9.2): Dahun이 스스로 정한 수(이번 주 목표 횟수 등)나 Dahun이 물은 진행에만 쓴다. 지나간 일, 하지 않은 일의 수로 쓰지 않는다.

#### 5.3.5 `todo_rows`와 체크 줄 `CheckRow`

```json
{"type": "todo_rows", "task_ids": [53, 54], "checkable": true}
```

- 줄 내용은 BE가 붙인 `data.todos`(`TodoRef`, 10.2)에서만 읽는다. props에는 id뿐이다.
- `checkable`의 기본값은 `true`다(지금 `ui_todo_list`처럼 체크할 수 있음).
- 한 줄 = `CheckRow`: 왼쪽 44px 체크 원, 제목(16 `--text`), 오른쪽 보조 글(13 `--muted`). 보조 글은 `scheduled_at`이 있으면 `HH:MM`, 없고 `planned_for`가 `data.today`와 다르면 `{M}월 {D}일 ({요일})`, 둘 다 아니면 없음.
- `status`: `open` → 체크할 수 있음(`checkable`이 `false`면 원 대신 점). `done` → 회색 취소선, 원은 채움, 꺼짐. `dropped` → 회색 취소선, 원 없음, 보조 글 "뺌". `draft` → 나오지 않는다(`drafts=False`, 10.2).
- 누르면 `/actions complete_task {id}`(8장). 다시 열기는 없다(지금 `ui_todo_list`와 같다).
- `data`가 없으면(옛 BE) "할 일 {n}개" 한 줄. `data.todos`가 비면(모두 소프트 삭제) "보여 줄 할 일이 없어요".
- **다시 쓰기**: `CheckRow`는 `ui/primitives/CheckRow.tsx`에서 내보내는 하나의 컴포넌트다. 받는 값은 `{title, meta?, checked, disabled, struck?, highlight?, mark?, onToggle}`이고 할 일을 모른다. `mark`는 `"circle"`(기본, 44px 체크 원) | `"dot"`(`checkable=false`의 점) | `"none"`(`dropped`, 원 없음)이다. 습관 줄은 기본값만 쓴다. `ui_todo_list`, `ui_todo_draft`, `todo_rows`, `ui_period_list`가 이것을 쓰고, 습관 기록 스레드의 `ui_habit_check` 줄도 `meta`("이번 주 n번 · 목표 m번")만 바꿔 같은 것을 쓴다.
- 접근성: 체크 원은 `role="checkbox"`, `aria-checked`, `aria-label="{제목} 체크"`(기존 `copy.parts.checkLabel`). `highlight`이면 줄 끝에 눈에 안 보이는 글 "비서가 바꿈".

#### 5.3.6 `tags`

```json
{"type": "tags", "items": [{"area": "health"}, {"text": "오전"}]}
```

- `area`는 용어집 6개 영역 영어 이름(`career`, `finance`, `health`, `relationships`, `learning`, `quality_of_life`)이고 앱이 한국어 이름(커리어, 경제, 건강, 관계, 배움, 삶의 질, 기존 `copy` 영역 이름)으로 보인다. 영역마다 색을 다르게 하지 않는다.
- 누를 수 없다(`<span>`). 목록은 `<ul aria-label="태그">`.

#### 5.3.7 `bullets`

```json
{"type": "bullets", "items": ["화요일 오후가 비어 있어요", "목요일은 일정이 셋이에요"]}
```

- `<ul>`, 줄 앞 4px 점(`--muted`), 줄 사이 6px. 마크다운은 읽지 않는다.

#### 5.3.8 `buttons`

```json
{"type": "buttons", "items": [
  {"label": "이번 주 할 일 보기", "do": {"kind": "open", "screen": "todos_week"}},
  {"label": "다음 주도 알려 줘", "do": {"kind": "send"}}]}
```

- `do`는 8장의 버튼 동작 셋 가운데 하나다: `send`(이어 말하기), `open`(앱 화면 열기), `complete`(할 일 완료). 되돌리기와 확정은 완성 카드에만 있다(8장).
- 44px 알약(`--radius-pill`), 테두리 `--border`, 글 15/600 `--text`. 채운 버튼은 없다: 모든 버튼이 같은 무게다(비서가 Dahun의 선택을 한쪽으로 기울이지 않게).
- 한 번 누른 `send`·`complete` 버튼은 꺼지고 누른 것만 `aria-pressed="true"`로 진하게 남는다(`ui_choice`와 같다). `open`은 몇 번이든 된다.

#### 5.3.9 `divider`

```json
{"type": "divider"}
```

- `<hr>` 1px `--rule`, 위아래 8px. 낭독기는 건너뛴다(`aria-hidden`).

#### 5.3.10 `group`

```json
{"type": "group", "layout": "row", "children": [
  {"type": "stat", "label": "완료", "value": "4개"},
  {"type": "stat", "label": "남은 것", "value": "3개"}]}
```

- `row`: 아이들을 같은 폭 칸으로 나란히(CSS grid `repeat(n, 1fr)`, 칸 사이 12px). 카드 안쪽 폭이 300px 아래면 한 줄에 하나씩(컨테이너 쿼리 없이 `@media (max-width: 340px)`). `stat`, `progress`만 2~3개.
- `stack`: 아이들을 세로로, 위쪽 1px `--rule`과 12px 여백으로 한 덩어리임을 보인다. `group`, `buttons`를 뺀 부품 2~6개.
- 묶음 안에 묶음은 없다(한 단계, G2).

## 6. 완성 카드

### 6.1 기존 넷 (props 그대로)

| 이름 | 다시 짜는 모양 (기본 부품) | 바뀌는 것 |
|---|---|---|
| `ui_todo_list` | 카드 제목 + `CheckRow` 줄 (6줄 넘으면 "n개 더") | 없음. 컴포넌트 안쪽만 `CheckRow`로 |
| `ui_todo_draft` | 테두리 카드 "할 일 초안" + 안내 + `CheckRow` + 버튼 줄 | 없음 |
| `ui_choice` | `text` 부품과 같은 글 모양의 질문(`<p>`, 마크다운을 읽지 않아 `**`도 글자 그대로) + 버튼 줄(`send`와 같은 동작) | 없음 |
| `ui_summary_card` | 카드 제목 + `bullets` 모양 줄 | 없음 |

- 카탈로그 스키마, BE 도구, 하네스는 그대로다. 앱 컴포넌트가 같은 부품 컴포넌트로 그려 모양을 맞춘다. SP5 13장 부품 시험이 그대로 통과해야 한다(보이는 글, 누름의 `/actions` 본문이 같다). 화면 차이는 스크린샷으로 확인한다(13장).
- 눈에 보이는 차이는 하나다: `ui_choice`의 알약이 36px에서 버튼 줄 부품의 44px이 된다(SP5 9장 터치 영역 44px에 맞춘다). SP5 7장 표의 "36px"를 같은 PR(A-1)에서 고친다.

### 6.2 `ui_date_choice` (날짜 고르기)

**언제**: Dahun이 할 일을 말했는데 날짜가 분명하지 않을 때, 또는 시각이 없는 열린 할 일(날짜는 있어도 없어도 된다)의 날짜를 정하자고 할 때(9.1).

**흐름**: 두뇌가 먼저 `add_task`(`planned_for` 없이)로 할 일을 만든다(사용자가 말한 할 일이라 SP3-4 10.1 A4대로 바로 적용) → `ui_date_choice {task_id, question, candidates}`를 부른다 → Dahun이 후보 하나를 누르면 앱이 `/actions move_task {id, planned_for}`를 보낸다. 두뇌는 다시 불리지 않는다(하루 두뇌 호출 상한을 쓰지 않는다).

```json
{"task_id": 53, "question": "치과 예약은 언제 할까요?",
 "candidates": [{"date": "2026-10-27", "note": "오후가 비어요"}, {"date": "2026-10-28"}, {"date": "2026-10-30"}]}
```

| props | 규칙 |
|---|---|
| `task_id` | 정수. BE 뜻 검사: 있음, 소프트 삭제 아님, `status = open`, `scheduled_at = null`. `planned_for`는 있어도 없어도 된다 |
| `question` | 1~60자 |
| `candidates` | 2~4개. `date`는 `YYYY-MM-DD`, 서로 다름, 오늘(논리적 날짜) 이상, 오늘 + 90일 이하. `note?`는 1~12자 |

- **시각이 잡힌 할 일은 받지 않는다**: 날짜를 옮기면 `scheduled_at`도 바뀌어(SP1 5.5) 시각 다시 잡기가 되고, 그것은 무거운 일이다(G5). 도구 오류 "시각이 잡힌 할 일은 날짜 고르기로 옮기지 않아요. 대화로 정해 주세요."
- **BE가 붙이는 값**: `{"ok": true, "data": {"today": "2026-10-24", "todo": TodoRef}}`(10.2).
- **그림**: 카드 제목 없이 `text`(질문) → 할 일 제목 한 줄(15 `--text-2`) → 후보마다 가로 꽉 찬 44px 버튼 "10월 27일 (화)"(오늘·내일이면 "오늘 · 10월 24일 (토)", "내일 · 10월 25일 (일)") + 오른쪽 `note`(13 `--muted`) → 맨 아래 테두리만 있는 버튼 "다른 날로 할게요".
- **누르면**: 후보 → `move_task`(8장 `confirm` 동작). 기다리는 동안 모든 버튼이 꺼진다. 그 사이 할 일에 시각이 잡혀 `needs_confirm`이 오면(8장) 할 일 화면과 같은 확인 시트(`ConfirmSheet`)를 띄운다. `applied`면 누른 후보만 `aria-pressed="true"`로 진하게 남고 나머지는 꺼진다. 확인 문구와 "되돌리기"는 기존 알림 줄(SP5 F8)이 보인다. `rejected`·`failed`면 알림 줄에 이유가 나오고 버튼이 다시 켜진다. "다른 날로 할게요" → 그 글을 새 사용자 메시지로 `/chat`(8장 `send`).
- **이미 정리됨**: `data.todo.status`가 `open`이 아니거나 `data.todo`가 없으면(지워짐) 후보 버튼을 그리지 않고 "이미 정리된 할 일이에요" 한 줄.

### 6.3 `ui_result` (방금 바꾼 것)

**언제**: 이 답에서 비서가 할 일 1~2개를 바꿨을 때(G4). 바꾼 도구를 부른 **뒤** 같은 답에서 부른다.

```json
{"task_ids": [53]}
```

| props | 규칙 |
|---|---|
| `task_ids` | 정수 1~2개, 서로 다름. BE 뜻 검사: 이번 답(같은 `RunContext`)의 활동 가운데 대상이 `task:<id>`인 것이 있어야 한다. 없으면 도구 오류 "이번 답에서 바꾼 할 일만 보여 줄 수 있어요." |

**BE가 붙이는 값** (10.2):

```json
{"ok": true, "data": {"today": "2026-10-24", "items": [
  {"todo": {"id": 53, "title": "치과 예약", "cadence": null, "area": "health", "status": "open",
            "planned_for": "2026-10-27", "scheduled_at": null},
   "change": "moved",
   "before": {"status": "open", "planned_for": "2026-10-25", "scheduled_at": null, "title": null},
   "after":  {"status": "open", "planned_for": "2026-10-27", "scheduled_at": null, "title": null},
   "activity_ids": [931], "undo_id": 931}]}}
```

- `change`는 그 할 일의 이번 답 활동에서 정한다: 활동 가운데 `task_added`가 있으면 `added`(`before = null`). 아니면 가장 늦은 활동의 종류: `task_moved` → `moved`, `task_completed` → `completed`, `task_reopened` → `reopened`, `task_dropped` → `dropped`, `task_updated` → `updated`, `tasks_confirmed` → `confirmed`.
- `before`: 이번 답에서 그 할 일의 **가장 이른** 활동(바뀌기 전 상태)의 `undo_json`에서 아래 표대로 꺼낸다. 표에 없는 필드는 `null`이다. `after`: 지금 값(`status`, `planned_for`, `scheduled_at`, `title`). 시각은 UTC(SP3-4 6.1).

| 가장 이른 활동 | `undo_json` 모양 (`tools/core.py`) | `before` |
|---|---|---|
| `task_added` | `{task_id}` | `null` (`change = added`) |
| `task_moved` | `{task_id, planned_for, scheduled_at}` | `planned_for`, `scheduled_at` (`status`는 `null`) |
| `task_completed`, `task_reopened`, `task_dropped` | `_before(t)` = `{task_id, status, completed_at, planned_for, scheduled_at}`(빼기는 `priorities`도) | `status`, `planned_for`, `scheduled_at` |
| `task_updated` | `{task_id, before: {바뀐 필드만}}` | `before` 안의 `title`, `planned_for`, `scheduled_at` 가운데 있는 것 |
| `tasks_confirmed` | `{task_ids}` | `{"status": "draft"}` |

- `activity_ids`: 이번 답에서 그 할 일을 대상으로 한 활동 id 전부(오래된 것부터).
- `undo_id`: **그 할 일의 이번 답 활동이 정확히 하나이고, 그 활동의 대상(`activity_targets`)이 그 할 일 하나뿐일 때만** 그 활동 id(지금 되돌릴 수 있을 때, U1~U3, SP3-4 6.4.3). 그 밖은 `null`이다. 활동이 여럿이면(예: 옮긴 뒤 다시 옮김) 마지막 것만 되돌려 "A → C"를 보여 주고 B로 돌아가는 일이 생기고, 여러 할 일을 함께 바꾼 활동(`tasks_confirmed`)은 한 줄의 되돌리기가 다른 할 일까지 되돌린다. 이런 경우의 되돌리기는 확인 칸(11.4에서 숨기지 않는다)과 기록 화면이 맡는다.
- 할 일이 그 사이 소프트 삭제됐으면(예: 같은 답에서 추가를 되돌림) 그 항목은 빠진다. 항목이 하나도 없으면 도구 오류 "보여 줄 바뀐 할 일이 없어요."

**그림**: 카드 제목 없이, 항목마다 한 덩어리.

| `change` | 첫 줄 | 둘째 줄 (13 `--text-2`) |
|---|---|---|
| `added` | 알약 "추가" + 제목 | 날짜(`{M}월 {D}일 ({요일})`, 시각이 있으면 뒤에 `HH:MM`), 없으면 "날짜 없음" |
| `moved` | 알약 "옮김" + 제목 | "{이전} → {지금}" (이전은 `--muted`) |
| `completed` | 알약 "완료" + 제목(취소선) | 없음 |
| `reopened` | 알약 "다시 엶" + 제목 | 없음 |
| `dropped` | 알약 "뺌" + 제목(취소선) | 없음 |
| `updated` | 알약 "고침" + 제목 | 제목이 바뀌었으면 "이전 제목: {before.title}", 시각이 바뀌었으면 "{이전 시각} → {지금 시각}", 그 밖은 "내용을 고쳤어요" |
| `confirmed` | 알약 "확정" + 제목 | "초안을 확정했어요" |

- 알약은 1.5px `--hue` 테두리 + `--hue` 글자(13/600). 비서가 한 일이라는 표시다(SP5 5.1). 항목 사이 `divider`.
- 오른쪽: `undo_id`가 있으면 32px 회색 알약 "되돌리기"(8장 `undo`). 누르면 `POST /activity/{undo_id}/undo`(기존 `useUndo`). `undone`·`already_undone` → 그 자리가 "되돌렸어요", `409`/`422` → 기존 `copy.activity.undoBlocked` 이유 글. 확인 문구는 기존 알림 줄에 나온다.
- 접근성: 바뀜 줄은 `aria-label="이전 {이전}, 지금 {지금}"`(화살표를 읽히지 않는다).
- **확인 칸 숨김**: 같은 메시지의 `ui_result` 카드들이 그 메시지 `data-activity`의 활동을 모두 덮으면 회색 확인 칸을 그리지 않는다(정확한 규칙은 11.4). 같은 일을 두 번 보이지 않게(G4).

### 6.4 `ui_period_list` (하루·한 주 보기)

**언제**: 이 답에서 할 일 3개 이상을 바꿨을 때(G4), 또는 Dahun이 하루나 한 주의 할 일을 보자고 할 때.

```json
{"week": "2026-W44", "highlight_task_ids": [53, 54, 57]}
```

| props | 규칙 |
|---|---|
| `day` 또는 `week` | 꼭 하나만. `day`: `YYYY-MM-DD`, 오늘 − 14일 ~ 오늘 + 56일. `week`: ISO 주 `YYYY-Www`(`priorities.period` 형식), 이번 주 − 2주 ~ 이번 주 + 8주 |
| `highlight_task_ids?` | 정수 0~30개, 서로 다름. BE 뜻 검사(`ui_result`와 같다): 모두 이번 답 활동의 대상 `task:<id>` 가운데 있어야 한다. 아니면 도구 오류 "바뀐 줄 표시는 이번 답에서 바꾼 할 일만 할 수 있어요." 보기만 하는 요청에는 비우거나 뺀다 |

**BE가 붙이는 값** (10.2):

```json
{"ok": true, "data": {"today": "2026-10-24", "start": "2026-10-26", "end": "2026-11-01",
  "days": [{"date": "2026-10-26", "weekday": "월", "is_today": false, "todos": [TodoRef]}],
  "outside": [{"reason": "moved", "todo": TodoRef}]}}
```

- `days`: `day`이면 하루, `week`이면 월~일 7일. 하루의 할 일은 새 순수 함수 `period_view`(10.2)가 정하고 규칙은 하나다: **`planned_for`가 그날이고 `status`가 `open` 또는 `done`인 할 일**, 할 일마다 한 번. 오늘이어도 같다: 오늘 화면(`today_view`)과 달리 전에 잡은 열린 할 일을 끌어오지 않는다. 순서는 `open` 가운데 시각 있는 것(시각 순) → 시각 없는 `open` → `done`. 초안·소프트 삭제·`dropped`는 빠진다.
- `outside`: `highlight_task_ids` 가운데 `days`에 없는 것을 이유와 함께. `reason`: `dropped`(뺀 할 일) → `no_date`(`planned_for`가 없음) → `moved`(날짜가 기간 밖) 순으로 먼저 맞는 하나. 소프트 삭제한 것은 빠진다.

**그림**:

- 카드 제목(15/600): `day`가 오늘·내일·어제면 "오늘"·"내일"·"어제", 아니면 "10월 27일 (화)". `week`가 이번 주면 "이번 주", 다음 주면 "다음 주", 지난주면 "지난주", 아니면 "10월 26일 ~ 11월 1일". 모두 `data.today` 기준이다(기기 달력을 쓰지 않는다, SP5 F3).
- 주: 날짜 묶음마다 작은 머리 "{D}일 {요일}"(13/600 `--muted`, 오늘이면 뒤에 " · 오늘") + `CheckRow` 줄. 빈 날은 한 줄 "{요일} · 없음"(SP5 5.5.5와 같은 모양). 하루 묶음이 8줄을 넘으면 "n개 더"로 접는다.
- 바뀐 줄(`highlight_task_ids`에 있음): `CheckRow highlight` = 줄 왼쪽 3px `--hue` 막대 + 낭독용 "비서가 바꿈".
- `outside`가 있으면 맨 아래에 이유별 머리로 나눠 보인다: `moved` "기간 밖으로 옮긴 것"(줄마다 보조 글로 그 날짜), `dropped` "뺀 것"(취소선, 체크 없음), `no_date` "날짜 없는 것". 빈 묶음은 그리지 않는다.
- 맨 아래 버튼 줄: 기간이 오늘이면 "할 일 화면에서 보기"(`open todos_day`), 이번 주면 같은 글로 `open todos_week`, 그 밖의 기간에는 없음. `highlight_task_ids`가 있으면 "기록에서 보기"(`open activity`).
- 체크는 `complete_task`(8장). 되돌리기는 이 카드에 없다: 여러 개 바꾼 답의 되돌리기는 같은 메시지의 확인 칸(SP5 5.5.2)과 기록 화면이 맡는다. 그래서 `ui_period_list`만 있는 메시지는 확인 칸을 숨기지 않는다(11.4).

### 6.5 공통 상태

| 상태 | 판정 (`PartContext`) | `ui_date_choice` | `ui_result` | `ui_period_list` | `ui_block` |
|---|---|---|---|---|---|
| 정상 | | 6.2 | 6.3 | 6.4 | 7장 |
| 비서 오프라인, 쓰기 막힘 | `readOnly` | 후보·"다른 날" 꺼짐 + 이유 글(기존 `Part`의 `copy.offline.writeLater`) | "되돌리기" 꺼짐 + 이유 글 | 체크 꺼짐, 화면 열기 버튼은 된다 | `complete`·`send` 꺼짐, `open`은 된다 |
| 다시 연 대화 | `restored` | 후보 그대로 보이고 모두 꺼짐(이유 글 없음, 지금 `Choice`와 같다) | 바뀜 줄만, "되돌리기" 없음 | 줄만, 체크 꺼짐, 화면 열기는 된다 | `complete`·`send` 없음, `open`은 된다 |
| `data` 없음(옛 BE) | `data === undefined` | 질문 + "할 일 1개" | "바뀐 할 일 {n}개" 한 줄 | 카드 제목 + "할 일을 불러오지 못했어요" | `todo_rows`만 "할 일 {n}개" |
| 옛 앱(이름 모름) | 레지스트리에 없음 | `UnknownPart` + `question` | `UnknownPart`(글 없음. 같은 메시지의 확인 칸은 옛 앱이 숨기지 않으므로 보인다) | `UnknownPart` | `UnknownPart` + `title` |
| 스키마 틀림 | 카탈로그 검사 또는 `checkBlock` 실패 | `UnknownPart` | 같음 | 같음 | 같음 |

- **화면 열기는 읽기 전용에서도 된다**: 쓰기가 아니고 열리는 화면이 스스로 오프라인 상태를 보인다(SP5 5.5.4).
- **다시 연 대화에서 `send`를 막는 이유**: 지난 질문의 답이 지금 대화로 들어간다(지금 `Choice`와 같은 규칙).
- 다시 연 조각의 `data`는 받은 때의 값이다(`localParts`). 그래서 체크와 되돌리기를 막는다(SP5 4.6, `history.ts`의 `restored`).

## 7. 조립 카드 `ui_block`

### 7.1 모양

```json
{"title": "이번 주 운동",
 "children": [
   {"type": "group", "layout": "row", "children": [
     {"type": "stat", "label": "이번 주", "value": "3회", "delta": {"text": "1회", "trend": "up"}},
     {"type": "stat", "label": "지난주", "value": "2회"}]},
   {"type": "progress", "label": "이번 주 목표", "value": 3, "max": 4},
   {"type": "text", "md": "**목요일** 오후가 비어 있어요."},
   {"type": "todo_rows", "task_ids": [61]},
   {"type": "buttons", "items": [{"label": "운동 끝났어", "do": {"kind": "complete", "task_id": 61}}]}]}
```

| props | 규칙 |
|---|---|
| `title` | 1~40자, 꼭 있음(카드 제목, 옛 앱의 `UnknownPart` 글) |
| `children` | 1~12개, 기본 부품(5장) 또는 `group` |

카드 틀은 기존 `Part`(흰 그룹, 반지름 16, 제목 `<h3>`)이고, 아이들을 위에서 아래로 12px 간격으로 쌓는다.

### 7.2 쌓기 규칙

| # | 규칙 | 스키마로 | 검사 오류 `code` |
|---|---|---|---|
| B1 | 부품 수는 묶음 안까지 모두 세어 12개 이하(`group` 하나는 1 + 아이 수) | 아니오 | `block_too_many` |
| B2 | `group`은 맨 위 단계에만. 묶음 안에 묶음 없음 | 예 (`group.children`의 항목 종류에 `group` 없음) | `union_tag_invalid` |
| B3 | `group layout=row`는 `stat`·`progress`만 2~3개, `layout=stack`은 `group`·`buttons`를 뺀 부품 2~6개 | 예 (`layout`별 모델 둘 `RowGroup`, `StackGroup`을 `layout`으로 가르는 안쪽 구분 유니언, 10.1) | `layout` 값이 틀리면 `union_tag_invalid`, 없으면 `union_tag_not_found`(위치 `children.<n>.group`), 아이 수·종류가 틀리면 Pydantic 기본 코드(`too_short`, `too_long`, `union_tag_invalid`) |
| B4 | `buttons`는 한 카드에 하나, 맨 위 단계의 마지막 | 아니오 | `buttons_place` |
| B5 | `todo_rows`는 한 카드에 둘까지 | 아니오 | `todo_rows_too_many` |
| B6 | `divider`는 처음·끝에 오지 않고 둘이 붙지 않음(묶음 안에서도) | 아니오 | `divider_place` |
| B7 | 내용 부품(`text`, `stat`, `progress`, `todo_rows`, `tags`, `bullets`)이 하나 이상 | 아니오 | `block_no_content` |
| B8 | `complete` 버튼의 `task_id`는 같은 카드 `todo_rows`의 id 가운데 하나 | 아니오 | `complete_not_in_rows` |
| B9 | props JSON(UTF-8)은 8KB 이하 | 아니오 | `too_large` |

- **BE**: Pydantic 모델(`BlockProps`, 부품은 `type`으로 가르는 `Annotated[Union[…], Field(discriminator="type")]`)이 B2·B3과 5장의 길이·개수를 맡고, `model_validator(mode="after")`가 B1, B4~B8을, `validate_props`가 B9를 본다. 오류 문구는 지금 형식 그대로 `"{위치}: {code}"`(값을 담지 않는다)이고, 위 표의 새 `code`에는 두뇌가 고칠 수 있게 괄호로 한국어 한 마디를 붙인다(부록 B).
- **앱**: 카탈로그 JSON Schema(`@cfworker/json-schema`)가 B2·B3과 길이를, 순수 함수 `checkBlock(props): boolean`(`ui/block/checkBlock.ts`)이 B1, B4~B8을 본다. B9는 보지 않는다(BE가 보냈으면 이미 맞다). 어느 하나라도 실패하면 카드 전체가 `UnknownPart`다(부분만 그리지 않는다).
- 두 쪽의 판정은 공유 고정 자료로 맞춘다(13장): `tests/fixtures/ui_props/ui_block/ok/*.json`은 둘 다 통과, `bad/<code>-*.json`은 둘 다 실패(BE는 파일 이름의 `code`가 오류에 있어야 한다). 예외는 BE 전용 판정이다: B9 `too_large`, 10.3의 `bad_char`·`banned_word`·`slash`, 그리고 `model_json_schema()`에 나오지 않는 `period_one`(`ui_period_list`), `value_over_max`(`progress`), 후보 날짜의 `not_unique`(`ui_date_choice`). 앱 공유 시험은 이 `code`의 `bad`를 건너뛴다. 정수 목록(`task_ids`, `highlight_task_ids`, `todo_rows.task_ids`)의 서로 다름은 JSON Schema `uniqueItems`로도 나가므로 양쪽이 본다. BE가 거절한 조각은 스트림에 오지 않는다(10.1).

### 7.3 BE가 붙이는 값

`{"ok": true, "data": {"today": "2026-10-24", "todos": [TodoRef]}}`. `todos`는 카드 안 모든 `todo_rows`의 id를 나온 순서대로 모은 것(겹치면 한 번, 초안·소프트 삭제 뺌). 각 `todo_rows`는 자기 id 순서대로 그 목록에서 찾는다. `todo_rows`가 없으면 `data`는 `{"today": …}`만이다.

## 8. 버튼과 동작 (허용 목록)

조각의 버튼이 할 수 있는 일은 이 다섯뿐이다(G5). 앱은 `ActionName`의 다른 이름을 조각에서 부르지 않는다.

| 동작 | 부르는 것 | 어느 조각에서 | 대상 |
|---|---|---|---|
| 체크·완료 (`complete`) | `/actions complete_task {id}` | `ui_todo_list`, `ui_period_list`, `ui_block`의 `todo_rows`와 `complete` 버튼 | `data.todos`(`ui_period_list`는 `data.days[].todos`)에 있고 `status = open`인 id만. `ui_todo_draft`의 체크 표시는 완료가 아니라 "고르기"다(확정·빼기할 것을 고른다, 지금 그대로). `CheckRow`의 `onToggle`이 무엇을 하는지는 카드마다 정한다 |
| 확정 (`confirm`) | `ui_date_choice`: `/actions move_task {id, planned_for}` · `ui_todo_draft`: `confirm_tasks`, `drop_task`(초안 빼기, 지금 그대로) · `ui_confirm`: 지금 그대로 | 완성 카드에만 | `move_task`의 `id`는 `data.todo.id`, `planned_for`는 props `candidates[].date` 가운데 하나. 범위(오늘~90일)와 "시각 없는 열린 할 일"은 **그릴 때만** BE가 확인한다. 누를 때 `/actions move_task`가 보는 것은 할 일이 있는지, 날짜 형식, 그리고 BE-2가 더하는 확인 규칙(아래) 셋뿐이다 |
| 되돌리기 (`undo`) | `POST /activity/{undo_id}/undo` | `ui_result` | BE가 붙인 `data.items[].undo_id`만. 두뇌는 활동 id를 모르고 props에 넣을 수도 없다 |
| 이어 말하기 (`send`) | 버튼 이름 그대로를 새 사용자 메시지로 `/chat`(`ctx.onChoose`, 지금 `ui_choice`와 같다) | `ui_choice`, `ui_date_choice`의 "다른 날로 할게요", `ui_block`의 `send` 버튼 | 보내는 글 = 보이는 이름(1~16자, 따로 숨은 글이 없다). `/`로 시작하면 BE가 거절한다(명령이 되지 않게) |
| 앱 화면 열기 (`open`) | 앱 라우터로 이동 후 대화 시트 닫기 | `ui_period_list`, `ui_block`의 `open` 버튼 | `screen` 열거값만(아래) |

**`open`의 `screen` 값** (주소는 앱이 만든다. props에 주소가 없다)

| `screen` | 주소 (SP5 4.5) |
|---|---|
| `today` | `/` |
| `todos_day` | `/todos/?tab=day` |
| `todos_week` | `/todos/?tab=week` |
| `todos_month` | `/todos/?tab=month` |
| `activity` | `/activity/` |
| `settings` | `/settings/` |

- **무거운 일은 버튼이 아니다**: 빼기(`drop_task`, 초안 빼기 제외), 우선순위(`set_priorities`), 시각 바꾸기(`update_task`의 `scheduled_at`, 시각 있는 할 일의 `move_task`)는 어떤 버튼에도 없다. Dahun이 대화로 시키면 두뇌가 도구를 부르고(사용자 요청이 곧 승인, SP3-4 10.1 A3), 회차 차례에서는 지금처럼 `needs_confirm` → `ui_confirm`이다. 할 일 화면의 줄 밀기·확인 시트(SP5 5.5.5)도 그대로다.
- **앱 통로의 `move_task` 확인 (BE-2)**: 지금 `ACTIONS["move_task"]`(`tools/actions.py`)에는 `needs_confirm`이 없고, `Tools.move_task`의 확인은 회차 차례에서만 돈다(`_confirm_first`). 그래서 그릴 때와 누를 때 사이에 시각이 잡힌 할 일은 확인 없이 시각까지 옮겨진다(G5에 어긋난다). BE-2는 `move_task`에 `needs_confirm=move_needs_confirm`을 더한다: 할 일에 `scheduled_at`이 있고 `planned_for`가 바뀌면 확인 문구 한 줄(`confirm_move_summary`, 회차 차례와 같은 문구), 아니면 `None`. `drop_task`처럼 **앱 통로 요청에만** 적용된다(SP3-4 6.4.2). 이것은 SP5 5.5.5·F6의 "앱의 `move_task`는 늘 바로 적용된다"를 바꾼다: 할 일·오늘·체크인 화면의 "내일로"도 시각 있는 할 일이면 `drop_task`와 같은 확인 시트를 거친다. 그래서 SP3-4 6.4.2 표의 `move_task` 위험 칸("low. 시각이 있는 할 일의 날짜를 바꾸면 `confirm`")과 SP5 5.5.5·F6 문장을 BE-2·A-2 PR에서 함께 고친다. 텔레그램 버튼은 지금처럼 바로 적용된다.
- **같은 누름 두 번**: 기존 `useAction`·`useUndo`의 진행 중 표시를 그대로 쓴다(SP5 4.6).
- **누른 뒤**: 부품은 상태를 스스로 바꾸지 않고(누른 표시만), `ctx.onAfterAction()`을 부른다(SP5 6장).

## 9. 두뇌 규칙

### 9.1 무엇을 언제 그리나

| 경우 | 그리는 것 | 글 |
|---|---|---|
| Dahun이 말한 할 일에 날짜가 분명하지 않음 ("다음 주에", "언젠가", 날짜 없음) | `add_task`(`planned_for` 없이) 뒤 `ui_date_choice`. 후보는 `list_tasks`로 본 그 기간의 빈 날 2~4개. 이 답에는 `ui_result`를 그리지 않는다(확인 칸이 추가를 보이고 되돌리기를 맡는다) | "날짜를 골라 주세요" 정도 한 문장 |
| 시각이 없는 열린 할 일의 날짜를 정하자고 함 (날짜가 있어도 된다) | `ui_date_choice` | 한 문장 |
| 비서가 이 답에서 할 일 1~2개를 바꿈 | 바꾼 뒤 `ui_result` | 한 문장 이하. 바뀐 내용을 되풀이하지 않는다 |
| 이 답에서 할 일 3개 이상을 바꿈 | `ui_period_list`(바뀐 것이 가장 많이 든 하루나 주, `highlight_task_ids` = 바꾼 것) | 한 문장 이하 |
| 하루·한 주의 할 일을 보여 달라 | `ui_period_list` | 한 문장 이하 |
| 날짜로 묶이지 않는 할 일 모음("건강 할 일 뭐 있지") | `ui_todo_list` | 한 문장 이하 |
| 숫자, 진행, 비교 (컨디션 평균, 레벨, 이번 주 횟수) | `ui_block`(`stat`, `progress`, `group row`) | 한두 문장, 숫자를 다시 읽지 않는다 |
| 고를 것 2~4개 | `ui_choice` | 질문을 글로 되풀이하지 않는다 |
| 짧은 정리 몇 줄 | `ui_summary_card` | |
| 위에 없는 짧은 답, 감정, 쉬자는 말 | 그리지 않는다 | 글만 |

- 할 일을 바꾼 결과는 `ui_result`·`ui_period_list` 가운데 하나만 그리고, `ui_date_choice`를 그린 답에는 둘 다 그리지 않는다.
- 한 답에 두뇌가 그리는 조각은 **두 개까지**(BE가 셋째를 거절한다, 10.4). 하네스 조각(초안 카드 등)은 세지 않는다.
- 회차 차례(아침 브리핑 등)에는 그리지 않는다: 회차 답에는 스트림이 없어 그려지지 않는다(SP3-4 6.4.5, 회차 카드는 하네스가 만든다).
- 텔레그램 대화에는 이 도구들이 없다(SP3-4 6.4.7, 지금 그대로).

### 9.2 `channel_app.md`의 새 내용 (지금 글을 바꾼다)

지금 글의 "답 글에도 같은 뜻을 씁니다(화면 조각이 보이지 않아도 글만으로 알 수 있게)"는 G4("카드가 보여 주는 것을 글로 되풀이하지 않는다")와 맞지 않아 뺀다. 새 글 전체:

```markdown
## 운영 앱 대화
이 대화는 운영 앱입니다. 화면 조각 도구는 그리기만 하고 아무것도 저장하지 않습니다. 화면 조각을 그렸으면 그 내용을 답 글에서 다시 말하지 않고, 한두 문장으로만 답합니다. 한 답에 화면 조각은 두 개까지입니다.

- 할 일을 바꿨으면 바꾼 뒤에 결과를 그립니다. 1~2개면 `ui_result`, 3개 이상이면 그 할 일들이 든 하루나 주의 `ui_period_list`(`highlight_task_ids`에 바꾼 할 일)를 그립니다.
- 사용자가 말한 할 일의 날짜가 분명하지 않으면 날짜를 묻는 글을 쓰지 않습니다. `add_task`를 날짜 없이 부른 뒤, `list_tasks`로 그 기간을 보고 비어 있는 날 2~4개를 `ui_date_choice`로 제안합니다. 이 답에는 `ui_result`를 그리지 않습니다. `ui_date_choice`는 시각이 없는 열린 할 일에만 쓰고(날짜는 있어도 됩니다), 시각이 잡힌 할 일에는 쓰지 않습니다.
- 하루나 한 주의 할 일을 보여 줄 때는 `ui_period_list`, 날짜로 묶이지 않는 할 일 모음은 `ui_todo_list`를 씁니다.
- 숫자나 진행을 보여 줄 때는 `ui_block`의 `stat`, `progress`를 씁니다. 숫자는 이번 차례의 도구 결과나 사용자가 말한 값만 씁니다. 비율(%)을 쓰지 않습니다. `progress`는 사용자가 스스로 정한 목표나 사용자가 물은 진행에만 쓰고, 하지 않은 일의 수로 쓰지 않습니다.
- 고를 것이 2~4개면 `ui_choice`, 짧은 정리는 `ui_summary_card`를 씁니다. 그 밖의 짧은 답, 감정, 쉬자는 말에는 그리지 않습니다.
- 화면 조각에 이모지, 주소(URL), 마크다운 표·제목을 넣지 않습니다. `ui_block`의 `text`는 `**굵게**`와 줄바꿈만 읽습니다.
- 버튼은 이어 말하기(`send`), 앱 화면 열기(`open`), 할 일 완료(`complete`)만 있습니다. 빼기, 우선순위, 시각 바꾸기는 버튼으로 만들지 않고, `send` 버튼의 이름으로도 빼기, 우선순위 바꾸기, 시각 바꾸기를 시키지 않습니다(그런 일은 사용자가 직접 말합니다).
- `ui_result`, `ui_period_list`의 `highlight_task_ids`에는 이번 답에서 바꾼 할 일만 넣습니다.
- 카드 고정(`pin_card`, `unpin_card`, `reorder_cards`)은 사용자가 고정하거나 내리거나 순서를 바꿔 달라고 할 때만 합니다. 고정할 수 있는 조각은 `ui_todo_list`, `ui_choice`, `ui_summary_card`입니다.
```

- 텔레그램 대화의 `system.md`는 바꾸지 않는다.

### 9.3 도구 설명 (`mcp_adapter._SPECS`)

| 도구 | 설명 | 입력 스키마 |
|---|---|---|
| `ui_date_choice` | "앱 화면에 날짜 고르기 조각을 그립니다(그리기만 합니다). task_id는 시각이 없는 열린 할 일 번호이고(날짜는 있어도 됩니다), candidates는 2~4개의 날짜(오늘부터 90일 안)와 짧은 메모입니다. 사용자가 고르면 앱이 그 날짜로 옮깁니다. 시각이 잡힌 할 일에는 쓰지 않습니다." | `UI_COMPONENTS["ui_date_choice"]["schema"]` |
| `ui_result` | "이번 답에서 바꾼 할 일 1~2개의 결과(전과 뒤, 되돌리기)를 앱 화면에 그립니다(그리기만 합니다). 바꾸는 도구를 부른 뒤에 부릅니다. 3개 이상이면 ui_period_list를 씁니다." | 같은 방식 |
| `ui_period_list` | "하루(day) 또는 한 주(week, 예: 2026-W44)의 할 일을 날짜별로 앱 화면에 그립니다(그리기만 합니다). highlight_task_ids에는 이번 답에서 바꾼 할 일을 넣습니다." | 같은 방식 |
| `ui_block` | "기본 부품을 쌓은 카드를 앱 화면에 그립니다(그리기만 합니다). 부품: heading, text(**굵게**·줄바꿈만), stat, progress, todo_rows, tags, bullets, buttons(send·open·complete), divider, group(row: stat·progress 2~3개, stack: 2~6개). 부품은 모두 12개까지, group은 한 단계, buttons는 하나만 맨 끝에, todo_rows는 둘까지입니다." | 같은 방식 |

- 기존 `ui_todo_list`, `ui_choice`의 설명에서 "같은 뜻을 답 글에도 씁니다", "같은 질문을 답 글에도 씁니다"를 뺀다(9.2와 맞춘다).
- 도구 수: BE-1은 앱 대화 도구 수를 바꾸지 않고, BE-2가 4개를 더한다(지금 코드는 `TOOL_NAMES` 21개 + 앱 전용 6개 = 27개, `grant_xp`가 아직 없어 SP3-4 10장의 28과 다르다. 시험은 절대 수가 아니라 "BE-1 전후 같음", "BE-2에서 +4"로 쓴다). 스파이크 S12(도구 수와 지연)를 BE-2에서 다시 잰다(14장).

## 10. BE 바꿀 것

### 10.1 카탈로그 (`tools/ui.py`)

- 모델: `DateChoiceProps`, `ResultProps`, `PeriodListProps`(`day`·`week` 하나만: `model_validator`), `BlockProps`와 부품 모델 10개(`HeadingEl`, `TextEl`, `StatEl`(`Delta`), `ProgressEl`, `TodoRowsEl`, `TagsEl`(`TextTag` \| `AreaTag`), `BulletsEl`, `ButtonsEl`(`Button`, `do`: `SendDo` \| `OpenDo` \| `CompleteDo`, `kind`로 가름), `DividerEl`, `GroupEl`). 모두 `_Props`(`extra="forbid"`, `strict=True`).
- **묶음은 구분 유니언 두 단계**: 바깥 `Element = Annotated[Union[HeadingEl, …, DividerEl, GroupEl], Field(discriminator="type")]`, 그 안의 `GroupEl = Annotated[Union[RowGroup, StackGroup], Field(discriminator="layout")]`(둘 다 `type: Literal["group"]`). `type` 하나로는 둘을 가를 수 없어서다. JSON Schema에서는 `oneOf` 안의 `oneOf`가 되고, 앱 검사기는 `layout`의 `const`로 가른다.
- `_COMPONENTS`에 넷을 `"brain"` 출처로 더한다: `ui_date_choice`, `ui_result`, `ui_period_list`, `ui_block`. 순서는 기존 두뇌 셋 뒤, 하네스 앞.
- `BRAIN_COMPONENTS`는 지금처럼 출처에서 만들어 7개가 된다. 지금 이 값을 쓰는 세 곳을 나눈다.
  - **고정**: `PINNABLE_COMPONENTS = ("ui_todo_list", "ui_choice", "ui_summary_card")`. `pin_card`와 그 스키마의 `enum`이 이것을 쓴다(새 넷이 고정되지 않게).
  - **두뇌에게 주기**: `mcp_adapter.APP_ONLY_TOOLS`는 지금 `[*BRAIN_COMPONENTS, …]`라 카탈로그에 이름을 더하면 바로 두뇌에게 간다. BE-1은 이것을 `[*PINNABLE_COMPONENTS, "pin_card", "unpin_card", "reorder_cards"]`로 바꿔 지금의 6개를 지키고, BE-2가 새 넷을 더한다(14장).
  - **화면 도구 판정**: `call_tool`의 `ui = name in BRAIN_COMPONENTS`는 그대로 둔다(7개 모두 화면 도구).
- JSON Schema는 `model_json_schema()`가 만든다(`$defs`와 `oneOf` + `discriminator`. `@cfworker/json-schema`는 `discriminator`를 모르는 키로 지나치고 `oneOf` + `type`의 `const`로 판정한다. BE-1이 공유 고정 자료로 확인한다).
- **스키마가 보는 것과 BE만 보는 것**: 후보 날짜(6.2)는 스키마가 형식(`YYYY-MM-DD`)·개수·서로 다름만 보고, 오늘~90일 범위는 BE-2의 뜻 검사가 본다(스키마는 시계를 모른다). BE-1만 병합된 동안에는 두뇌가 이 도구를 받지 않으므로 빈틈이 없다. `model_validator`가 보는 서로 다름 가운데 정수 목록 셋은 `json_schema_extra`로 `uniqueItems: true`를 붙여 앱 검사기도 거른다. `day`·`week` 하나만(`period_one`), `value ≤ max`(`value_over_max`), 후보 날짜의 서로 다름(`not_unique`)은 JSON Schema에 나오지 않는 BE 전용 판정이다(7.2 끝).

### 10.2 지금 값 붙이기 (`mcp_adapter._stream_output`, `store/views.py`)

| 조각 | `output.data` | 만드는 곳 |
|---|---|---|
| `ui_todo_list` | `{todos}` (지금 그대로) | `ui_todo_refs(…, drafts=False)` |
| `ui_date_choice` | `{today, todo}` (`todo`가 지워졌으면 `null`) | `todo_refs([task_id], drafts=False)` |
| `ui_result` | `{today, items[]}` (6.3) | 새 `Tools.ui_result_items(ctx, task_ids)`: `ctx.activity_ids`의 활동 행과 `activity_targets`에서 `task:<id>`를 찾고, 6.3 표로 `before`를, 활동 수와 대상 수로 `undo_id`를 정한다. 읽기만 |
| `ui_period_list` | `{today, start, end, days[], outside[]}` (6.4) | 새 순수 함수 `store/views.py period_view(tasks: TasksRepo, start: date, end: date, today: date) -> list[DayView]`(`TasksRepo.list(status=TaskStatus.open, from_=start, to=end)`와 `status=TaskStatus.done` 두 번 읽어 6.4 규칙으로 날짜별로 나눈다. `today`는 `DayView.is_today`에만 쓴다) + `todo_refs` + `outside`(6.4 이유 순서). 뜻 검사(`highlight_task_ids` ⊆ 이번 답 활동의 할 일)는 `ui_result`와 같은 함수 |
| `ui_block` | `{today, todos?}` (7.3) | `todo_refs(ids, drafts=False)` |

- **`TodoRef`에 필드 둘을 더한다**: `planned_for`(논리적 날짜 또는 `null`), `scheduled_at`(UTC 또는 `null`). 깨지지 않는 변경이다(SP3-4 6.1). `todo_ref`가 모든 곳(고정 카드, 체크인 카드 포함)에서 같은 모양을 준다. SP3-4 6.3의 `TodoRef` 예시와 설명을 같은 PR에서 고친다.
- `today`는 논리적 날짜(`Tools.today()`)다. 앱이 "오늘", "내일"을 기기 달력으로 만들지 않게 한다.
- 뜻 검사(6.2의 `task_id`, 6.3과 6.4의 "이번 답에서 바뀐 것", 6.4의 범위)는 도구 메서드(`Tools.ui_date_choice` 등) 안에서 `_draw` 뒤에 한다. 모두 읽기만 하고 `ctx.events`, DB, 파일을 건드리지 않는다(SP3-4 6.4.7 "그리기만", 시험으로 확인).

### 10.3 검사 (`validate_props`)

스키마와 쌓기 규칙 다음에, 새 넷과 기존 두뇌 셋의 모든 글 값에 대해:

1. 제어 문자(U+0000~U+001F, U+007F)가 있으면 거절. 예외는 `text.md`의 `\n`(4개까지). 코드 `bad_char`.
2. 방향 바꾸기 문자(U+202A~U+202E, U+2066~U+2069)가 있으면 거절. 코드 `bad_char`.
3. 금지어(SP1 `system.md`의 `banned-words` 블록 + SP5 10장의 "연속", "스트릭", "달성률")가 있으면 거절. 코드 `banned_word`. 목록은 `system.md` 블록을 읽어 만들고(정본 하나), 앱용 셋은 `tools/ui.py`의 상수다.
4. `send` 버튼 이름과 `ui_choice`의 `label`이 `/`로 시작하면 거절. 코드 `slash`.

오류 문구에는 값을 넣지 않는다(지금 규칙): `"children.2.md: banned_word (쓰지 않는 말이 있어요)"`.

### 10.4 한 답 두 개 상한 (`mcp_adapter.call_tool`)

`RunContext`에 `ui_drawn: int = 0`을, `mcp_adapter`에 상수 `UI_PARTS_PER_REPLY = 2`를 더한다. 두뇌 화면 도구가 검사를 지나 조각을 쓸 때 1을 더하고, 이미 `UI_PARTS_PER_REPLY`이면 부르지 않고 도구 오류 "한 답에 화면 조각은 2개까지예요."를 돌려준다(조각 없음). 하네스 조각과 `pin_card`는 세지 않는다. 스트림이 없는 차례(텔레그램, 회차)는 도구가 없거나 그려지지 않으므로 세지 않는다.

### 10.5 카탈로그 판

- **판 번호를 미리 잡아 두지 않는다**: 카탈로그를 바꾸는 BE PR은 **병합될 때 다음 판**을 쓴다(지금 `2026-10-24.2`. 형식은 `YYYY-MM-DD.n`, 날짜는 병합한 날, 같은 날이면 `n`을 올린다). SP6에서 카탈로그를 바꾸는 PR은 BE-1 하나다(14장). 습관 기록 스레드의 `ui_habit_check` PR도 같은 규칙이라, 먼저 병합되는 쪽이 앞 판을 쓴다.
- 앱은 판 값을 해석하지 않고 다르면 다시 받을 뿐이고(SP5 6장), 모르는 컴포넌트는 `UnknownPart`로 보인다. 그래서 판 순서가 어떻게 되든 앱은 깨지지 않는다.
- `GET /ui/catalog`, `/health.version.ui_catalog`, `GET /schema`의 `UiCatalog`가 같은 값을 준다(지금 그대로).

### 10.6 기준 SSE와 공유 고정 자료

- **공유 props 자료** `tests/fixtures/ui_props/<컴포넌트>/{ok,bad}/*.json`(BE-1): 새 넷 모두, `ui_block`은 7.2의 B1~B9마다 `bad` 하나 이상과 부품 10개가 모두 나오는 `ok`. 꾸며 낸 내용만. 앱은 복사하지 않고 제자리에서 읽는다(SP5 F4의 기준 SSE와 같은 방식).
- **기준 SSE** `tests/fixtures/app_golden/`(BE-2, `tests/test_app_golden.py`의 `CASES`에 더함): `chat_date_choice`(`add_task` → `ui_date_choice`), `chat_result`(`move_task` → `ui_result` + `data-activity`), `chat_period_list`(`move_task` 셋 → `ui_period_list`), `chat_block`(`ui_block` + `todo_rows`), `chat_ui_rejected`(쌓기 규칙 위반 → 조각 없음, 두뇌가 고쳐 다시 불러 하나만), `chat_gallery`(시험 전용: 새 조각과 기존 두뇌 셋이 모두 한 답에. 시험이 `monkeypatch.setattr(mcp_adapter, "UI_PARTS_PER_REPLY", 10)`으로 상한 10.4를 푼다. `BeEnv`에는 설정을 더하지 않는다. 앱 스크린샷용).

## 11. 앱 바꿀 것

### 11.1 폴더

```
web/app/src/ui/
  primitives/   CheckRow.tsx Heading.tsx MiniText.tsx Stat.tsx Progress.tsx TodoRows.tsx Tags.tsx
                Bullets.tsx Buttons.tsx Divider.tsx Group.tsx  parseMiniMd.ts  primitives.module.css
  components/   (기존) TodoList, TodoDraft, Choice, SummaryCard → primitives로 다시 짬
  chat/         DateChoice.tsx Result.tsx PeriodList.tsx  cards.module.css  registerChatParts.ts
  block/        Block.tsx  checkBlock.ts  renderElement.tsx
```

### 11.2 레지스트리

- `registry.tsx`는 지금 10개 + `registerParts(entries)`를 내보낸다(같은 이름을 두 번 등록하면 개발 중 오류). 지금 `registryNames`는 가져올 때 `Object.keys`로 굳은 배열이라 등록 뒤의 이름을 모른다. A-2는 이것을 함수 `registryNames(): string[]`로 바꾸고, 그것을 쓰는 `ui/catalog.test.ts`(지금 "길이 10", "카탈로그 고정 자료와 같은 이름")를 `registerChatParts()`를 부른 뒤 14개, 카탈로그와 같은 이름으로 고친다. `UiPart`의 판정 순서(이름 → 카탈로그 스키마 → 컴포넌트)는 그대로이고, `ui_block`만 스키마 다음에 `checkBlock`을 한 번 더 본다.
- **새 넷은 대화 묶음에서 등록한다**: `ui/chat/registerChatParts.ts`가 `ui_date_choice`, `ui_result`, `ui_period_list`, `ui_block`을 등록하고, `chat/MessageView.tsx`가 이것을 가져온다(대화 시트 묶음은 늦게 읽힌다, SP5 9장). 새 넷은 고정 카드와 체크인 카드에 나오지 않으므로(2장) 첫 화면 묶음에 넣지 않는다. 대화 밖에서 이 이름이 오면(있어서는 안 된다) 등록 전이라 `UnknownPart`다.
- 기본 부품(`primitives/`)은 오늘 화면의 고정 카드(기존 넷)가 쓰므로 첫 화면 묶음에 들어간다.

### 11.3 CSS (CSP 규칙)

- 모든 CSS는 `_app`과 함께 나간다(PR #107 규칙: Pages Router가 화면 이동 때 쪽 CSS를 인라인 `<style>`로 붙여 `style-src 'self'`에 막힌다). 그래서 `_app.tsx`에 `import "../ui/primitives/primitives.module.css"`, `import "../ui/chat/cards.module.css"`를 더한다. 대화 묶음의 자바스크립트는 늦게 읽혀도 CSS는 처음부터 한 장에 있다. `check:csp`가 이것을 지킨다(쪽 단위 CSS가 있으면 실패, 지금 그대로).
- 컴포넌트에 `style={{…}}`가 없다. 진행 막대는 `<progress>`를 `::-webkit-progress-bar`, `::-webkit-progress-value`, `::-moz-progress-bar`로 꾸민다(`appearance: none`).

### 11.4 메시지 그리기 (`chat/parts.ts`, `MessageView.tsx`)

- 조각 읽기는 그대로다(`ui_`로 시작하는 도구 조각 → `ViewPart kind: "ui"`, `output.data` → `data`).
- **`activity_ids` 읽기 (A-2)**: 지금 `parts.ts`의 `activity` 조각은 `{confirmation, undoIds}`만 읽는다. BE는 `data-activity`에 `activity_ids`도 보내므로(`harness/stream.py data_activity`) A-2가 `ViewPart kind: "activity"`에 `activityIds: number[]`를 더해 읽는다(없으면 `[]`).
- **확인 칸 숨김 규칙**: 한 메시지의 `ViewPart`를 다 모은 뒤, 확인 칸의 `activityIds`가 비어 있지 않고 그 id 하나하나가 **`undo_id`가 있는 `ui_result` 항목의 `activity_ids`(하나뿐)**와 같으면 `activity` 조각을 그리지 않는다. 하나라도 빠지면(할 일 둘을 바꾸고 하나만 그림, `undo_id: null`인 항목, `ui_period_list`만 있음) 확인 칸을 그대로 그린다. 순수 함수 `hideCoveredActivity(parts: ViewPart[]): ViewPart[]`로 두고 시험한다.
- **다시 연 대화에서는 숨기지 않는다**: `hideCoveredActivity`는 지금 받은 메시지에만 쓴다. `restored` 메시지에는 쓰지 않는다(지금 `localParts`는 `ui` 조각만 두므로 다시 연 대화에는 확인 칸이 없다. 나중에 확인 칸을 저장하게 되면 늘 보인다).
- 알림 줄(Toast)은 `useAction`이 지금처럼 띄운다(`ui_date_choice`의 확정, `CheckRow` 체크).

### 11.5 `PartContext`와 타입

- `usePartAction`은 지금 `needs_confirm`을 실패 알림으로 바꾼다. A-2는 `ui_date_choice`가 쓸 수 있게 `needs_confirm`을 돌려받는 선택(`{onNeedsConfirm}`)을 더하고, 카드는 그때 `ConfirmSheet`를 연다(8장).
- `PartContext`에 `onOpen?(screen: OpenScreen): void`를 더한다(대화 시트가 라우터 이동 + 시트 닫기로 채운다). 없으면 `open` 버튼을 그리지 않는다.
- `PartData`에 `today?: string`, `todo?: PartTodo | null`, `items?: ResultItem[]`, `start?`, `end?`, `days?: DayTodos[]`, `outside?: {reason: "moved" | "dropped" | "no_date"; todo: PartTodo}[]`를 더한다. `PartTodo`는 `planned_for`, `scheduled_at`을 더 읽는다(10.2).
- `types.gen.ts`는 BE `GET /schema`에서 다시 만든다(`TodoRef` 필드 둘, `UiCatalog`).

### 11.6 바꾸지 않는 것

- `localParts`(저장 모양, 200개, 7일), `history.ts`의 `restored` 표시, `UnknownPart`, `CatalogProvider`, `transport.ts`. 
- 고정 카드: 오늘 화면의 길게 누르기 메뉴와 `pin_card`가 받는 셋.

### 11.7 크기

- 첫 화면: SP6이 더하는 몫은 gzip 6KB 이하이고 합계는 180KB 이하(`npm run size`, SP5 9장). 넘으면 기본 부품 가운데 기존 넷이 쓰지 않는 것(`Stat`, `Progress`, `Tags`, `Group`)을 대화 묶음으로 옮긴다.
- 대화 묶음: `scripts/size.mjs`가 첫 화면 합계 다음 줄에 대화 시트 묶음(`chatSheetChunk`가 읽는 조각)의 gzip 크기를 알림으로만 찍는다(실패 기준 아님). SP6 앱 PR 설명에 앞뒤 값을 적는다.

## 12. 보안

| 위험 | 막는 것 |
|---|---|
| 두뇌가 화면 코드나 HTML을 넣음 | 화면은 앱에 미리 만든 컴포넌트뿐이다. props는 JSON 값이고 모든 글은 React 글 마디로 들어간다. `dangerouslySetInnerHTML`, `eval`, 동적 `import()`에 props를 쓰지 않는다(`web/app`에는 ESLint가 없어 `ui/primitives/primitives.css.test.ts`의 `noInlineStyle` 시험이 `src/ui/**/*.tsx`에서 `style={`와 `dangerouslySetInnerHTML`을 찾는다. `components/Markdown.tsx`는 이 검사 밖이고 원시 HTML을 끈다) |
| 마크다운으로 링크·그림·HTML | `parseMiniMd`는 `**`와 `\n`만 읽는다. 나머지는 글자 그대로 |
| 링크 주소(`javascript:`, 외부 주소) | props 어디에도 주소가 없다. 화면 열기는 `screen` 열거값 6개를 앱이 주소로 바꾼다. 그래서 주소 체계 허용 목록이 필요 없다 |
| 버튼이 큰 일을 함 | 8장 다섯 가지만. 앱은 버튼 동작을 `kind` 열거값으로만 받고 `ActionName`을 props에서 읽지 않는다 |
| props의 글을 믿고 쓰기 | 쓰기에 들어가는 값은 BE가 붙인 id(`data.todos[].id`, `data.todo.id`, `data.items[].undo_id`)와 스키마로 범위를 확인한 날짜 후보뿐이다. 할 일 제목·상태는 `data`에서만 읽는다. 누를 때 BE는 id와 형식을 보고(`/actions`, `/undo`), 시각 있는 할 일의 날짜 옮기기는 확인을 거친다(8장, BE-2). 날짜 후보의 범위는 그릴 때만 본다 |
| 이어 말하기로 명령 실행 | `send` 이름과 `ui_choice` `label`이 `/`로 시작하면 BE가 거절(10.3). 보이는 글과 보내는 글이 같다 |
| 이어 말하기로 무거운 일 시키기 (남는 위험) | 버튼 이름이 "이거 빼 줘" 같은 글이면, 누르는 순간 Dahun의 메시지로 가고 사용자 메시지 차례라 확인 없이 적용된다(SP3-4 10.1 A3). 막는 것은 프롬프트 규칙(9.2)뿐이고 BE가 뜻을 검사하지 않는다. 받아들이는 이유: 이름이 그대로 보이고, 누르는 것이 곧 그 글을 보내는 것이며, 빼기·우선순위는 되돌릴 수 있다(6.4.3). 쓰다 문제가 되면 `send` 이름의 낱말 검사를 더한다 |
| 방향 바꾸기 문자로 눈속임 | BE가 거절(10.3) |
| 큰 props로 화면·저장 부풀리기 | 개수·길이 상한(5장, 7.2), props 8KB(B9), 한 답 두 개(10.4). `localParts`는 200개 상한 그대로 |
| 로그로 새는 내용 | 도구 오류 문구에 값을 넣지 않는다(위치와 코드만). 시스템 로그에 props를 남기지 않는다(SP3-4 14장, 로그 검사 시험에 새 도구를 더한다) |
| 옛 앱이 모르는 조각을 잘못 그림 | 레지스트리에 없거나 스키마가 틀리면 `UnknownPart`(SP5 6장) |

## 13. 테스트

| 층 | 무엇 | 도구 | 통과 기준 |
|---|---|---|---|
| BE 스키마 | `tests/fixtures/ui_props/**/ok`는 모두 통과, `bad/<code>-*`는 그 `code`로 실패. 금지어, 제어 문자, 방향 문자, `/` 시작 거절. 오류 문구에 값 없음. BE-1 전후 앱 대화 도구 수가 같음 | pytest | `python -m pytest tests/test_ui_catalog.py` (새 파일) → 실패 0 |
| BE 도구 | 새 도구 넷: 뜻 검사(6.2 시각 있는 할 일 거절, 6.3 이번 답에 안 바뀐 할 일 거절, 6.4 범위 밖 거절), DB·파일·`ctx.events`를 건드리지 않음, 한 답 두 개 상한, 텔레그램 통로에는 없음, `pin_card`가 새 넷을 거절, BE-2에서 앱 대화 도구 수 +4. 앱 통로 `/actions move_task`가 시각 있는 할 일의 날짜를 바꾸면 `needs_confirm`, 시각 없으면 `applied`, 텔레그램 버튼은 바로 적용 | pytest | `python -m pytest tests/test_ui_tools.py` → 실패 0 |
| BE 지금 값 | `ui_result`: 6.3 표의 활동 종류마다 `before`, 추가 뒤 옮김 → `added`이고 `undo_id: null`(활동 둘), 옮김 하나 → `undo_id` 있음, 옮김 둘(A→B→C) → `before`는 A이고 `undo_id: null`, `tasks_confirmed`(할 일 둘) → `undo_id: null`, 확인으로 적용한 변경 → `undo_id: null`. `highlight_task_ids`에 이번 답에서 안 바꾼 할 일 → 도구 오류. `period_view`: 오늘에도 전에 잡은 할 일을 끌어오지 않음, `open`·`done`만, 할 일마다 한 번, 순서, `outside`의 이유 셋. `TodoRef`의 새 필드가 UTC | pytest | `python -m pytest tests/test_ui_tools.py tests/test_period_view.py` (뒤는 새 파일) → 실패 0 |
| BE 기준 SSE | 10.6의 여섯 파일이 `parse_sse`를 지나고 바이트 단위로 같음 | pytest | `python -m pytest tests/test_app_golden.py` → 실패 0 |
| 앱 스키마 | 같은 `tests/fixtures/ui_props/`를 제자리에서 읽어 카탈로그 스키마 + `checkBlock`이 BE와 같은 판정 | Vitest | `npx vitest run src/ui/block` → `0 failed` |
| 앱 부품 | 부품 10개: props로 그려짐, `parseMiniMd`(굵게, 줄바꿈, 짝 없는 `**`, `<b>`·`[a](b)`가 글자 그대로), `stat` 낭독 글, `<progress>` 값, `CheckRow` 상태 넷 | Vitest + Testing Library | `npx vitest run src/ui/primitives` → `0 failed` |
| 앱 카드 | 새 넷: 6.5 표의 모든 칸(정상, 읽기 전용, 다시 연 대화, `data` 없음), 누름의 정확한 본문(`move_task {id, planned_for}`, `/activity/{id}/undo`, `/chat` 글, 라우터 주소), 이미 정리된 할 일. 기존 넷의 SP5 시험이 그대로 통과 | Vitest + MSW | `npx vitest run src/ui` → `0 failed` |
| 앱 대화 계약 | 저장소의 `tests/fixtures/app_golden/chat_{date_choice,result,period_list,block,ui_rejected}.sse`를 `useChat` + `parts.ts`로 읽어 화면 결과 확인, `hideCoveredActivity`(전부 덮음 → 숨김, 일부 → 보임, `undo_id: null` 항목 → 보임, `ui_period_list`만 → 보임, `restored` → 보임), `activityIds` 읽기 | Vitest + MSW | `npx vitest run src/chat` → `0 failed` |
| 문구 | 부록 A의 문구가 `copy.ts`에 있고 금지어 없음 | Vitest, `lint-copy` | `npx vitest run src/lib/copy.test.ts` → `0 failed` |
| 대비 | 새로 쓰는 쌍(`--raised` 위 `--text-2`, `--surface` 위 `--hue` 글자, 진행 막대 `--primary` 대 `--raised` 3:1)을 모든 프리셋 × 밝게·어둡게에서 | Vitest(대비 계산) | `npx vitest run src/styles` → `0 failed` |
| 빌드·CSP | 정적 내보내기에 인라인 스크립트·스타일·쪽 CSS 없음 | `npm run build && npm run check:csp` | `CSP OK: <n> files` |
| 크기 | 첫 화면 180KB 이하 | `npm run size` | 종료 코드 0 |
| CSP 실행 | 빌드한 `out/`을 CSP 헤더로 띄우고 `chat_gallery.sse`로 대화를 열어 새 넷이 모두 부품으로 그려짐 + 콘솔 CSP 위반 0건 | Playwright | `npx playwright test csp.spec.ts` → 지금 셋("chat part renders under CSP", "no CSP violations", "screens keep their styles after moving between tabs")에 "SP6 cards render under CSP", "SP6 gallery has no CSP violations"를 더해 `5 passed` |
| 눈으로 | 390×844, `chat_gallery.sse` 대화 시트: (1) 기본 프리셋 밝게·어둡게에서 카드 7개(새 넷 + `ui_todo_list`, `ui_choice`, `ui_summary_card`) 하나씩 = 14장, (2) 프리셋 6개 × 밝게·어둡게 시트 전체 = 12장. 다시 짠 기존 넷은 SP6 전 스크린샷과 나란히 본다 | Playwright + MSW | `npx playwright test screens.spec.ts` → 26장 저장, 사람이 확인 |
| 디자인 | taste 규칙 | `node <taste>/scripts/lint.mjs --app web/app/src` | `0 FAIL` |
| 실기기 | 아이폰에서 날짜 없는 할 일 말하기 → 후보 누름 → 되돌리기, 할 일 둘 옮기기 → `ui_result` 되돌리기, 셋 옮기기 → `ui_period_list`, "이번 주 컨디션 어땠지" → `ui_block` | Dahun과 함께 | `docs/acceptance/sp5-checklist.md`에 SP6 줄을 더하고 모두 확인 |

- 프리셋 시험(대비 6벌, 스크린샷 12장)은 색 프리셋 티켓이 병합된 뒤에 켠다. 그 전에는 기본 프리셋 밝게·어둡게만 돈다.

## 14. 내보내는 순서와 티켓

**원칙**: 두뇌가 새 조각을 부를 수 있게 되는 PR(BE-2)은 앱이 그 조각을 그릴 수 있게 된 뒤(A-2 배포 뒤)에 병합한다. 그 전에는 BE가 새 이름을 카탈로그에만 싣고 두뇌에게 주지 않는다. 그래서 어느 순간에도 Dahun이 그릴 수 없는 조각을 받지 않는다(옛 앱이 남아 있어도 `UnknownPart`로 물러선다).

| 순서 | 티켓 | 맡는 곳 | 내용 | 기대는 것 |
|---|---|---|---|---|
| 1 | **BE-1** 카탈로그 | SP3-4 BE 스레드 | 10.1 모델·쌓기 규칙, 10.3 검사, `PINNABLE_COMPONENTS`, `TodoRef` 필드 둘(+ SP3-4 6.3 문서), 카탈로그 다음 판(10.5), 공유 props 자료(10.6), `GET /schema` 다시 만듦, `GLOSSARY.md`에 용어 셋. 도구 메서드는 아직 두뇌에게 주지 않는다(`APP_ONLY_TOOLS`에 넣지 않음) | 없음 |
| 1 | **A-1** 기본 부품 | 운영 앱 스레드 | `ui/primitives/` 10개 + `CheckRow`, `parseMiniMd`, CSS를 `_app`에, 기존 넷을 부품으로 다시 짬(시험·스크린샷 그대로) | 없음 (BE-1과 나란히) |
| 2 | **A-2** 새 카드 | 운영 앱 스레드 | `ui/chat/` 셋, `ui/block/`, `registerChatParts`, `activityIds` 읽기, `hideCoveredActivity`, `onOpen`, `usePartAction`의 `onNeedsConfirm`, 시각 있는 할 일의 "내일로" 확인 시트(SP5 5.5.5·F6 고침, BE-2가 들어오기 전에는 `needs_confirm`이 오지 않아 그대로 돈다), `registryNames()`와 `catalog.test.ts`, 부록 A 문구, 공유 props 자료로 스키마 시험, `types.gen.ts` 다시 만듦. 손으로 쓴 MSW SSE로 카드 시험 | BE-1, A-1 |
| 3 | **BE-2** 두뇌에게 주기 | SP3-4 BE 스레드 | 새 도구 넷의 메서드와 뜻 검사, 10.2 지금 값, `period_view`, 10.4 상한, 앱 통로 `move_task` 확인(8장, SP3-4 6.4.2 표 고침), `APP_ONLY_TOOLS`·`_SPECS`(9.3), `channel_app.md`(9.2), 기존 두 설명 고침, 기준 SSE 여섯(10.6), S12 다시 재기, 로그 검사 시험에 새 도구 | A-2가 Vercel에 배포됨 |
| 4 | **A-3** 계약·눈으로 | 운영 앱 스레드 | 기준 SSE로 대화 계약 시험(손으로 쓴 SSE를 바꿈), CSP 실행 시험, 스크린샷 26장, 대비, 실기기 체크리스트 | BE-2, (프리셋 시험은) 색 프리셋 티켓 |

- BE-1은 카탈로그만 바꾸고 BE-2는 카탈로그를 바꾸지 않는다(판은 BE-1에서 한 번만 오른다). BE-2에서 스키마를 고쳐야 하면 그 PR이 다음 판을 쓴다(10.5).
- A-1은 BE 변경이 없어도 배포할 수 있다(보이는 것이 같다).

## 15. 미결 사항

없다. 아래는 정하고 넘어간 것이고, Dahun이 다르게 원하면 이 문서를 고친다.

1. 날짜가 분명하지 않은 할 일은 **먼저 날짜 없이 추가**하고 고르면 날짜를 옮긴다(6.2). 초안(`propose_tasks`)으로 두면 고를 때 확정과 날짜 두 동작이 필요해 하나로 묶이지 않는다. 고르지 않으면 날짜 없는 열린 할 일로 남는다.
4. 앱 통로의 `move_task`도 시각 있는 할 일의 날짜를 바꾸면 확인을 거친다(8장, 리뷰 결정). SP5의 "늘 바로 적용"을 바꾼다.
2. 새 넷은 고정 카드로 올리지 않는다(`ui_block`의 숫자, `ui_result`의 결과는 그때의 값이라 오늘 화면에 남으면 낡는다). `ui_period_list` 고정은 다음 단계 후보다.
3. 한 답에 두뇌 조각 두 개까지(10.4).

## 부록 A. 새 고정 문구 (`web/app/src/lib/copy.ts`, Dahun 확인 필요)

| 키 (`copy.parts.*`) | 문구 | 쓰는 곳 |
|---|---|---|
| `dayLabel(m, d, w)` | `{M}월 {D}일 ({요일})` | 날짜 표시 모두 |
| `today` / `tomorrow` / `yesterday` | 오늘 / 내일 / 어제 | 6.2 후보 앞머리(`오늘 · 10월 24일 (토)`), 6.4 카드 제목 |
| `thisWeek` / `nextWeek` / `lastWeek` | 이번 주 / 다음 주 / 지난주 | 6.4 카드 제목 |
| `weekRange(a, b)` | `{a} ~ {b}` (예: 10월 26일 ~ 11월 1일) | 6.4 카드 제목 |
| `dayHead(d, w)` | `{D}일 {요일}` | 6.4 날짜 머리 |
| `dayHeadToday` | ` · 오늘` | 6.4 날짜 머리 뒤 |
| `otherDay` | 다른 날로 할게요 | 6.2 버튼이자 보내는 글 |
| `alreadySettled` | 이미 정리된 할 일이에요 | 6.2 |
| `noDate` | 날짜 없음 | 6.3 `added` |
| `changeChip.added` … | 추가 · 옮김 · 완료 · 다시 엶 · 뺌 · 고침 · 확정 | 6.3 알약 |
| `prevTitle(t)` | 이전 제목: {t} | 6.3 `updated` |
| `editedOnly` | 내용을 고쳤어요 | 6.3 `updated` |
| `confirmedDraft` | 초안을 확정했어요 | 6.3 `confirmed` |
| `changeAria(a, b)` | 이전 {a}, 지금 {b} | 6.3 낭독 |
| `resultCount(n)` | 바뀐 할 일 {n}개 | 6.5 `data` 없음 |
| `outsideHead.moved` / `.dropped` / `.noDate` | 기간 밖으로 옮긴 것 / 뺀 것 / 날짜 없는 것 | 6.4 |
| `openTodos` | 할 일 화면에서 보기 | 6.4 |
| `openActivity` | 기록에서 보기 | 6.4 |
| `periodFailed` | 할 일을 불러오지 못했어요 | 6.5 `data` 없음 |
| `noTodos` | 보여 줄 할 일이 없어요 | 5.3.5 |
| `dropped` | 뺌 | 5.3.5 보조 글 |
| `changedBySecretary` | 비서가 바꿈 | 바뀐 줄 낭독 |
| `trendAria.up(t)` / `.down(t)` / `.same` | 지난번보다 올라감 {t} / 지난번보다 내려감 {t} / 지난번과 같음 | 5.3.3 낭독 |
| `progressAria(l, n, m)` | {l} {n}/{m} | 5.3.4 낭독 |
| `tagsLabel` | 태그 | 5.3.6 목록 이름 |

그대로 다시 쓰는 문구: `copy.parts.unknown`, `todoCount`, `more`, `less`, `checkLabel`, `copy.chat.undo`("되돌리기"), `copy.chat.undone`("되돌렸어요"), `copy.activity.undoBlocked`, `copy.offline.writeLater`, 영역 이름, SP5의 "{요일} · 없음".

## 부록 B. 두뇌가 받는 도구 오류 (BE 고정 문구)

| 경우 | 문구 |
|---|---|
| 스키마·쌓기 규칙 (지금 형식) | `화면 조각 형식이 맞지 않아요: {위치}: {code}` + 새 `code`면 괄호 안 한 마디 |
| `block_too_many` | (부품은 모두 12개까지예요) |
| `buttons_place` | (버튼 줄은 하나만, 맨 끝에 둬요) |
| `todo_rows_too_many` | (할 일 줄은 둘까지예요) |
| `divider_place` | (구분선은 처음·끝에 두지 않고 둘을 붙이지 않아요) |
| `block_no_content` | (내용 부품이 하나는 있어야 해요) |
| `complete_not_in_rows` | (완료 버튼의 할 일은 같은 카드의 할 일 줄에 있어야 해요) |
| `too_large` | (조각이 너무 커요) |
| `bad_char` | (쓸 수 없는 글자가 있어요) |
| `banned_word` | (쓰지 않는 말이 있어요) |
| `slash` | (/로 시작하는 글은 쓸 수 없어요) |
| 6.2 시각 있는 할 일 | 시각이 잡힌 할 일은 날짜 고르기로 옮기지 않아요. 대화로 정해 주세요. |
| 6.2 열린 할 일 아님 | 시각이 없는 열린 할 일만 날짜를 고를 수 있어요. |
| 6.2 후보 날짜 범위 | 후보 날짜는 오늘부터 90일 안이에요. |
| 6.3 | 이번 답에서 바꾼 할 일만 보여 줄 수 있어요. |
| 6.4 바뀐 줄 표시 | 바뀐 줄 표시는 이번 답에서 바꾼 할 일만 할 수 있어요. |
| 6.3 모두 지워짐 | 보여 줄 바뀐 할 일이 없어요. |
| 6.4 범위 | 하루는 2주 전부터 8주 뒤까지, 주는 2주 전부터 8주 뒤까지 보여 줄 수 있어요. |
| 10.4 | 한 답에 화면 조각은 2개까지예요. |

## 변경 기록

| 날짜 | 판 | 내용 | 누가 |
|---|---|---|---|
| 2026-10-24 | v1 | 첫 초안: Dahun 결정 G1~G7, 기본 부품 10개, 완성 카드 셋 추가, 조립 카드, 버튼 허용 목록, 두뇌 규칙, BE·앱 변경, 티켓 다섯 | 운영 앱 스레드 |
| 2026-10-24 | v2 | 문서 리뷰 반영: `ui_result`의 `before` 꺼내기 표와 `undo_id` 조건(활동 하나·대상 하나), 앱 통로 `move_task` 확인(SP5 "늘 바로 적용" 바꿈), `todos_day`, 체크 줄 뜻은 카드마다, `activityIds` 읽기와 다시 연 대화의 확인 칸, `period_view` 규칙 하나와 서명, `outside` 이유 셋, `highlight_task_ids` 뜻 검사, 날짜 고르기 답에는 `ui_result` 없음, 날짜 고르기 대상 "시각 없는 열린 할 일", `send` 남는 위험, `registryNames()`, 도구 수는 상대 수로, 묶음 구분 유니언 두 단계, `UI_PARTS_PER_REPLY`, CSP 시험 이름 | 운영 앱 스레드 |
| 2026-10-24 | v3 | G-BE1이 계획의 빈 곳 3·9·10을 옮김: `todo_rows.checkable` 기본값 `true`(5.3.5), 후보 날짜 범위는 BE-2 뜻 검사·정수 목록 `uniqueItems`·BE 전용 판정(10.1, 7.2) | SP3-4 BE 스레드 |
| 2026-10-24 | v4 | G-A1이 계획의 빈 곳 1·2·5·12를 옮김: `CheckRow`의 `mark`(5.3.5), `parseMiniMd`가 돌려주는 줄 배열(5.3.2), `ui_choice` 질문은 마크다운 없는 `<p>`(6.1), `dangerouslySetInnerHTML` 금지는 시험으로(12장) | 운영 앱 스레드 |
