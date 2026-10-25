// Screen words of the dashboard (spec 13.1, 13.2, appendix A). Kept here so one test can read them all.
import type { HealthRun, SkipReason } from "../api/types.gen";
import type { PictogramName } from "../components/pictograms.gen";

// Appendix A push titles; an unknown loop reads as the notice title.
export const LOOP_LABELS: Record<HealthRun["loop"], string> = {
  morning_brief: "아침 브리핑",
  evening_checkin: "저녁 체크인",
  review: "주간 회고",
  return: "다시 이어서",
};

export function loopLabel(loop: string): string {
  return (LOOP_LABELS as Record<string, string>)[loop] ?? "알림";
}

// Gap 10: short forms of docs/acceptance/sp1-checklist.md's meanings.
export const SKIP_REASON_LABELS: Record<SkipReason, string> = {
  late: "한계 시각 지남",
  merged_into_return: "복귀 인사로 합침",
  paused: "/pause 중",
  daily_cap: "하루 두뇌 호출 상한",
  auth: "로그인·결제 문제",
  rate_limit: "사용 한도",
};

export function skipLabel(reason: string | null): string {
  const shown = reason === null ? undefined : (SKIP_REASON_LABELS as Record<string, string>)[reason];
  return shown ? `건너뜀(${shown})` : "건너뜀";
}

// `interrupted` (the BE stopped while sending, SP1 5.1) was not sent either.
const STATUS_LABELS: Record<string, string> = {
  done: "보냄",
  pending: "예정",
  queued: "예정",
  running: "보내는 중",
  failed: "전송 안 됨",
  interrupted: "전송 안 됨",
};

export function runStatusLabel(run: Pick<HealthRun, "status" | "skip_reason">): string {
  if (run.status === "skipped") return skipLabel(run.skip_reason);
  return STATUS_LABELS[run.status] ?? "—";
}

const CHECKIN_LABELS: Record<string, string> = { answered: "답함", pending: "답 기다림", missed: "지나감" };

export function checkinLabel(state: string | null): string | null {
  return state === null ? null : (CHECKIN_LABELS[state] ?? null);
}

export const CHANNEL_LABELS: Record<string, string> = { app: "앱", telegram: "텔레그램" };
export const channelLabel = (c: string) => CHANNEL_LABELS[c] ?? c;

export const POLLING_LABELS: Record<string, string> = { running: "연결됨", down: "끊김", stopped: "멈춤" };
export const AUTH_LABELS: Record<string, string> = {
  ok: "정상",
  login: "다시 로그인 필요",
  billing: "결제 확인 필요",
  unknown: "확인 전",
};

// Common states (spec 13.1 table, verbatim).
export const STATE_TEXT = {
  offline: "BE가 켜지면 다시 보여 드릴게요.",
  unauthorized: "토큰이 맞지 않아요. 설정에서 다시 넣어 주세요.",
  rate_limited: "잠시 뒤에 다시 시도해 주세요.",
  safe_mode: "데이터베이스 점검이 필요해요. PC에서 README의 복구 절차를 따라 주세요.",
  broken: (code: string) => `BE가 응답했지만 이 화면을 그리지 못했어요 (${code}).`,
  openSettings: "설정 열기",
} as const;

// DU-02: the card in place of a screen while the BE does not answer. What to check, when this browser last
// heard from it, and that it keeps checking. "never" is a browser with no good answer on record.
export const OFFLINE_TEXT = {
  title: {
    never: "이 브라우저는 아직 노트북의 비서와 연결되지 않았어요.",
    before: "노트북의 비서가 지금 응답하지 않아요.",
  },
  lastSeen: (when: string, ago: string) => `마지막 응답 ${when} (${ago})`,
  lastNone: "이 브라우저에는 아직 응답 기록이 없어요.",
  lead: {
    never: "처음 연결할 때는 이 세 가지를 확인해 주세요.",
    before: "잠시 쉬고 있을 수 있어요. 이 세 가지를 확인해 주세요.",
  },
  checks: [
    "노트북이 켜져 있고 절전 상태가 아닌지",
    "이 기기에서 Tailscale이 켜져 있는지",
    "Chrome이라면 로컬 네트워크 접근을 허용했는지",
  ],
  checksLabel: "확인할 것",
  neverHint: "주소와 토큰도 설정에서 한 번 더 봐 주세요.",
  retry: (every: string) => `${every}마다 자동으로 다시 확인하고 있어요.`,
  every: (ms: number) => (ms >= 60_000 ? `${Math.round(ms / 60_000)}분` : `${Math.round(ms / 1000)}초`),
} as const;

// Relative time beside the last answer (DU-02).
export const TIME_TEXT = {
  justNow: "방금",
  minutesAgo: (n: number) => `${n}분 전`,
  hoursAgo: (n: number) => `${n}시간 전`,
  daysAgo: (n: number) => `${n}일 전`,
} as const;

export const BAND_TEXT = {
  on: (hhmmss: string) => `BE 켜짐 · ${hhmmss} 응답`,
  onNoTime: "BE 켜짐",
  off: (when: string | null) => `BE 꺼짐 · 마지막 응답 ${when ?? "기록 없음"}`,
  checking: "연결 확인 중",
  check: "연결 확인",
  none: "BE 연결 전",
  offShort: "BE 꺼짐",
} as const;

export const HEALTH_TEXT = {
  title: "비서 상태",
  version: (app: string, api: string, schema: number | null) => `my-planner ${app} · API ${api} · 스키마 ${schema ?? "—"}`,
  lastTick: (hhmm: string | null) => `마지막 tick ${hhmm ?? "—"}`,
  polling: "텔레그램 폴링",
  login: "Claude 로그인",
  noLimit: "사용 한도 없음",
  limitedUntil: (hhmm: string) => `사용 한도 ${hhmm}까지`,
  noPause: "멈춤 없음",
  pausedUntil: (when: string) => `${when}까지 멈춤`,
  primary: (primary: string, effective: string) => `주 통로 ${primary} (지금 ${effective})`,
  push: (n: number) => `푸시 구독 ${n}`,
  runsHeading: "오늘 회차",
  noRuns: "오늘 예정된 회차가 아직 없어요.",
  brainCalls: "두뇌 호출",
  proactive: "먼저 보낸 메시지",
  noWarnings: "최근 24시간 경고 없음",
  warnings: (total: number, parts: string) => `최근 24시간 경고·오류 ${total}${parts ? ` (${parts})` : ""}`,
} as const;

export const SETTINGS_TEXT = {
  title: "설정",
  intro: "BE 주소와 API 토큰은 이 브라우저에만 저장해요.",
  url: "BE 주소",
  urlHint: "https://노트북.tailnet.ts.net/api/v1",
  token: "API 토큰",
  check: "연결 확인",
  checking: "확인 중",
  saved: "저장했어요.",
  urlErrors: {
    not_https: "https 주소만 넣을 수 있어요.",
    out_of_range: "이 대시보드가 허용한 tailnet 주소가 아니에요.",
    invalid: "주소 형식이 맞지 않아요.",
  },
  tokenMissing: "토큰을 넣어 주세요.",
  tokenInvalid: "토큰에는 영문, 숫자, 기호만 들어가요.",
  // DU-04: where the two values come from. The address shape is a pattern, never a real machine name.
  help: {
    summary: "주소와 토큰은 어디서 찾나요?",
    urlTitle: "BE 주소",
    urlBody: "노트북에서 이 명령을 실행하면 나오는 주소예요.",
    urlCommand: "tailscale serve status",
    urlShape: "https://<기계>.<tailnet>.ts.net",
    urlShapeNote: "이런 모양이에요. 뒤에 /api/v1은 붙여도 되고 빼도 돼요.",
    tokenTitle: "API 토큰",
    tokenBody: "노트북에서 이 명령으로 새로 만들 수 있어요.",
    tokenCommand: "python -m my_planner gen-token",
    tokenEnv: "이미 만들어 두었다면 노트북 .env 파일의 API_TOKEN 줄에 있어요.",
  },
} as const;

export const NAV_TEXT = {
  brand: "my-planner",
  status: "비서 상태",
  tasks: "할 일",
  curve: "인생곡선",
  window: "상태창",
  settings: "설정",
  label: "화면",
} as const;

// (b) 할 일 + 컨디션, spec 13.3. Group names and the line shapes follow the Telegram `/today`, `/week` text.
export const TASKS_TEXT = {
  title: "할 일",
  tabs: { today: "오늘", week: "이번 주" },
  tabsLabel: "기간",
  today: (md: string, weekday: string) => `오늘 (${md} ${weekday})`,
  week: (start: string, end: string) => `이번 주 (${start}~${end})`,
  groups: { priority: "우선순위", scheduled: "일정", open: "열린 할 일" },
  weekPriorities: "우선순위",
  todayMark: "(오늘)",
  noTodos: "아직 비어 있어요.",
  emptyDay: "—",
  hint: "바꾸려면 텔레그램이나 운영 앱에서 말씀해 주세요.",
} as const;

export const CONDITION_TEXT = {
  title: (days: number) => `컨디션 지난 ${days}일`,
  head: (average: string, days: number) => `평균 ${average} · ${days}일 기록`,
  chart: (days: number, logged: number, average: string) => `컨디션 지난 ${days}일: ${logged}일 기록, 평균 ${average}`,
  empty: "저녁 체크인에서 컨디션을 기록하면 여기에 그려져요.",
  listLabel: "기록한 날",
  dayScore: (md: string, score: number) => `${md} 컨디션 ${score}`,
} as const;

// (d) 게임형 상태창, spec 13.5 and appendix A. XP and level only rise; a debuff is a signal with a quest.
export const STATUS_TEXT = {
  title: "상태창",
  level: (n: number) => `Lv. ${n}`,
  xp: (into: number, forNext: number) => `${into} / ${forNext} XP`,
  xpBar: (into: number, forNext: number) => `경험치 ${into} / ${forNext}`,
  hp: (score: number) => `HP ${score}/5`,
  hpNone: "HP 기록 없음",
  hpBar: (score: number | null) => (score === null ? "HP 기록 없음" : `HP ${score} / 5`),
  hpWhat: "오늘 컨디션",
  stats: (period: string | null) => (period ? `스탯 (${period})` : "스탯"),
  statsEmpty: "영역 점수는 분기 마지막 주 회고에서 함께 정해요.",
  statBar: (label: string, score: number | null) => (score === null ? `${label} 기록 없음` : `${label} ${score} / 10`),
  noScore: "—",
  olderPeriod: (period: string) => `(${period})`,
  debuff: (prev: string, score: number) => `↓ 디버프 (${prev} ${score})`,
  recovery: (quest: string) => `회복 퀘스트: ${quest} (15~30분)`,
  mainQuests: "메인 퀘스트 (이번 분기)",
  firstSteps: (done: number, total: number) => `첫 걸음 ${done}/${total}`,
  mainEmpty: "이번 분기 메인 퀘스트가 아직 없어요. 계획 모드(/plan)에서 함께 정할 수 있어요.",
  dailyQuests: "오늘의 퀘스트",
  daily: (title: string) => `${title} (15~30분)`,
  dailyEmpty: "오늘의 퀘스트는 첫 걸음이 생기면 나타나요.",
  take: "텔레그램이나 운영 앱에서 '그 퀘스트 할게'라고 말씀해 주세요.",
  titles: "칭호",
  titlesEmpty: "높은 때나 전환점을 곡선에 남기면 칭호가 생겨요.",
  recentXp: "최근 경험치",
  xpGain: (amount: number, label: string) => `+${amount} ${label}`,
  recentEmpty: "할 일, 체크인 답, 컨디션 기록, 쉬는 날 모두 경험치가 돼요.",
  // SP8 10.1, appendix A. Numbers with one decimal; nothing here compares with an earlier bonus.
  statSub: (base: number, bonus: number) => (bonus > 0 ? `바탕 ${base} · 요즘 +${bonus.toFixed(1)}` : `바탕 ${base}`),
  statSubNoBase: (bonus: number) => `요즘 +${bonus.toFixed(1)} · 분기 회고에서 점수를 정하면 더해져요`,
  recentHeading: "요즘 손이 간 영역",
  recentLine: (bonus: number) => `+${bonus.toFixed(1)}`,
  recentCounts: (c: { tasks: number; habit_checks: number; body_days: number }) =>
    `4주 동안 ${[
      c.tasks > 0 ? `할 일 ${c.tasks}개` : "",
      c.habit_checks > 0 ? `습관 ${c.habit_checks}번` : "",
      c.body_days > 0 ? `몸 기록 ${c.body_days}일` : "",
    ]
      .filter(Boolean)
      .join(" · ")}`,
  recentAreasEmpty: "4주 안에 끝낸 할 일이나 습관 체크가 생기면 여기에 보여요.",
  // SP8 10.1, appendix A: the moments panel is read only.
  momentsHeading: "이룬 순간",
  momentsFooter: "숨기거나 지우는 것은 운영 앱 상태창에서 할 수 있어요.",
  momentsEmpty: "하루가 끝나면 비서가 그날 해낸 일을 몇 줄로 남겨 둬요.",
  // SP8 10.1, appendix A: the body record line under health. A part with no value is left out; no warning when old.
  bodyLine: (b: { steps_avg_7: number | null; sleep_avg_7: number | null }) => {
    const parts: string[] = [];
    if (typeof b.steps_avg_7 === "number") parts.push(`지난 7일 걸음 평균 ${b.steps_avg_7.toLocaleString("ko-KR")}`);
    if (typeof b.sleep_avg_7 === "number")
      parts.push(`${typeof b.steps_avg_7 === "number" ? "" : "지난 7일 "}잠 평균 ${Math.floor(b.sleep_avg_7 / 60)}시간 ${b.sleep_avg_7 % 60}분`);
    // Nothing to say when neither average exists (a record older than a week): no line, no warning.
    return parts.length > 0 ? ["몸 기록", ...parts].join(" · ") : "";
  },
} as const;

const WEEKDAYS = ["일", "월", "화", "수", "목", "금", "토"] as const;

/** "10월 24일 (토)": the date head over a day's moments (SP8 appendix A). `date` is a calendar day, "YYYY-MM-DD". */
export function momentDay(date: string): string {
  const [y, m, d] = date.split("-").map(Number);
  return `${m}월 ${d}일 (${WEEKDAYS[new Date(Date.UTC(y, m - 1, d)).getUTCDay()]})`;
}

/** The name of each pictogram (spec 9.1), for the places one stands without a word beside it. */
export const PICTOGRAM_LABELS: Record<PictogramName, string> = {
  career: "커리어",
  finance: "경제",
  health: "건강",
  relationships: "관계",
  learning: "배움",
  quality_of_life: "삶의 질",
  high: "높은 때",
  low: "힘든 때",
  turning_point: "전환점",
  chapter: "챕터",
  condition: "컨디션",
  ladder: "사다리",
  level: "레벨",
  quest: "퀘스트",
  review: "회고",
  todo: "할 일",
  habit: "습관",
  memory: "기억",
  future: "5년 뒤",
  eye: "보임",
  eyeoff: "가림",
  assistant: "비서가 만듦",
  home: "한눈에",
  curve: "인생곡선",
  status: "상태창",
  list: "목록",
  estimate: "추정",
  settings: "설정",
};

// SP1 area order and names (the same as `/status` stat labels).
export const AREAS = ["career", "finance", "health", "relationships", "learning", "quality_of_life"] as const;
export type Area = (typeof AREAS)[number];
export const AREA_LABELS: Record<Area, string> = {
  career: "커리어",
  finance: "경제",
  health: "건강",
  relationships: "관계",
  learning: "배움",
  quality_of_life: "삶의 질",
};

// (c) 인생곡선, spec 13.4 and 8.3 (the reassurance table, verbatim). Nothing here judges a score.
export const CURVE_TEXT = {
  title: "인생곡선",
  zoomLabel: "확대",
  zooms: { day: "일", week: "주", month: "월", quarter: "분기", year: "년" },
  sensitive: "민감한 사건 보기",
  legendNow: "지금",
  legendFuture: "5년 뒤",
  legendCondition: "컨디션 (0~10으로 옮김)",
  chart: (from: string, to: string) => `인생곡선 ${from}~${to}`,
  dataList: "곡선의 값",
  ladderRow: (period: string, now: number | null, future: number | null) =>
    [`사다리 ${period}`, now !== null ? `지금 ${now}` : null, future !== null ? `5년 뒤 ${future}` : null].filter(Boolean).join(" · "),
  conditionRow: (bucket: string, average: number, days: number) => `컨디션 ${bucket} 평균 ${average.toFixed(1)} · ${days}일 기록`,
  chapterRow: (title: string, start: string, end: string | null) => `챕터 ${title} (${start}~${end ?? "지금"})`,
  kinds: { high: "높은 때", low: "힘든 때", turning_point: "전환점" },
  glyphs: { high: "▲", low: "▼", turning_point: "◆" },
  milestoneButton: (kind: string, date: string, title: string) => `${kind} ${date} ${title}`,
  estimate: "(추정)",
  sensitiveMark: "민감한 사건",
  close: "닫기",
  details: "사건 상세",
  areas: (latest: string, previous: string | null) => (previous ? `영역 (${latest}, 점선 ${previous.slice(5)})` : `영역 (${latest})`),
  areasTitle: "영역",
  areaRow: (label: string, now: number | null, prev: number | null, prevPeriod: string | null, down: boolean) =>
    `${label} ${now ?? "—"}${prev !== null && prevPeriod ? ` (${prevPeriod.slice(5)} ${prev})` : ""}${down ? " ↓" : ""}`,
  reassurance: "안심 보기",
  monthLabel: (period: string, sameYear: boolean) => {
    const [y, m] = period.split("-");
    return sameYear ? `${Number(m)}월` : `${y}년 ${Number(m)}월`;
  },
  remembered: (month: string, now: number) => `${month} 기억 ${now}`,
  daily: (scaled: number) => `하루하루 ${scaled.toFixed(1)}`,
  copy: {
    better: "기억보다 하루하루가 괜찮았던 달이에요",
    harder: "하루하루는 버거웠지만 한 달을 좋게 기억하는 달이에요",
    similar: "기억과 하루하루가 비슷했던 달이에요",
    few: "이 달은 컨디션 기록이 적어서 비교하지 않았어요",
  },
  moreMonths: (n: number) => `지난 달 ${n}개 더 보기`,
  empty: {
    events: "시드를 가져오거나 대화에서 사건을 남기면 여기에 그려져요.",
    reassurance: "사다리 점수와 컨디션 기록이 한 달 쌓이면 비교해 드릴게요.",
  },
  // DU-05: what comes next and on which day, in place of the 13.4 ladder and area lines. No counts of days.
  upcoming: {
    label: "곧 그려질 것",
    firstLadderMark: "첫 사다리",
    ladderMark: "사다리",
    areasMark: "영역 점수",
    firstLadder: (day: string) => `${day} 월말 회고에서 첫 사다리 점수를 여쭤볼게요.`,
    ladder: (day: string) => `${day} 월말 회고에서 사다리 점수를 여쭤볼게요.`,
    areas: (day: string) => `${day} 분기 회고에서 영역 점수를 함께 정해요.`,
  },
} as const;

// Review days (DU-05), for example "11월 29일(일)".
export const REVIEW_TEXT = {
  weekdays: ["일", "월", "화", "수", "목", "금", "토"],
  day: (m: number, d: number, weekday: string) => `${m}월 ${d}일(${weekday})`,
} as const;

// SP8 8.3, 8.4 and appendix A: the history tab of the life curve. Nothing here ranks or compares a chapter.
export const HISTORY_TEXT = {
  tabsLabel: "보기",
  tabs: { curve: "곡선", history: "히스토리" },
  subtitle: (chapters: number, events: number, sinceYear: number | null) =>
    `지금까지 걸어온 길 · 챕터 ${chapters}개 · 사건 ${events}개${sinceYear === null ? "" : ` · ${sinceYear}년부터`}`,
  filterLabel: "거르기",
  filters: { all: "전체", high: "높은 때", low: "힘든 때", turning_point: "전환점" },
  sort: { recent: "최근부터 ▾", oldest: "오래된 것부터 ▾" },
  ladderRemembered: (n: string) => `그때 사다리 ${n}`,
  ladderRecorded: (n: string) => `사다리 평균 ${n}`,
  eventCount: (n: number) => `사건 ${n}개`,
  estimate: "추정",
  estimateSketch: "기억으로 그린 시기예요.",
  assistantMade: "비서가 만듦",
  sensitive: "민감",
  more: (title: string, years: string) => `${title} · ${years} 더 보기`,
  noneOfKind: "이 시기에는 고른 종류의 사건이 없어요.",
  unassigned: "시기를 정하지 않은 사건",
  empty: "시드를 가져오거나 대화에서 사건을 남기면 여기에 쌓여요.",
  kindEstimate: (kind: string) => `${kind} · 추정`,
  hideSensitive: "민감한 사건 가림",
  hidden: (n: number, years: number[]) => `가려 둔 사건 ${n}개${years.length > 0 ? ` · ${years.map((y) => `${y}년`).join(", ")}` : ""}`,
  showHidden: "보기",
  hideAgain: "가리기",
  glance: {
    title: "한눈에 보는 지난 길",
    subtitle: "챕터마다 기억한 사다리 점수와 사건이에요. 점선은 기억으로 그린 시기예요.",
    tableCaption: "한눈에 보는 지난 길을 표로 본 것",
    chapter: "챕터",
    years: "해",
    ladder: "사다리",
    events: "사건",
    noLadder: "없음",
  },
  summary: {
    label: "옆 요약",
    highest: (title: string, ladder: string) => `가장 높았던 챕터 · ${title} · 사다리 ${ladder}`,
    turningPoints: (n: number, years: number[]) => `전환점 · ${n}번${years.length > 0 ? ` · ${years.map((y) => `${y}년`).join(", ")}` : ""}`,
    longest: (title: string, years: number) => `가장 길었던 챕터 · ${title} · ${years}년`,
    since: (year: number) => `기억과 기록 · ${year}년부터는 매일 기록으로 그려요`,
    help: "대화에서 나온 일을 사건 초안으로 만들어 두면, 확인 버튼을 눌러야 여기에 올라와요. 지난 챕터도 '이 시기 같이 정리하자'라고 말하면 돼요.",
  },
} as const;
