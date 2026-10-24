import { copy } from "./copy";

// Every time the app shows is Asia/Seoul, whatever the device zone is (spec 4.6, Review Focus 1).
export type KstStyle = "HH:mm" | "date" | typeof copy.dateStyle.monthDay | typeof copy.dateStyle.monthDayTime;

const kst = new Intl.DateTimeFormat("en-US", {
  timeZone: "Asia/Seoul",
  year: "numeric",
  month: "numeric",
  day: "numeric",
  hour: "numeric",
  minute: "numeric",
  hourCycle: "h23",
});

const pad = (n: number) => String(n).padStart(2, "0");

export function formatKst(iso: string, style: KstStyle): string {
  const p: Record<string, number> = {};
  for (const part of kst.formatToParts(new Date(iso))) {
    if (part.type !== "literal") p[part.type] = Number(part.value);
  }
  const hhmm = `${pad(p.hour)}:${pad(p.minute)}`;
  switch (style) {
    case "HH:mm":
      return hhmm;
    case "date":
      return `${p.year}-${pad(p.month)}-${pad(p.day)}`;
    case copy.dateStyle.monthDay:
      return copy.dateParts.monthDay(p.month, p.day);
    case copy.dateStyle.monthDayTime:
      return `${copy.dateParts.monthDay(p.month, p.day)} ${hhmm}`;
  }
}

// Calendar arithmetic on a logical date (YYYY-MM-DD). No time zone is involved.
export function addDays(date: string, n: number): string {
  const [y, m, d] = date.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d + n)).toISOString().slice(0, 10);
}

export function relativeChecked(iso: string, now: number): string {
  const minutes = Math.floor((now - Date.parse(iso)) / 60_000);
  return minutes < 1 ? copy.settings.checkedJustNow : copy.settings.checkedMinutesAgo(minutes);
}

// A KST wall-clock date + "HH:mm" as UTC ISO without milliseconds ("2026-10-25" + "14:00" -> "2026-10-25T05:00:00Z").
// Korea has no daylight saving, so +09:00 is exact whatever the device zone is.
export function kstToUtcIso(date: string, hhmm: string): string {
  return new Date(`${date}T${hhmm}:00+09:00`).toISOString().replace(".000Z", "Z");
}

// The BE counts the hours before this one as the previous day (clock.py `logical_date`, default
// `day_boundary` in config.py: time(4, 0)). The API does not expose the setting, so it is fixed here.
export const DAY_BOUNDARY_HOUR = 4;

/** The BE's logical date (YYYY-MM-DD) of an instant: Seoul wall time, hours before 04:00 count as the day before. */
export function logicalDateOf(iso: string): string {
  const date = formatKst(iso, "date");
  const time = formatKst(iso, "HH:mm");
  return Number(time.slice(0, 2)) < DAY_BOUNDARY_HOUR ? addDays(date, -1) : date;
}
