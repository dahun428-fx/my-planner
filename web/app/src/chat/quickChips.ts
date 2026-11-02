import type { ChatRequestBody, CheckinSummary, Today } from "../api/types.gen";
import type { IconName } from "../components/icons";
import type { PictogramName } from "../components/pictograms.gen";
import { copy } from "../lib/copy";
import { copyPanel } from "../lib/copyPanel";
import { logicalDateOf } from "../lib/time";
import type { Agent } from "./agent";

// SP9 9.5 퀵 칩: 입력창 위 고정 칩 4개와, 때에 맞는 칩 1개(맨 앞). 판단 재료는 `GET /today`뿐이다(BE에 새 경로 없음).

/** SP15 11장: the life manager's three chips have their copy in copyPanel (the chat chunk's). */
export type ManagerChipKey = "manager_full" | "manager_week" | "manager_upload";
export type ChipKey = keyof typeof copy.chat.chips | ManagerChipKey;
/** `POST /chat`의 `chip`(SP9c 4.1). */
export type WireChip = NonNullable<ChatRequestBody["chip"]>;
/** 한 줄 쓰기 칩(SP9c 3): 할 일·일정·메모. */
export type WriteKey = keyof typeof copy.chat.write;

export interface Chip {
  key: ChipKey;
  label: string;
  /** 누르면 내 말풍선으로 보내는 정해진 문장(`send`). */
  text: string;
  icon: IconName;
  /** SP15: 아이콘 대신 그리는 픽토그램("전체 진단" = 상태창의 `status`). */
  pictogram?: PictogramName;
  /**
   * SP9c 3: `write`는 보내지 않고 입력창을 한 줄 쓰기로 바꾼다. `send`는 문장을 바로 보낸다.
   * SP15: `attach`는 보내지 않고 입력창의 사진 붙이기 메뉴를 연다("자료 올리기").
   */
  mode: "write" | "send" | "attach";
  /** 요청에 싣는 `chip`. 체크인·회고 칩은 없다. */
  wire?: WireChip;
  /** 체크인·회고 칩: 그 회차(`checkin_id`)로 보낸다. 이때는 `resume_conversation_id`를 싣지 않는다(Review Focus 5). */
  checkinId?: number;
  /** SP15: 지금은 누를 수 없는 칩(오늘 전체 진단을 이미 했다). 줄에 그대로 있고 흐리다. */
  disabled?: boolean;
}

export const isWriteKey = (key: string): key is WriteKey => key in copy.chat.write;
const WIRE = ["todo", "event", "memo", "today", "next", "mate_today", "mate_log", "mate_plan", "manager_full", "manager_week"] as const satisfies readonly WireChip[];
const isWire = (key: string): key is WireChip => (WIRE as readonly string[]).includes(key);

const chip = (key: keyof typeof copy.chat.chips, icon: IconName, checkinId?: number): Chip => ({
  key,
  icon,
  ...copy.chat.chips[key],
  mode: isWriteKey(key) ? "write" : "send",
  ...(isWire(key) ? { wire: key } : {}),
  ...(checkinId === undefined ? {} : { checkinId }),
});

export const FIXED_CHIPS: readonly Chip[] = [chip("todo", "todos"), chip("event", "schedule"), chip("memo", "memo"), chip("today", "today")];
/** SP12 5.7: 운동메이트 대화의 고정 3개. 때에 따라 바뀌는 칩은 없다. */
export const MATE_CHIPS: readonly Chip[] = [chip("mate_today", "today"), chip("mate_log", "memo"), chip("mate_plan", "todos")];

/** SP15 11장: 라이프 매니저 대화의 고정 3개. 글이 곧 보내는 문장이다(정해진 문장이 따로 없다). */
const managerChip = (key: ManagerChipKey, icon: IconName | { pictogram: PictogramName }, mode: Chip["mode"]): Chip => ({
  key,
  ...(typeof icon === "string" ? { icon } : { icon: "activity", pictogram: icon.pictogram }),
  label: copyPanel.chips[key],
  text: copyPanel.chips[key],
  mode,
  ...(isWire(key) ? { wire: key } : {}),
});
export const MANAGER_CHIPS: readonly Chip[] = [managerChip("manager_full", { pictogram: "status" }, "send"), managerChip("manager_week", "today", "send"), managerChip("manager_upload", "memo", "attach")];
// `GET /panel/budget`의 `full_diagnosis_ok`가 거짓: 그 칩은 "오늘은 이미 했어요"로 막힌다.
const FULL_DONE: Chip = { ...MANAGER_CHIPS[0], label: copyPanel.chips.fullDone, disabled: true };

/** "3시간 안에 시작하는 일정"(9.5, 15장 8번). 꼭 3:00 뒤는 든다. */
export const NEXT_EVENT_MS = 3 * 60 * 60_000;

const isWeeklyReview = (c: CheckinSummary) => c.loop === "review" && c.cadence === "week";

// 답하지 않았고 보낸 뒤 답장 창(`reply_until`) 안. 기기 시계가 BE보다 늦을 수 있어 보낸 시각과 지금은 견주지 않는다.
const openRun = (c: CheckinSummary, now: number) => c.state === "pending" && c.sent_at !== null && now < Date.parse(c.reply_until);

// 논리적 날짜(04:00 경계)의 요일이 일요일. 월요일 01:00은 아직 일요일이다.
function isSunday(now: Date, boundary: string | undefined): boolean {
  const [y, m, d] = logicalDateOf(now.toISOString(), boundary).split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d)).getUTCDay() === 0;
}

const newestFirst = (a: CheckinSummary, b: CheckinSummary) => ((a.sent_at ?? "") < (b.sent_at ?? "") ? 1 : -1);

/**
 * 맨 앞 칩(9.5): 위에서 처음 맞는 것.
 * (1) 답하지 않은 체크인 회차가 답장 창 안 → 체크인 하기. 일요일의 주간 회고는 (2)가 맡는다.
 * (2) 일요일이고 이번 주 회고가 열려 있음 → 이번 주 돌아보기(그 회고 회차로 보낸다).
 * (3) 3시간 안에 시작하는 일정 → 다음 일정 보기. 하루 종일 일정과 이미 시작한 일정은 뺀다.
 * 없으면 null(고정 4개만).
 */
export function frontChip(today: Today, now: Date): Chip | null {
  const t = now.getTime();
  const sunday = isSunday(now, today.day_boundary);
  const open = today.checkins.filter((c) => openRun(c, t)).sort(newestFirst);
  const run = open.find((c) => !(sunday && isWeeklyReview(c)));
  if (run) return chip("checkin", "check", run.id);
  const review = sunday ? open.find(isWeeklyReview) : undefined;
  if (review) return chip("review", "activity", review.id);
  const soon = (today.events ?? []).some((e) => {
    if (e.all_day || e.start === null) return false;
    const ahead = Date.parse(e.start) - t;
    return ahead > 0 && ahead <= NEXT_EVENT_MS;
  });
  return soon ? chip("next", "schedule") : null;
}

/**
 * 칩 줄 전체: 맨 앞 칩(있으면) + 고정 4개. `/today`를 못 받았으면 고정 4개만. 운동메이트는 고정 3개뿐.
 * 라이프 매니저도 고정 3개, `fullDiagnosisOk`가 거짓이면 "전체 진단"이 막힌다(모르면 누를 수 있다: BE가 다시 막는다).
 */
export function quickChips(today: Today | null, now: Date, agent: Agent = "secretary", opts: { fullDiagnosisOk?: boolean } = {}): readonly Chip[] {
  if (agent === "mate") return MATE_CHIPS;
  if (agent === "manager") return opts.fullDiagnosisOk === false ? [FULL_DONE, ...MANAGER_CHIPS.slice(1)] : MANAGER_CHIPS;
  const front = today ? frontChip(today, now) : null;
  return front ? [front, ...FIXED_CHIPS] : FIXED_CHIPS;
}
