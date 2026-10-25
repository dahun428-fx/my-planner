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
  // A device clock behind the BE's (or an unreadable time) reads as "just now", never "-3 minutes".
  const minutes = Math.max(0, Math.floor((now - Date.parse(iso)) / 60_000) || 0);
  return minutes < 1 ? copy.settings.checkedJustNow : copy.settings.checkedMinutesAgo(minutes);
}

// A KST wall-clock date + "HH:mm" as UTC ISO without milliseconds ("2026-10-25" + "14:00" -> "2026-10-25T05:00:00Z").
// Korea has no daylight saving, so +09:00 is exact whatever the device zone is.
export function kstToUtcIso(date: string, hhmm: string): string {
  return new Date(`${date}T${hhmm}:00+09:00`).toISOString().replace(".000Z", "Z");
}

// An older BE sends no `/today.day_boundary`; its default was 04:00 (config.py), so that stands in.
const DEFAULT_BOUNDARY = "04:00";
const boundaryOf = (boundary: string | undefined) => (boundary !== undefined && /^\d{2}:\d{2}$/.test(boundary) ? boundary : DEFAULT_BOUNDARY);

/**
 * The BE's logical date (YYYY-MM-DD) of an instant: Seoul wall time, minutes before `boundary` ("HH:MM",
 * `/today.day_boundary`) count as the day before.
 */
export function logicalDateOf(iso: string, boundary: string | undefined): string {
  const b = boundaryOf(boundary);
  const date = formatKst(iso, "date");
  return formatKst(iso, "HH:mm") < b ? addDays(date, -1) : date;
}
