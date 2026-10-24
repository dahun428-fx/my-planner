# v2 컴포넌트 견본 (site.css 18장)

페이지 에이전트용 안내입니다. 아래 견본을 그대로 복사해 내용만 바꿉니다. 색은 모두 `site.css`의 토큰에서 옵니다. 페이지 안에 색 값(`#…`, `rgb()`)을 직접 쓰지 않습니다.

먼저 알아 둘 것:

- **그림 판(`.fig__body`)은 두 테마 모두 밝습니다.** 그래서 인라인 SVG 안에서는 `--diagram-*` 토큰을 쓰는 클래스(`d-*`, `c4-*`, `bpmn-*`, `uml-*`, `seq-*`)만 씁니다. `--ok` 같은 일반 의미색은 다크 테마에서 밝아져 판 위에서 안 읽히므로, SVG 안에서는 `d-ok`, `d-bad`, `d-warn`, `d-info`(=`--diagram-ok` 등)를 씁니다.
- **아이콘을 SVG 그림 안에 넣을 때**는 `<use>`에 크기를 주고 색 클래스를 붙입니다: `<use href="#i-phone" x="10" y="10" width="20" height="20" class="d-ic--accent"/>`. 진한 상자 위에서는 `d-ic--on`을 씁니다.
- **넓은 그림**은 `fig__body--wide`와 `style="--fig-min:900px"`로 판 안에서 가로로 스크롤합니다. 페이지 자체는 360px에서 가로로 넘치면 안 됩니다.
- **SVG에는 `width` 속성을 viewBox 폭과 같게 줍니다**(`<svg viewBox="0 0 860 420" width="860" …>`). 없으면 넓은 화면에서 그림이 판 폭까지 커져 글자가 지나치게 커집니다. 판보다 좁은 화면에서는 `max-width:100%`로 줄거나(`fig__body`), `--fig-min`까지 지키고 스크롤합니다(`fig__body--wide`).
- BPMN 메시지 흐름(점선)은 **서로 다른 풀 사이**에만 씁니다. 한 풀 안 레인 사이는 시퀀스 흐름(실선)입니다.
- **모든 그림에는 범례(`.legend`)와 한 문장 결론(`.fig__cap`)**을 붙입니다.
- 기존 v1 부품(`.fig`, `.legend`, `.phone`, `.msg`, `.kbd-grid`, `.mk`, `.pill.*`, `.dt`, `.kpis`, `.summary`, `.callout`, `ol.steps`, `details.more`, `.bars`, `.stack`)은 그대로 씁니다.

목차

1. 구현 상태 칩 `.pill.st`
2. 와이어프레임 틀: 폰 360 `.wf-phone`, 데스크톱 `.wf-desk`, 번호 콜아웃 `.mk`
3. SVG 공통: 화살촉 마커, 글자 테두리
4. C4 상자 `.c4-*`
5. BPMN 풀·레인 `.bpmn-*`
6. UML 상태 기계 `.uml-*`
7. 시퀀스 생명선 `.seq-*`
8. API 엔드포인트 카드 `.api`, 방식 알약 `.method`, 응답 코드 `.http`
9. 포털 전용: 읽는 순서 `ol.readpath`, 새 문서 표시 `.doccard__new`

---

## 1. 구현 상태 칩 `.pill.st`

색과 함께 앞 기호의 **모양**이 상태를 말합니다. 칩 글자는 줄바꿈하지 않습니다.

| `data-s` | 글자 | 앞 기호 |
|---|---|---|
| `done` | 구현됨 | 찬 원 |
| `partial` | 진행 중 | 반 찬 원 |
| `laptop` | 노트북 확인 대기 | 과녁(테 + 가운데 점) |
| `planned` | 계획 | 점선 원, 점선 테두리 |
| `deferred` | 미룸 | 가로 막대 |

```html
<span class="pill st" data-s="done">구현됨</span>
<span class="pill st" data-s="partial">진행 중</span>
<span class="pill st" data-s="laptop">노트북 확인 대기</span>
<span class="pill st" data-s="planned">계획</span>
<span class="pill st" data-s="deferred">미룸</span>
```

범례 한 줄 견본:

```html
<ul class="legend__list">
  <li><span class="legend__glyph"><span class="pill st" data-s="done">구현됨</span></span><span class="legend__term">main에 병합</span><span class="legend__desc">코드와 시험이 main에 있다</span></li>
</ul>
```

## 2. 와이어프레임 틀

저충실도 틀입니다. 실제 색이 아니라 자리와 위계를 보여 줍니다. 화면 요소에 번호 콜아웃(`.mk`)을 붙이고, 옆 표의 같은 번호 행과 `data-mk`로 잇습니다. `site.js`가 같은 `data-mk`를 가진 표식·요소·표 행을 함께 강조합니다.

### 2a. 화면 한 묶음 짜임 `.wf-spec`

```html
<div class="wf-spec" id="scr-app-today">                 <!-- 폰: 왼쪽 틀 360 + 오른쪽 표 -->
  <div>
    <!-- 틀 (2b 또는 2c) -->
    <p class="wf-cap"><span class="mono">SCR-APP-TODAY</span> 오늘 화면 · 기본 상태</p>
  </div>
  <div class="table-wrap">
    <table class="dt">
      <caption>SCR-APP-TODAY 요소</caption>
      <thead><tr><th class="w-min">#</th><th>요소</th><th>내용 · 규칙</th><th class="w-min">이벤트</th></tr></thead>
      <tbody>
        <tr id="today-c1" data-mk="t1"><td class="num"><a class="mk" href="#today-c1" data-mk="t1">1</a></td><td>날짜 머리</td><td>논리적 날짜(04:00 기준)</td><td>없음</td></tr>
      </tbody>
    </table>
  </div>
</div>
```

데스크톱 틀은 `class="wf-spec wf-spec--wide"`로 위에 틀, 아래에 표를 둡니다.

### 2b. 폰 틀 `.wf-phone` (운영 앱, 360px)

```html
<div class="wf-phone" style="--wf-h:620px">
  <div class="wf-phone__status"><span>9:41</span><span>5G</span></div>
  <div class="wf-appbar mk-host" data-mk="t1">
    <a class="mk" href="#today-c1" data-mk="t1">1</a>
    <span class="wf-appbar__title">10월 24일 (금)</span>
    <span class="wf-chip"><svg class="ic ic--sm" aria-hidden="true"><use href="#i-wifi-off"/></svg>오프라인</span>
  </div>
  <div class="wf-phone__body">
    <div class="wf-banner"><svg class="ic" aria-hidden="true"><use href="#i-warning"/></svg>노트북에 닿지 않아요. 마지막 스냅샷을 보여요.</div>
    <div class="wf-card mk-host" data-mk="t2">
      <a class="mk mk--right" href="#today-c2" data-mk="t2">2</a>
      <span class="wf-card__title"><svg class="ic" aria-hidden="true"><use href="#i-priority"/></svg>오늘의 우선순위</span>
      <span class="wf-check is-on">산책 20분</span>
      <span class="wf-check">보고서 초안 첫 문단</span>
    </div>
    <div class="wf-grid" style="--cols:2">
      <div class="wf-card"><span class="wf-label">컨디션</span><span class="wf-num">4</span></div>
      <div class="wf-box" style="--h:72px">차트 자리</div>
    </div>
    <span class="wf-line" style="--w:70%"></span>
    <div class="wf-row"><span class="wf-btn wf-btn--primary">확인</span><span class="wf-btn">나중에</span><span class="wf-btn wf-btn--ghost">더 보기</span></div>
    <div class="wf-input">비서에게 말하기…</div>
    <div class="wf-bubble wf-bubble--me">내일 오전에 치과 넣어 줘</div>
    <div class="wf-bubble wf-bubble--bot">넣었어요. ✓ 추가: 치과 (10/25 10:00)</div>
    <span class="wf-toast">바꿨어요 <b>되돌리기</b></span>
  </div>
  <div class="wf-sheet">시트 내용 (아래에서 올라오는 판)</div>   <!-- 필요할 때만 -->
  <nav class="wf-tabbar" style="--tabs:4" aria-label="앱 탭(그림)">
    <span class="wf-tab is-on"><svg class="ic" aria-hidden="true"><use href="#i-sun"/></svg>오늘</span>
    <span class="wf-tab"><svg class="ic" aria-hidden="true"><use href="#i-task"/></svg>할 일</span>
    <span class="wf-tab"><svg class="ic" aria-hidden="true"><use href="#i-habit"/></svg>습관</span>
    <span class="wf-tab"><svg class="ic" aria-hidden="true"><use href="#i-activity"/></svg>기록</span>
  </nav>
</div>
```

- 틀 높이는 `style="--wf-h:…"`(기본 600px). 폭은 최대 360px, 좁은 화면에서는 폭에 맞춰 줄어듭니다.
- 틀 안의 버튼·칩·체크는 그림입니다. `<button>`이 아니라 `<span>`으로 씁니다(포커스가 가지 않게).
- 탭 수는 `--tabs`, 격자 열 수는 `--cols`, 줄 길이는 `--w`, 빈 자리 높이는 `--h`.

틀 부품 목록:

| 클래스 | 뜻 |
|---|---|
| `.wf-appbar` / `.wf-appbar__title` | 화면 위 제목 줄 |
| `.wf-tabbar` / `.wf-tab` (`.is-on`) | 아래 탭 막대(폰) |
| `.wf-nav` (`.is-on`) | 왼쪽 메뉴 줄(데스크톱) |
| `.wf-card` / `.wf-card__title` / `.wf-card--dashed` | 카드, 비어 있는 카드 |
| `.wf-row` (`--between`) / `.wf-grid` | 가로 줄 / 격자 |
| `.wf-line` | 글 자리 막대(내용이 정해지지 않은 글) |
| `.wf-text` / `.wf-label` / `.wf-num` | 작은 글 / 꼬리표 / 큰 숫자 |
| `.wf-box` | 빗금 친 빈 자리(차트, 이미지) |
| `.wf-btn` (`--primary`, `--ghost`, `--block`) | 버튼 |
| `.wf-chip` (`.is-on`) | 칩, 고른 칩 |
| `.wf-input` | 입력 칸 |
| `.wf-check` (`.is-on`) | 체크 줄 |
| `.wf-sheet` | 아래 시트 |
| `.wf-toast` | 알림 줄(되돌리기 등) |
| `.wf-banner` | 경고 띠(오프라인 등) |
| `.wf-bubble--bot` / `.wf-bubble--me` | 대화 말풍선 |

### 2c. 데스크톱 틀 `.wf-desk` (대시보드)

넓은 틀은 `.wf-scroll` 안에 넣습니다. 판 안에서 가로로 스크롤하고, 페이지는 넘치지 않습니다.

```html
<div class="wf-spec wf-spec--wide" id="scr-dsh-curve">
  <div class="wf-scroll" tabindex="0" aria-label="가로로 스크롤되는 화면 그림">
    <div class="wf-desk" style="--wf-min:900px; --wf-h:460px">
      <div class="wf-desk__chrome"><span class="wf-desk__dots"><i></i><i></i><i></i></span><span class="wf-desk__url">my-planner-dashboard-seven.vercel.app/curve</span></div>
      <div class="wf-desk__body">
        <div class="wf-desk__side">
          <span class="wf-nav"><svg class="ic" aria-hidden="true"><use href="#i-heartbeat"/></svg>비서 상태</span>
          <span class="wf-nav is-on"><svg class="ic" aria-hidden="true"><use href="#i-curve"/></svg>인생 곡선</span>
        </div>
        <div class="wf-desk__main">
          <div class="wf-row wf-row--between mk-host" data-mk="d1">
            <a class="mk" href="#curve-c1" data-mk="d1">1</a>
            <span class="wf-appbar__title">인생 곡선</span>
            <span class="wf-row"><span class="wf-chip is-on">1년</span><span class="wf-chip">5년</span><span class="wf-chip">전체</span></span>
          </div>
          <div class="wf-box" style="--h:240px">곡선 차트 자리</div>
        </div>
      </div>
    </div>
  </div>
  <p class="wf-cap"><span class="mono">SCR-DSH-CURVE</span> 인생 곡선 · 1년 보기</p>
  <div class="table-wrap"><!-- 요소 표 (2a와 같음) --></div>
</div>
```

- 기본 최소 폭은 720px(`--wf-min`), 왼쪽 메뉴 폭은 `--wf-side`(기본 180px). 메뉴가 없는 화면은 `.wf-desk__body--full`.

### 2d. 번호 콜아웃 `.mk`

| 쓰는 법 | 위치 |
|---|---|
| `<a class="mk" …>` | 요소 왼쪽 위 |
| `<a class="mk mk--right" …>` | 오른쪽 위 |
| `<a class="mk mk--bottom" …>` | 왼쪽 아래 (`mk--right`와 같이 쓰면 오른쪽 아래) |
| `<a class="mk mk--mid" …>` | 왼쪽 가운데 |

부모에 `class="mk-host" data-mk="키"`를 주고, 표식과 표 행에도 같은 `data-mk`를 줍니다. 표식 `href`는 표 행의 `id`를 가리킵니다.

상태(빈 화면, 로딩, 오류, 오프라인)는 화면마다 작은 틀을 더 그리거나 표로 적습니다. 이벤트 표는 `트리거 → 동작 → 결과 화면` 세 칸으로 씁니다.

## 3. SVG 공통

모든 인라인 SVG에 `role="img"`와 `aria-label`(그림이 말하는 것 한 문장)을 줍니다. 화살촉은 그림마다 `<defs>`에 둡니다. **id는 페이지 안에서 겹치지 않게** 그림 번호를 붙입니다(`ah-f3`).

```html
<figure class="fig">
  <figcaption class="fig__head"><span class="fig__no"></span><span class="fig__title">그림 제목</span><span class="fig__std">C4 · Container</span></figcaption>
  <div class="fig__body fig__body--wide" style="--fig-min:860px">
    <svg viewBox="0 0 860 420" role="img" aria-label="그림이 말하는 것 한 문장">
      <defs>
        <marker id="ah-f3" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
          <path d="M0 0L10 5L0 10z" class="d-head"/>
        </marker>
        <marker id="ah-f3-open" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse">
          <path d="M1 1L9 5L1 9" fill="none" class="d-line" stroke-width="1.4"/>
        </marker>
      </defs>
      <!-- 내용 -->
    </svg>
  </div>
  <div class="fig__body fig__body--tight" style="background:var(--surface)"><!-- 선택: .legend 를 판 아래에 --></div>
  <p class="fig__cap"><b>결론:</b> 한 문장.</p>
</figure>
```

| 클래스 | 뜻 |
|---|---|
| `d-head` | 화살촉 채움 |
| `d-halo` | 선 위에 놓인 글자에 판 색 테두리(읽히게) |
| `d-bold` | 굵은 글자 |
| `d-ok` `d-bad` `d-warn` `d-info` (채움) / `d-ok-s` … (선) | 판 위 의미색 |
| `d-annot` / `d-annot-ink` | 그림 안 번호 원 / 그 위 글자 |
| `d-dash` | 점선 |
| `d-ic` / `d-ic--accent` / `d-ic--on` | `<use>` 아이콘 색: 잉크 / 강조 / 진한 상자 위 |
| (v1) `d-text` `d-text-sm` `d-mono` `d-line` `d-rule` `d-box` `d-box-2` `d-plain` `d-accent` `d-accent-s` | 기본 글자·선·상자 |

그림 안 번호 원 견본: `<circle cx="20" cy="20" r="10" class="d-annot"/><text x="20" y="24" text-anchor="middle" class="d-mono d-annot-ink d-bold">1</text>`

## 4. C4 상자 `.c4-*`

C4 표기: 사람·시스템은 진한 면(글자는 `c4-on-dark`), 컨테이너는 옅은 면, 컴포넌트는 흰 면, 외부 시스템은 회색 점선, 경계는 점선 틀입니다. 상자마다 이름 · `[기술]` · 한 줄 설명 세 줄을 씁니다.

```html
<svg viewBox="0 0 640 300" role="img" aria-label="사용자가 운영 앱으로 BE API를 부르고, BE가 SQLite에 쓴다">
  <defs><marker id="ah-c4" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" class="d-head"/></marker></defs>
  <!-- 사람 -->
  <g class="c4-on-dark">
    <circle cx="80" cy="34" r="16" class="c4-person"/>
    <rect x="20" y="52" width="120" height="70" rx="14" class="c4-person"/>
    <text x="80" y="80" class="c4-name">Dahun</text>
    <text x="80" y="98" class="c4-tech">[사람]</text>
  </g>
  <!-- 경계 -->
  <rect x="200" y="14" width="420" height="272" rx="8" class="c4-boundary"/>
  <text x="212" y="32" class="c4-boundary__label">노트북 · tailnet 안</text>
  <!-- 컨테이너 -->
  <rect x="230" y="50" width="170" height="86" rx="6" class="c4-container"/>
  <text x="315" y="76" class="c4-name">BE (my-planner)</text>
  <text x="315" y="94" class="c4-tech">[Python 3.12, aiohttp]</text>
  <text x="315" y="114" class="c4-desc">하네스 · API · 회차</text>
  <!-- 데이터베이스(원통) -->
  <path d="M440 70v60c0 7 22 12 50 12s50-5 50-12V70" class="c4-db"/>
  <ellipse cx="490" cy="70" rx="50" ry="12" class="c4-db"/>
  <text x="490" y="106" class="c4-name">planner.db</text>
  <text x="490" y="124" class="c4-tech">[SQLite]</text>
  <!-- 외부 시스템 -->
  <rect x="230" y="190" width="170" height="70" rx="6" class="c4-ext"/>
  <text x="315" y="220" class="c4-name">텔레그램</text>
  <text x="315" y="238" class="c4-tech">[외부 · Bot API]</text>
  <!-- 관계 -->
  <path d="M140 87H228" class="c4-rel" marker-end="url(#ah-c4)"/>
  <text x="184" y="80" class="c4-rel__label">HTTPS /api/v1</text>
  <path d="M400 93H438" class="c4-rel" marker-end="url(#ah-c4)"/>
  <path d="M315 136V188" class="c4-rel c4-rel--async" marker-end="url(#ah-c4)"/>
</svg>
```

| 클래스 | 뜻 |
|---|---|
| `c4-person` / `c4-system` | 진한 면(사람·우리 시스템). 묶음 `<g class="c4-on-dark">` 안에 글자 |
| `c4-container` / `c4-db` | 컨테이너 / 데이터 저장소(원통) |
| `c4-component` | 컴포넌트(흰 면) |
| `c4-ext` | 외부 시스템(회색 점선) |
| `c4-boundary` / `c4-boundary__label` | 경계 틀 / 그 이름 |
| `c4-name` / `c4-tech` / `c4-desc` | 이름 / [기술] / 설명 (모두 가운데 정렬) |
| `c4-rel` (`--async`) / `c4-rel__label` | 관계선(비동기는 점선) / 관계 글 |

범례 견본(HTML):

```html
<div class="legend"><p class="legend__title">범례</p>
  <div class="chip-row">
    <span class="c4-key" data-c4="person">사람</span><span class="c4-key" data-c4="system">시스템</span>
    <span class="c4-key" data-c4="container">컨테이너</span><span class="c4-key" data-c4="component">컴포넌트</span>
    <span class="c4-key" data-c4="ext">외부 시스템</span><span class="c4-key" data-c4="boundary">경계</span>
  </div>
</div>
```

## 5. BPMN 풀·레인 `.bpmn-*`

레인은 가로 띠, 왼쪽에 세로 이름 띠(폭 32)를 둡니다. 레인 높이는 110 안팎. 작업은 둥근 사각형(rx 10), 게이트웨이는 마름모입니다. 범례는 v1의 `.bpmn-chip` + 아이콘(`i-bpmn-*`)을 그대로 씁니다.

```html
<svg viewBox="0 0 900 260" role="img" aria-label="아침 브리핑: 타이머가 울리면 하네스가 두뇌를 부르고, 사용자는 텔레그램에서 답한다">
  <defs><marker id="ah-bp" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" class="d-head"/></marker></defs>
  <!-- 풀 -->
  <rect x="1" y="1" width="898" height="258" class="bpmn-pool"/>
  <!-- 레인 1 -->
  <rect x="1" y="1" width="898" height="128" class="bpmn-lane"/>
  <rect x="1" y="1" width="32" height="128" class="bpmn-lane__head"/>
  <text class="bpmn-lane__text" transform="translate(17 65) rotate(-90)">사용자</text>
  <!-- 레인 2 -->
  <rect x="1" y="129" width="898" height="130" class="bpmn-lane bpmn-lane--alt"/>
  <rect x="1" y="129" width="32" height="130" class="bpmn-lane__head"/>
  <text class="bpmn-lane__text" transform="translate(17 194) rotate(-90)">하네스</text>
  <!-- 타이머 시작 이벤트 -->
  <circle cx="80" cy="194" r="16" class="bpmn-timer"/><circle cx="80" cy="194" r="12" class="bpmn-timer"/>
  <path d="M80 186v8l5 3" class="d-line" stroke-width="1.5" stroke-linecap="round"/>
  <text x="80" y="230" text-anchor="middle" class="bpmn-label">09:00</text>
  <!-- 작업 -->
  <rect x="130" y="169" width="140" height="50" rx="10" class="bpmn-task"/>
  <text x="200" y="194" class="bpmn-task__text">브리핑 만들기</text>
  <!-- 사람 작업 -->
  <rect x="330" y="40" width="140" height="50" rx="10" class="bpmn-task bpmn-task--user"/>
  <text x="400" y="65" class="bpmn-task__text">초안 확인</text>
  <!-- 배타 게이트웨이 -->
  <path d="M560 169l25 25-25 25-25-25z" class="bpmn-gw"/>
  <path d="M552 186l16 16M568 186l-16 16" class="bpmn-gw__mark"/>
  <text x="560" y="236" text-anchor="middle" class="bpmn-label">답 있음?</text>
  <!-- 끝 이벤트 -->
  <circle cx="680" cy="194" r="16" class="bpmn-end"/>
  <!-- 흐름 -->
  <path d="M96 194H128" class="bpmn-flow" marker-end="url(#ah-bp)"/>
  <path d="M270 180C300 180 300 65 328 65" class="bpmn-flow" marker-end="url(#ah-bp)"/>
  <path d="M470 65C520 65 560 100 560 167" class="bpmn-flow" marker-end="url(#ah-bp)"/>
  <path d="M585 194H662" class="bpmn-flow" marker-end="url(#ah-bp)"/>
  <text x="620" y="186" text-anchor="middle" class="bpmn-label">예</text>
</svg>
```

| 클래스 | 뜻 |
|---|---|
| `bpmn-pool` | 풀 바깥 틀 |
| `bpmn-lane` (`--alt`) / `bpmn-lane__head` / `bpmn-lane__text` | 레인 띠(번갈아 옅은 면) / 왼쪽 이름 띠 / 세로 이름 |
| `bpmn-task` (`--user`, `--sub`) / `bpmn-task__text` | 작업(사람 작업은 옅은 면, 하위 프로세스는 아래에 [+]를 따로) / 글 |
| `bpmn-start` / `bpmn-end` / `bpmn-timer` / `bpmn-inter` | 시작(초록 얇은 원) / 끝(빨강 굵은 원) / 타이머(원 두 겹) / 중간 이벤트(원 두 겹) |
| `bpmn-gw` / `bpmn-gw__mark` | 게이트웨이 마름모 / 안쪽 표시(X 배타, + 병렬) |
| `bpmn-flow` / `bpmn-msg` | 시퀀스 흐름(실선) / 메시지 흐름(점선) |
| `bpmn-data` / `bpmn-label` | 데이터 객체 / 흐름 위 글(조건 등) |

## 6. UML 상태 기계 `.uml-*`

상태는 둥근 사각형(rx 12). 이름 칸과 활동 칸을 가는 선(`uml-state__div`)으로 나눕니다. 전이 글은 `이벤트 [조건] / 동작` 순서로 씁니다.

```html
<svg viewBox="0 0 620 200" role="img" aria-label="할 일은 초안에서 확정되어 열림이 되고, 완료되거나 빠진다">
  <defs><marker id="ah-st" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" class="d-head"/></marker></defs>
  <circle cx="30" cy="70" r="9" class="uml-initial"/>
  <rect x="70" y="40" width="130" height="62" rx="12" class="uml-state"/>
  <text x="135" y="62" class="uml-state__name">draft</text>
  <path d="M70 72H200" class="uml-state__div"/>
  <text x="135" y="90" class="uml-state__act">entry / 버튼 보이기</text>
  <rect x="290" y="40" width="130" height="62" rx="12" class="uml-state uml-state--active"/>
  <text x="355" y="76" class="uml-state__name">open</text>
  <rect x="480" y="40" width="110" height="62" rx="12" class="uml-state uml-state--final"/>
  <text x="535" y="76" class="uml-state__name">done</text>
  <circle cx="535" cy="160" r="11" class="uml-final-ring"/><circle cx="535" cy="160" r="6" class="uml-final-dot"/>
  <path d="M39 70H68" class="uml-trans" marker-end="url(#ah-st)"/>
  <path d="M200 71H288" class="uml-trans" marker-end="url(#ah-st)"/>
  <text x="244" y="62" text-anchor="middle" class="uml-trans__label">confirm_tasks</text>
  <path d="M420 71H478" class="uml-trans" marker-end="url(#ah-st)"/>
  <path d="M480 90C440 130 400 120 380 104" class="uml-trans uml-trans--undo" marker-end="url(#ah-st)"/>
  <text x="430" y="132" text-anchor="middle" class="uml-trans__guard">undo [5분 안]</text>
  <path d="M535 102V147" class="uml-trans" marker-end="url(#ah-st)"/>
</svg>
```

| 클래스 | 뜻 |
|---|---|
| `uml-state` (`--active`, `--final`) | 상태 / 주된 상태(옅은 면) / 닫힌 상태(회색) |
| `uml-state__name` / `uml-state__div` / `uml-state__act` | 이름 / 칸 나눔 선 / entry·do·exit 활동 |
| `uml-initial` | 시작 상태(찬 원, r 9) |
| `uml-final-ring` + `uml-final-dot` | 끝 상태(테 + 찬 원) |
| `uml-choice` | 선택 마름모 |
| `uml-trans` (`--undo`) / `uml-trans__label` / `uml-trans__guard` | 전이(되돌리기는 남빛 점선) / 이벤트 글 / [조건] 글 |

## 7. 시퀀스 생명선 `.seq-*`

참여자 상자는 위에(높이 40), 생명선은 그 아래 점선입니다. 참여자 간격은 150~170, 메시지 간격은 34~40을 권합니다. 메시지 앞에 번호(`seq-msg__no`)를 붙이고, 같은 번호로 아래 표에서 설명합니다.

```html
<svg viewBox="0 0 600 300" role="img" aria-label="앱이 /chat을 부르면 BE가 두뇌를 열고 글 조각을 스트리밍으로 돌려준다">
  <defs>
    <marker id="ah-sq" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" class="d-head"/></marker>
    <marker id="ah-sq-open" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse"><path d="M1 1L9 5L1 9" fill="none" class="d-line" stroke-width="1.4"/></marker>
  </defs>
  <!-- 참여자 3 (x = 90, 300, 510) -->
  <rect x="30" y="10" width="120" height="40" rx="6" class="seq-actor"/><text x="90" y="30" class="seq-actor__text">운영 앱</text>
  <rect x="240" y="10" width="120" height="40" rx="6" class="seq-actor"/><text x="300" y="30" class="seq-actor__text">BE API</text>
  <rect x="450" y="10" width="120" height="40" rx="6" class="seq-actor seq-actor--ext"/><text x="510" y="30" class="seq-actor__text">두뇌</text>
  <path d="M90 50V290M300 50V290M510 50V290" class="seq-life"/>
  <!-- 활성 막대 -->
  <rect x="294" y="80" width="12" height="150" class="seq-act"/>
  <!-- 메시지 -->
  <path d="M90 80H292" class="seq-msg" marker-end="url(#ah-sq)"/>
  <text x="191" y="74" class="seq-msg__text"><tspan class="seq-msg__no">1 </tspan>POST /api/v1/chat</text>
  <path d="M306 120H508" class="seq-msg seq-msg--async" marker-end="url(#ah-sq-open)"/>
  <text x="407" y="114" class="seq-msg__text"><tspan class="seq-msg__no">2 </tspan>query()</text>
  <!-- 반복 조각 -->
  <rect x="60" y="140" width="480" height="70" class="seq-frame"/>
  <path d="M60 140h46v14l-6 6H60z" class="seq-frame__tag"/>
  <text x="66" y="153" class="seq-frame__tagtext">loop</text>
  <text x="116" y="153" class="seq-frame__guard">[글 조각마다]</text>
  <path d="M292 185H92" class="seq-msg seq-msg--reply" marker-end="url(#ah-sq)"/>
  <text x="191" y="179" class="seq-msg__text"><tspan class="seq-msg__no">3 </tspan>SSE text-delta</text>
  <!-- 메모 -->
  <rect x="330" y="240" width="200" height="34" class="seq-note"/>
  <text x="340" y="261" class="seq-note__text">통로별 두뇌 줄은 하나</text>
</svg>
```

| 클래스 | 뜻 |
|---|---|
| `seq-actor` (`--ext`) / `seq-actor__text` / `seq-actor__sub` | 참여자 상자(외부는 점선) / 이름 / 작은 부제 |
| `seq-life` | 생명선(점선) |
| `seq-act` | 활성 막대(폭 12) |
| `seq-msg` / `seq-msg--reply` / `seq-msg--async` | 동기 호출(찬 화살촉) / 응답(점선) / 비동기(파랑, 열린 화살촉 `ah-…-open`) |
| `seq-msg__text` / `seq-msg__no` | 메시지 글 / 번호 |
| `seq-frame` / `seq-frame__tag` / `seq-frame__tagtext` / `seq-frame__guard` / `seq-frame__div` | 조각 틀(alt·opt·loop) / 왼쪽 위 꼬리표 / 꼬리표 글 / [조건] / alt 칸 나눔 점선 |
| `seq-note` / `seq-note__text` | 메모 |

## 8. API 엔드포인트 카드 `.api`

OpenAPI 표처럼 한 엔드포인트에 카드 하나입니다. 경로의 변수는 `api__param`으로 칠합니다. 토큰 값, 호스트 이름은 쓰지 않습니다(`<기계>.<tailnet>.ts.net`).

```html
<div class="api-list">
  <article class="api" id="api-get-today">
    <header class="api__head">
      <span class="method" data-m="GET">GET</span>
      <code class="api__path">/api/v1/today</code>
      <span class="api__tags">
        <span class="api-tag"><svg class="ic" aria-hidden="true"><use href="#i-token"/></svg>토큰 필요</span>
        <span class="api-tag"><svg class="ic" aria-hidden="true"><use href="#i-phone"/></svg>운영 앱</span>
      </span>
    </header>
    <div class="api__body">
      <p class="api__desc">오늘 화면에 필요한 것을 한 번에 돌려줍니다.</p>
      <dl class="api__meta">
        <dt>호출자</dt><dd>운영 앱, 대시보드</dd>
        <dt>응답</dt><dd><span class="http" data-c="2xx">200</span> <span class="http" data-c="4xx">401</span> <span class="http" data-c="5xx">503</span></dd>
        <dt>원천</dt><dd><code>src/my_planner/api/read.py</code></dd>
      </dl>
      <div class="table-wrap"><table class="dt dt--narrow"><caption>응답 필드</caption>
        <thead><tr><th>필드</th><th>타입</th><th>뜻</th></tr></thead>
        <tbody><tr><td class="code">date</td><td class="code">string</td><td>논리적 날짜</td></tr></tbody>
      </table></div>
      <pre class="code">{ "date": "2026-10-24", "priorities": [] }</pre>
    </div>
  </article>
  <article class="api" id="api-delete-push">
    <header class="api__head"><span class="method" data-m="DELETE">DELETE</span><code class="api__path">/api/v1/push/subscriptions/<span class="api__param">{id}</span></code></header>
    <div class="api__body"><p class="api__desc">…</p></div>
  </article>
</div>
```

| 클래스 | 뜻 |
|---|---|
| `.method[data-m="GET|POST|PUT|PATCH|DELETE|SSE"]` | 방식 알약(파랑·초록·황토·황토·빨강·남빛). 글자가 뜻을 말한다 |
| `.method.method--tool` | 두뇌 도구 이름 앞 꼬리표(`<span class="method method--tool">TOOL</span>`) |
| `.api__head` / `.api__path` / `.api__param` / `.api__tags` | 머리 / 경로 / 경로 변수 / 오른쪽 꼬리표 묶음 |
| `.api__body` / `.api__desc` / `.api__meta` | 본문 / 설명 / 정의 목록(dt·dd) |
| `.http[data-c="2xx|3xx|4xx|5xx"]` | 응답 코드 칩 |
| `.api-tag` | 인증·통로 꼬리표(아이콘 + 글) |
| `.api-list` | 카드 세로 묶음 |

## 9. 포털 전용

```html
<ol class="readpath">
  <li><span class="readpath__doc"><svg class="ic" aria-hidden="true"><use href="#i-doc-requirements"/></svg><a href="requirements.html">요구사항 정의서</a></span>
      <span class="readpath__why">무엇을 왜 만드는지.</span><span class="readpath__time">10분</span></li>
</ol>
```

새 문서 표시: `<span class="doccard__new">NEW</span>` (doccard 이름 옆). 시스템 지도 그림은 `<figure class="fig sysmap">`.
