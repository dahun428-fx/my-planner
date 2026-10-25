import type { CheckinSummary, Today } from "../api/types.gen";
import type { IconName } from "../components/icons";
import { copy } from "../lib/copy";
import { logicalDateOf } from "../lib/time";

// SP9 9.5 퀵 칩: 입력창 위 고정 칩 4개와, 때에 맞는 칩 1개(맨 앞). 판단 재료는 `GET /today`뿐이다(BE에 새 경로 없음).

export type ChipKey = keyof typeof copy.chat.chips;

export interface Chip {
  key: ChipKey;
  label: string;
  /** 누르면 내 말풍선으로 보내는 정해진 문장. */
  text: string;
  icon: IconName;
  /** 체크인·회고 칩: 그 회차(`checkin_id`)로 보낸다. 이때는 `resume_conversation_id`를 싣지 않는다(Review Focus 5). */
  checkinId?: number;
}

const chip = (key: ChipKey, icon: IconName, checkinId?: number): Chip => ({
  key,
  icon,
  ...copy.chat.chips[key],
  ...(checkinId === undefined ? {} : { checkinId }),
});

export const FIXED_CHIPS: readonly Chip[] = [chip("todo", "todos"), chip("event", "schedule"), chip("memo", "memo"), chip("today", "today")];

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
  const soon = today.events.some((e) => {
    if (e.all_day || e.start === null) return false;
    const ahead = Date.parse(e.start) - t;
    return ahead > 0 && ahead <= NEXT_EVENT_MS;
  });
  return soon ? chip("next", "schedule") : null;
}

/** 칩 줄 전체: 맨 앞 칩(있으면) + 고정 4개. `/today`를 못 받았으면 고정 4개만. */
export function quickChips(today: Today | null, now: Date): readonly Chip[] {
  const front = today ? frontChip(today, now) : null;
  return front ? [front, ...FIXED_CHIPS] : FIXED_CHIPS;
}
