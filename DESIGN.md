---
version: alpha
name: my-planner
description: 다훈의 인생 비서. 운영 앱(web/app, 아이폰 PWA)과 대시보드(web/dashboard)가 함께 쓰는 디자인 시스템. 방향 A "종이와 잉크".
source_of_truth: web/shared/global.css
colors:
  # 라이트 (기본 프리셋 "종이")
  ground: "#F6F3EC"
  surface: "#FFFDF8"
  raised: "#EDE8DD"
  bar: "#FAF8F2"
  rule: "#E3DED2"
  border: "#D9D4C8"
  control: "#8A8478"
  text: "#1B1A17"
  text-2: "#3D3A33"
  muted: "#696357"
  primary: "#1B1A17"
  on-primary: "#FAF8F3"
  hue: "#2C5AB8"
  positive: "#2E7349"
  negative: "#B0352A"
  notice-bg: "#FFFBEB"
  notice-border: "#FDE68A"
  notice-ink: "#5C2A07"
  # 의미 색 (positive/negative)과 영역색·램프는 프리셋이 바꾸지 않는다
  # 다크
  dark-ground: "#12110F"
  dark-surface: "#1C1B18"
  dark-raised: "#2A2824"
  dark-bar: "#171613"
  dark-rule: "#2A2824"
  dark-border: "#3A3732"
  dark-control: "#7A756B"
  dark-text: "#F3EFE6"
  dark-text-2: "#D6D0C4"
  dark-muted: "#A59F92"
  dark-primary: "#F3EFE6"
  dark-on-primary: "#12110F"
  dark-hue: "#8FB0EC"
  dark-positive: "#6CC493"
  dark-negative: "#F08A7E"
  dark-notice-bg: "#2B2210"
  dark-notice-border: "#5C4A17"
  dark-notice-ink: "#F5D27A"
  # 삶의 영역 6색 (프리셋이 바뀌어도 고정, 라이트/다크 두 값)
  area-career: "#4553B5"
  area-finance: "#5A6B1C"
  area-health: "#B4482F"
  area-relationships: "#AD3F70"
  area-learning: "#8F6212"
  area-quality-of-life: "#26737A"
  dark-area-career: "#9AA5F0"
  dark-area-finance: "#B9CC6A"
  dark-area-health: "#F0937A"
  dark-area-relationships: "#EC8DB6"
  dark-area-learning: "#E0B45C"
  dark-area-quality-of-life: "#6CC3C9"
  # 단계 램프 (새벽 → 한낮, 채움 전용. 글자에 쓰지 않는다)
  ramp-1: "#A3AFC2"
  ramp-2: "#6FC7B8"
  ramp-3: "#F2C94C"
  ramp-4: "#F29B4B"
  ramp-5: "#EC6F5B"
typography:
  family: "Pretendard Variable, Pretendard, -apple-system, Apple SD Gothic Neo, Noto Sans KR, system-ui, sans-serif"
  display:  { size: 34px, weight: 700, line: 1.2,  tracking: -0.02em }
  title:    { size: 22px, weight: 700, line: 1.3,  tracking: -0.01em }
  headline: { size: 17px, weight: 600, line: 1.45, tracking: -0.01em }
  body:     { size: 17px, weight: 400, line: 1.6,  tracking: -0.01em }
  callout:  { size: 15px, weight: 400, line: 1.5,  tracking: 0 }
  label:    { size: 13px, weight: 600, line: 1.3,  tracking: 0 }
  caption:  { size: 13px, weight: 400, line: 1.4,  tracking: 0 }
spacing: { base: 4px, scale: [4, 8, 12, 16, 20, 24, 32, 40, 56], gutter: 24px, gutter-narrow: 16px, section: 28px, pad: 16px, message: 12px, speaker: 20px }
rounded: { field: 12px, container: 16px, sheet: 20px, bubble: 18px, pill: 999px, row: 0 }
elevation:
  none: "none"
  sheet: "0 -1px 0 var(--rule), 0 12px 32px rgb(27 26 23 / 0.10)"
motion: { fast: 120ms, base: 200ms, slow: 320ms, press-scale: 0.97, press: 150ms, easing: "cubic-bezier(0.2, 0, 0, 1)" }
sizes: { touch: 44px, row: 52px, check: 22px, measure-phone: 600px, measure-wide: 960px }
---

# my-planner 디자인 시스템

## Overview

**종이와 잉크.** 따뜻한 종이색 바탕 위에 잉크로 쓴 것처럼 보이는 화면이다. 카드를 쌓지 않고, 목록은
한 장의 종이처럼 이어지며 가는 선으로만 나뉜다. 큰 글자와 넓은 여백으로 읽기 편하게 하고, 색은 "의미가
있을 때만" 쓴다. 참고: Things 3(이어지는 목록, 둥근 체크), Apple 미리 알림(그룹 목록),
Gentler Streak(숫자 대신 말로 풀어 주는 상태, 죄책감 없는 동기 부여).

이 문서와 `web/shared/global.css`가 **단일 진실 소스**다. 앱(web/app)은 `npm run sync:design`으로
`global.css`를 자기 `src/styles/global.css`에 복사하고(생성 파일 머리말이 붙는다), 시험
(`scripts/sync-design.test.mjs`)이 사본이 원본과 같은지 본다. 대시보드(web/dashboard)도 같은 방식으로
옮겨 왔다(아래 "대시보드" 절). 사본을 앱 안에 두는 까닭: Vercel은 앱을 루트 `web/app`으로 빌드하고 `ignoreCommand`도 `web/app`만
비교한다. 토큰을 바꿀 때는 이 문서의 맨 위 값과 `global.css`를 **같은 커밋에서** 함께 고친다
(`contrast.test.ts`가 맨 위 색 값과 `global.css`를 맞춰 본다).

## Colors

### 바탕과 잉크 (프리셋이 바꾸는 색)

| 역할 | 쓰임 |
|---|---|
| `--ground` | 화면 바탕(종이). 목록도 이 위에 바로 놓인다 |
| `--surface` | 시트, 입력창, 비서 카드처럼 "떠 있는 것"의 바탕 |
| `--raised` | 눌린 줄, 선택된 칸, 표 머리. 이 위에는 영역색 글자를 두지 않는다 |
| `--rule` | 목록 사이 가는 선(1px), 섹션 머리 밑줄 |
| `--bar` | 아래 탭 막대 바탕(종이보다 한 톤 밝게) |
| `--border` | 입력창·알약 버튼·시트 손잡이 테두리(장식, 대비 요구 없음) |
| `--control` | 체크 동그라미 테두리, 꺼진 표시, 인용 막대. `--ground`·`--surface` 대비 3:1 이상 |
| `--text` / `--text-2` / `--muted` | 본문 / 보조 본문 / 메타 줄. 셋 다 `--ground`·`--surface` 위 4.5:1 이상 |
| `--primary` / `--on-primary` | 주 버튼 채움(잉크)과 그 위 글자 |
| `--hue` | **비서가 한 일과 링크에만.** 비서가 제안한 할 일 표시, 바뀐 줄 막대, 링크. 화면의 1% 안쪽 |

색감 프리셋(설정 › 이 기기 › 색감)은 위 역할만 바꾼다. 기본은 **종이**(`data-palette` 없음), 나머지는
잉크(무채색, 이 문서 전의 기본값), 숲, 바다, 노을, 라벤더(`:root[data-palette="…"]`). 프리셋마다 라이트와
다크 두 벌이 있고, 대비 시험이 12벌 모두를 본다. 설정의 색 견본은 자기 `data-palette`를 달아 그 프리셋 색으로
그려진다.

**`--control`을 정한 까닭.** 이 문서 전의 앱은 `--control`을 옅은 회색(바탕 대비 1.3~2.4:1)으로 두고
입력창·알약·런처 테두리와 체크 테두리에 함께 썼다. 이 문서의 뜻(체크 테두리, 3:1)에 맞춰 열두 벌 모두
`--control`을 3:1 이상으로 진하게 했고(잉크도 이 값 하나만 바뀜), 입력창·알약·런처 테두리와 시트 손잡이는
`--border`로 옮겼다. 남은 쓰임은 체크 동그라미, 마크다운 인용 막대, (대시보드의) 점선 눈금이고 모두 3:1 그래픽 규칙을
지킨다.

### 의미 색 (프리셋과 상관없이 고정)

- `--positive` / `--negative`: 됨/실패, 오름/내림. 글자로 쓸 때는 반드시 말(“+2”, “실패”)을 함께 쓴다.
  라이트·다크 두 값뿐이고 프리셋(잉크 포함)이 바꾸지 않는다. `--ground`·`--surface` 위 4.5:1 이상.
- `--notice-*`(`bg`, `border`, `ink`): 오프라인·연결 끊김 띠. 프리셋이 바꾸지 않는다.
- **삶의 영역 6색** `--area-career` `--area-finance` `--area-health` `--area-relationships`
  `--area-learning` `--area-quality-of-life`: 영역을 알아보는 색. **점(8px), 작은 태그 글자, 곡선·레이더의
  선**에만 쓴다. 넓은 면을 칠하지 않는다. `--ground`·`--surface` 위 글자 대비 4.5:1 이상(라이트·다크).
  영역 이름 글자를 항상 함께 쓴다(색만으로 구분하지 않는다).
- **단계 램프** `--ramp-1`~`--ramp-5`(새벽 회청 → 민트 → 노랑 → 주황 → 코랄): 순서가 있는 단계
  (사다리 점수 구간, 컨디션 1~5, 레벨 진행)를 **채움으로만** 보여 준다. 글자에는 쓰지 않는다.

### 하지 않는 것

그라디언트 배경, 색 그림자, 같은 뜻의 색을 여러 개 두기(빨강은 `--negative` 하나), 영역색으로 큰 면 칠하기.

## Typography

글꼴은 **Pretendard Variable** 1.3.9(npm `pretendard`, 동적 서브셋 woff2 92개)를 앱 안에 직접 둔다
(`public/fonts/pretendard/`, OFL 라이선스 파일 함께, `unicode-range`로 쓰는 글자의 조각만 받음,
`font-display: swap`, CSP `font-src 'self'`). `@font-face`는 `global.css` 맨 끝에 있다(대시보드도 같은 파일을
쓰고, 글꼴은 자기 `public/fonts/pretendard/`에 둔다). 서비스 워커는 글꼴을 미리 받아 두지 않는다
(`/_next/static`만 받는다): 오프라인 첫 화면은 시스템 글꼴로 그려질 수 있다. 숫자는 모두
`font-variant-numeric: tabular-nums`(`.tnum`).

| 역할 | 값 | 쓰임 |
|---|---|---|
| `display` | 34 / 700 / 1.2 | 화면 큰 제목("오늘") |
| `title` | 22 / 700 / 1.3 | 시트 제목, 대시보드 섹션 제목 |
| `headline` | 17 / 600 / 1.45 | 카드 제목, 강조 줄 |
| `body` | 17 / 400 / 1.6 | 본문, 할 일 제목, 비서 말 |
| `callout` | 15 / 400 / 1.5 | 버튼 글자, 표 칸, 촘촘한 본문 |
| `label` | 13 / 600 / 1.3 | 섹션 머리("할 일 3"), 태그 |
| `caption` | 13 / 400 / 1.4 | 메타 줄(시각, 영역, "비서가 제안") |

- 13px 아래는 쓰지 않는다(탭 막대 글자 11px 하나만 예외).
- 크기는 rem으로 둬서 글자 크기 설정을 따른다. 역할 클래스 `.t-display` … `.t-caption`이나 토큰
  `--fs-display` … `--fs-caption`(줄 높이 `--lh-*`)을 쓰고 화면마다 크기를 새로 정하지 않는다. 정말 필요하면
  이 표에 먼저 추가한다.
- 옛 이름도 남겨 둔다(두 앱을 고쳐 쓰지 않으려고): 앱의 `--size-title`(= display, 화면 큰 제목),
  `--size-body`(= body), `--size-section`(= callout), `--size-meta`(= caption), `--size-tab`(11px), 대시보드의
  `--fs-section`(= callout), `--fs-meta`(= caption), `--fs-nav`(= headline). 대시보드의 `--fs-title`과
  `--fs-body`는 이 표의 title(22)과 body(17)가 된다.
- 굵기는 400/600/700 셋만.

## Layout

- 폰: 좌우 여백 `--gutter` 24px(360px 미만 화면은 16px). 섹션 사이 `--section-gap` 28px, 섹션 머리와 내용
  사이 8px. 상자 안 여백은 `--pad` 16px.
- 목록 줄 높이 최소 52px, 누르는 곳 최소 44×44px.
- 대시보드: 본문 최대 폭 960px 가운데 정렬, 2열은 720px 이상에서만. 폰에서는 한 열.
- 채팅: 내 말 말풍선 최대 폭은 80%(아래 채팅 참고).
- 간격 토큰 `--gap`은 앱의 옛 블록 간격 20px 그대로다. 대시보드의 옛 `--gap`(12px, 패널 사이)은
  `--panel-gap`이 이어받는다. 대시보드의 옛 `--row`(44px)는 `--control-h`, `--measure`(720px)는 이 문서의
  960px(`--measure-wide`)가 된다.
- 안전 영역: 아래 고정 막대는 `padding-bottom: max(16px, env(safe-area-inset-bottom))`.

## Elevation & Depth

종이는 평평하다. **그림자는 시트(아래에서 올라오는 판)와 토스트에만**, 나머지는 바탕 톤 차이와 가는
선으로 나눈다. 겹침 순서: 본문 0 · 고정 막대 10 · 팝오버 20 · 시트 30 · 확인 창 40 · 토스트 50.

## Motion

- 눌림: `transform: scale(0.97)` 150ms(버튼, 알약, 체크). 체크는 채워질 때 120ms 페이드.
- 시트: 320ms 아래에서 위로. 목록 줄 추가·삭제: 200ms 높이 접힘.
- `prefers-reduced-motion: reduce`이면 모든 이동·크기 변화를 끄고 색 변화만 남긴다.
- 무한 반복 움직임은 쓰지 않는다(스트리밍 중 점 세 개 하나만, 움직임 줄이기에서 멈춤).

## Shapes

| 토큰 | 값 | 쓰임 |
|---|---|---|
| `--radius-field` | 12px | 버튼, 입력창, 선택 칸 |
| `--radius-container` | 16px | 비서 카드, 대시보드 패널, 그룹 목록(`--radius-group`, `--radius-panel`도 같은 값) |
| `--radius-sheet` | 20px | 시트 윗모서리 |
| `--radius-bubble` | 18px | 내 말 말풍선(꼬리 쪽 아래 오른쪽만 4px) |
| `--radius-pill` | 999px | 알약 버튼(컨디션 1~5, 선택지), 태그 |
| 목록 줄 | 0 | 이어지는 종이 |

12px 토큰 이름은 `--radius-field`다(초안의 `--radius-control`이 아님): 대시보드가 이미
`--radius-control`을 알약(999px)으로 쓰고 있어서, `global.css`는 `--radius-control`을 `--radius-pill`의 옛
이름으로 남긴다. 새 코드에서는 `--radius-control`을 쓰지 않는다.

**누르는 것은 12px 또는 알약, 담는 것은 16px.** 이 차이가 "누를 수 있음"의 신호다.

## Components

### 목록 줄 (ListRow, CheckRow)
바탕 위에 바로. 왼쪽 22px 둥근 체크(테두리 1.5px `--control`, 끝나면 `--primary`로 채우고 `--on-primary`
체크; 누르는 곳은 44×44px이고 동그라미의 왼쪽 끝이 글자 여백에 맞는다),
제목 `body`, 둘째 줄 `caption` `--muted`(영역 점 + 영역 이름 · 시각). 비서가 제안한 줄은 둘째 줄을
`--hue`로 "비서가 제안". 줄 사이 선은 글자 시작점부터(왼쪽 들여쓴 1px `--rule`). 끝난 줄은 `--muted` + 취소선.
누를 수 없는 체크(오프라인, 읽기 전용 카드)는 같은 동그라미를 **점선** 테두리로 그려, 색만이 아니라 모양으로도
다르게 보인다.

### 섹션 머리
`label` `--muted` + 오른쪽에 보조 숫자(“1개 끝남”), 밑에 1px `--rule`. 카드 상자를 씌우지 않는다.
오늘·할 일·기록은 이어지는 종이다(`<Group paper>`: 줄이 화면 끝까지 닿아 스와이프와 44px 체크가 들어가고,
줄 사이 선은 글자 시작점에서 여백 끝까지). 설정·체크인·습관 화면은 Apple 설정식 그룹 목록(`--surface` +
16px 둥글기, `<Group>`)을 쓴다. 그룹 안 줄의 옆 여백은 `--row-pad-x`, 불투명 바탕은 `--row-bg`가 정한다.

### 버튼
- 주 버튼: `--primary` 채움, `--on-primary` 글자, 높이 48px, 12px 둥글기, 화면당 하나.
- 보조 버튼: 투명 + 1px `--border`, `--text` 글자.
- 글자 버튼: `--hue` 글자(링크 성격일 때만).
- 알약 선택(컨디션, 선택지): 높이 44px, 1px `--border`, 고르면 `--primary` 채움. `aria-pressed` 또는 라디오.

### 입력창 (채팅 입력 포함)
최소 높이 48px, 12px 둥글기, `--surface` 바탕 + 1px `--border`, 안쪽 여백 12×16px, 글자 `body`.
**보낼 수 있을 때만 테두리가 1.5px `--primary`로 진해진다**(글이 비면 다시 옅게). 두 줄까지 위로
자라고 그 뒤는 안에서 스크롤(줄 수에 따라 `<textarea rows>`를 1~2로 바꾼다. `style=`로 높이를 넣지 않음).
보내기 버튼은 오른쪽 36px 원(`--primary`)이지만 누르는 곳은 44×44px. 답이 오는 동안(기다림·생각·스트리밍)에는
같은 자리, 같은 원이 멈춤 버튼이다(채운 네모 그림, 이름 "멈추기"). 입력이 비어 있어도 켜져 있고, 누르면 이미 온 글은
그대로 두고 끝에 "멈췄어요." 한 줄을 붙인 뒤 입력창이 다시 보내기로 돌아온다.
글이 있을 때만 입력창 안 오른쪽 끝(첫 줄 가운데)에 지우기 ×(`--muted`, 누르는 곳 44×44px, 이름 "입력한 글 지우기")가
뜬다. 누르면 글이 한 번에 비고 초점은 입력창에, 높이는 한 줄로 돌아온다(한 줄 쓰기는 열린 채). 입력창은 그 자리만큼
오른쪽 여백을 늘 두어 글이 × 밑으로 가지 않는다. 보내기·멈춤 버튼과는 따로다.
엔터는 보내기, 한글 조합 중의 엔터와 Shift+엔터는 보내지 않는다.

### 채팅
**비대칭 대화**가 기본이다(참고 프로젝트의 AI 코치 화면에서 가져옴).
- 비서 말: 말풍선 없이 폭 전체를 쓰는 열린 글, `body`(Markdown). 대화 첫 답 위에만 작은 `label` 머리
  ("비서"). 시각은 따로 적지 않고, 대화가 30분 넘게 끊겼을 때만 가운데 `caption` 구분 줄("오후 3:12").
- 내 말: 오른쪽 말풍선, `--raised` 바탕 + `--text` 글자, 둥글기 18/18/4/18(꼬리 쪽 아래 오른쪽만 4px),
  여백 12×18px, 최대 폭 80%.
- 메시지 사이 12px, 말한 사람이 바뀌면 20px.
- 비서 카드(생성형 UI): `--surface` + 1px `--rule` + 16px 둥글기 + 16px 여백. 안의 부품은 이 문서의
  목록 줄·버튼·알약을 그대로 쓴다. 카드 전체를 누를 수 있으면 버튼 하나의 `::after`를 카드 전체로 늘려
  탭 정지는 하나만 둔다.
- 추천 질문: 높이 44px 알약(`--surface`, 1px `--border`, 여백 10×18px, `callout`), 한 줄로 오른쪽 끝을
  넘겨 흘러가는 가로 스크롤(`scroll-snap`, 흐림 처리 없음). 처음 화면과 답 끝에만.
- 답 아래 동작(복사, 다시 답하기)은 `caption` 글자 버튼, 마지막 답에만, 누르는 곳 44px.
- 처음 화면(대화 없음): `title` 인사 한 줄 + 오늘 요약 비서 카드 하나 + 추천 질문 줄.

### 시트
`--surface`, 윗모서리 20px, 손잡이 36×5px `--border`, 그림자 `sheet`(`--shadow-sheet`). 제목 `title`.

### 태그
알약, `label` 크기, 영역 태그는 영역색 점 + 영역 이름(`--text-2`). 바탕을 칠하지 않는다.

### Pictograms
작은 선 그림 30개. 원본은 `web/shared/pictograms.svg` 하나이고, 앱과 대시보드의 `npm run sync:design`이
`src/components/pictograms.gen.tsx`(`<PictogramSprite />`, `<Pictogram name size label? />`)를 만든다. 스프라이트는
`_document`의 `<body>` 첫 요소로 한 번 그린다(`check:csp`가 본다). 바꿀 때는 원본 SVG, 이 표, 두 앱의 생성 파일을
같은 커밋에서 고친다.

1. 24px 격자, 선 1.75, 둥근 끝·둥근 이음, 채우지 않음. 크기는 16 / 20 / 24 셋. 16px에서는 선 2.
2. 색은 `currentColor`. 기본 `--text` 또는 `--muted`. 영역 픽토그램만 영역색(`--area-*`)으로 그릴 수 있다(작은 표식이라
   "점·작은 태그"와 같은 취급, 면 칠하기 아님). 비서 표시(`assistant`)만 `--hue`.
3. 혼자 뜻을 전하지 않는다: 늘 옆에 이름 글자가 있다(영역 이름, 종류 이름). 글자가 있으면 픽토그램은 `aria-hidden`.
   글자 없이 쓰는 곳(한눈에 띠의 사건 표식)은 `role="img"`와 `aria-label`, 그리고 같은 내용의 표.
4. 이모지 아이콘을 쓰지 않는다. 조작 아이콘(더하기, 체크, 닫기, 보내기, 펼침)은 `icons.tsx`가 맡고 픽토그램과 섞지 않는다.
   앱 탭 막대 아이콘은 SP8에서는 그대로이고, SP9가 탭을 바꿀 때 스프라이트로 옮긴다(그때 id가 세 개 늘고 아래 표도 함께 고친다).
5. 원(36px, `--raised`) 안에 넣는 것은 사건 줄과 홈 머리처럼 "줄의 얼굴"일 때만. 카드 안에 카드처럼 겹치지 않는다.

| id | 이름 | 쓰는 자리 |
|---|---|---|
| `career` | 커리어 | 영역 태그, 요즘 손이 간 영역, 이룬 순간 줄 |
| `finance` | 경제 | 영역 태그, 요즘 손이 간 영역, 이룬 순간 줄 |
| `health` | 건강 | 영역 태그, 요즘 손이 간 영역, 이룬 순간 줄 |
| `relationships` | 관계 | 영역 태그, 요즘 손이 간 영역, 이룬 순간 줄 |
| `learning` | 배움 | 영역 태그, 요즘 손이 간 영역, 이룬 순간 줄 |
| `quality_of_life` | 삶의 질 | 영역 태그, 요즘 손이 간 영역, 이룬 순간 줄 |
| `high` | 높은 때 | 사건 줄, 거르기, 한눈에 띠 |
| `low` | 힘든 때 | 사건 줄, 거르기, 한눈에 띠 |
| `turning_point` | 전환점 | 사건 줄, 거르기, 한눈에 띠 |
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
| `eye` | 보임 | 민감한 사건 |
| `eyeoff` | 가림 | 민감한 사건 |
| `assistant` | 비서가 만듦 | 비서가 만든 사건, 도움 상자 |
| `home` | 한눈에 | 대시보드 내비게이션, 탭, 거르기 "전체" |
| `curve` | 인생곡선 | 대시보드 내비게이션, 탭, 거르기 "전체" |
| `status` | 상태창 | 대시보드 내비게이션, 탭, 거르기 "전체" |
| `list` | 목록 | 대시보드 내비게이션, 탭, 거르기 "전체" |
| `estimate` | 추정 | 추정 태그 |
| `settings` | 설정 | 대시보드 설정 링크 |
| `dumbbell` | 운동메이트 | 브리핑 관찰 줄, 비서 메모 |
| `compass` | 라이프 매니저 | 브리핑 관찰 줄, 비서 메모(SP15 상대 고르기) |

### 대시보드
- 패널: `--surface` + 16px 둥글기 + 20px 여백, 제목 `title`, 부제 `caption`.
- 인생 곡선: 사다리 선 2px `--text`, 영역 선 1.5px 영역색, 사건 점 8px(비서가 만든 사건은 `--hue` 테두리),
  눈금과 축 글자 `caption` `--muted`, 격자는 `--rule` 한 겹. 곡선 아래 칠하기 없음.
- 레이더(삶의 수레바퀴): 축 6개, 칸 테두리 `--rule`, 이번 분기 1.5px `--text`, 지난 분기 1px 점선 `--muted`.
- 상태창: 레벨 숫자 `display`, XP 막대 높이 6px(`--raised` 위 `--primary`), 영역 능력치는 숫자 + 단계 램프 점.
  연속 기록(스트릭)과 빨간 경고는 쓰지 않는다.
- 추이 차트(컨디션, 주간 달성): 맨 SVG, `viewBox` 폭 = 실제 폭(글자가 늘지 않게), 격자 1px 점선 `--rule`,
  선 2px `--text`, 점 이름은 지금 값 하나만, 다가올 기간은 `--raised` 띠. 같은 내용의 화면 읽기용 표를 함께 둔다.
- 목표 대비 실제 막대: 뒤에 `--raised` 목표 막대, 앞에 `--primary` 실제 막대, SVG `rect`(CSP 안전).
- 날짜 칸(체크인 달력): 상태를 **모양으로도** 구분한다(채움 = 함, 굵은 테두리 = 오늘, 점선 = 쉼, × = 못 함),
  오늘은 글자로도 "오늘". 칸 하나가 44px 누르는 곳, 상태는 `aria-pressed`/`aria-label`.
- 패널 사이 세로 간격은 12px 하나로 통일, 한 열에서는 할 일이 먼저.
- 램프로 칠한 칸과 점(HP 칸, 컨디션 점, 능력치 단계 점)에는 1px `--text` 고리를 둘러, 옅은 단계도 3:1을 넘긴다.

**옮겨 옴.** 대시보드는 앱과 같은 방식으로 이 체계를 쓴다(`web/dashboard`의 `npm run sync:design`,
`scripts/sync-design.test.mjs`). 대시보드의 대비 시험은 `src/styles/tokens.test.ts`이고, 대시보드만의 이름은
`src/styles/tokens.css`(차트·막대, 모두 역할 토큰의 `var()`)에 있다. 일부러 따르지 않는 것과 그 까닭:
- 곡선의 영역 선: `/curve`가 영역별 계열을 보내지 않는다(그릴 데이터가 없음).
- 사건 점 8px과 `--hue` 테두리: 히스토리는 영역 태그와 "비서가 만듦" 표시를 쓴다(곡선 차트의 점은 그대로 ▲▼◆,
  종류는 높은 때·힘든 때·전환점).
- 레이더 축 선의 영역색: 차트 부품(Recharts `PolarGrid`)이 축마다 색을 줄 수 없다. 영역색은 축 이름과 꼭짓점 점에만.
- 사다리 점수 구간의 램프: 곡선 아래를 칠하게 되어 "곡선 아래 칠하기 없음"과 부딪친다.
- 색감 프리셋: 대시보드에는 색감 설정이 없어 늘 종이(라이트·다크)다.

## Do's and Don'ts

### Do
- 색·크기·간격은 언제나 `var(--…)` 토큰으로. 하드코딩 hex는 이 문서 맨 위와 `global.css`에만.
- 글자 역할 7개로 끝낸다. 새 역할이 필요하면 이 문서부터 고친다.
- 숫자는 말로 한 번 풀어 준다("이번 주 평균보다 조금 좋아요").
- 새 화면을 만들기 전에 이 문서의 컴포넌트로 되는지 본다.

### Don't
- 카드 안에 카드, 그림자 쌓기, 그라디언트, 이모지 아이콘.
- `--hue`를 장식으로 쓰기(비서가 한 일이 아닌 곳에).
- 영역색으로 면 칠하기, 색만으로 뜻 전하기.
- 인라인 `style=`(CSP가 막는다), 화면별 CSS를 `_app` 밖에서 불러오기.

## Implementation notes

- 눌림은 전역 유틸리티 `.pressable`(scale .97, 150ms, 움직임 줄이기에서 꺼짐)을 버튼에 클래스로 단다.
- 영역색은 `data-area="career"` 같은 속성이 `--area`를 정하고, `.area-dot`이 8px 점을 그린다.
- 대시보드가 쓰는 이름은 `global.css`에 모두 있다: `--neutral`(= `--muted`), `--offline-bg`(= `--raised`),
  `--condition-dot`(= `--muted`, 바탕·표면·`--raised` 위 3:1 이상), `--radius-panel`, `--radius-control`(999px),
  `--gutter`, `--fs-nav`, `--measure`.
- 앱의 옛 `styles/tokens.css`·`styles/globals.css`는 `global.css` 사본으로 바뀌었다. 화면 CSS Modules는
  역할 토큰만 쓴다(`primitives.css.test.ts`, `contrast.test.ts`가 본다).

## Agent Prompt Guide

이 저장소에서 화면을 만들거나 고칠 때:
1. 이 문서를 먼저 읽고 맨 위 토큰과 컴포넌트 이름을 쓴다.
2. CSS Modules에서 `var(--ground)` 같은 역할 토큰만 쓴다. 새 토큰이 필요하면 이 문서와
   `web/shared/global.css`를 함께 고치고 `npm run sync:design`을 돌린다.
3. 대비 시험(`contrast.test.ts`)과 `check:csp`가 통과해야 한다.
4. 화면을 바꾸면 라이트·다크 스크린샷을 PR에 붙인다.

---
이 문서는 [Google Stitch DESIGN.md](https://github.com/google-labs-code/design.md) alpha 형식을 따른다.
