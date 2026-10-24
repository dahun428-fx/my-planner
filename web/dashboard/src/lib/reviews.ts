// When the next reviews come (SP3-4 11.2), worked out in the browser in Korean time (DU-05): the monthly
// ladder review is the last Sunday of the month, the quarterly areas review is in the quarter's last week,
// which is its last month's last Sunday (12/27 for 2026-Q4). Dates are logical `YYYY-MM-DD`.
import { REVIEW_TEXT } from "./labels";

const seoulDate = new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Seoul", year: "numeric", month: "2-digit", day: "2-digit" });

const pad = (n: number) => String(n).padStart(2, "0");
const ymd = (y: number, m: number, d: number) => `${y}-${pad(m)}-${pad(d)}`;

/** Today's date in Korea, whatever zone the device is in. */
export function seoulToday(now: Date = new Date()): string {
  const p: Record<string, string> = {};
  for (const part of seoulDate.formatToParts(now)) p[part.type] = part.value;
  return `${p.year}-${p.month}-${p.day}`;
}

/** The last Sunday of month `m` (1~12) of year `y`. */
export function lastSunday(y: number, m: number): string {
  const last = new Date(Date.UTC(y, m, 0)); // day 0 of the next month
  return ymd(y, m, last.getUTCDate() - last.getUTCDay());
}

const parts = (day: string) => day.split("-").map(Number) as [number, number, number];

/** The first last-Sunday on or after `today` among the months `months` picks (the review day itself counts). */
function nextLastSunday(today: string, isReviewMonth: (m: number) => boolean): string {
  let [y, m] = parts(today);
  for (;;) {
    if (isReviewMonth(m)) {
      const day = lastSunday(y, m);
      if (day >= today) return day;
    }
    m += 1;
    if (m > 12) {
      m = 1;
      y += 1;
    }
  }
}

/** The next monthly review (first ladder score). */
export const nextMonthlyReview = (today: string) => nextLastSunday(today, () => true);

/** The next quarter-end review (area scores). */
export const nextQuarterReview = (today: string) => nextLastSunday(today, (m) => m % 3 === 0);

/** `2026-10-25` as "10월 25일(일)". */
export function reviewDayLabel(day: string): string {
  const [y, m, d] = parts(day);
  return REVIEW_TEXT.day(m, d, REVIEW_TEXT.weekdays[new Date(Date.UTC(y, m - 1, d)).getUTCDay()]);
}
