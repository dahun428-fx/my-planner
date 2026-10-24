// Every time on screen is Korean time, whatever zone the device is in (spec 13.1). The API sends UTC.
import { TIME_TEXT } from "./labels";

export type KstStyle = "HH:mm" | "HH:mm:ss" | "M/D" | "M/D HH:mm";

const kst = new Intl.DateTimeFormat("en-US", {
  timeZone: "Asia/Seoul",
  month: "numeric",
  day: "numeric",
  hour: "numeric",
  minute: "numeric",
  second: "numeric",
  hourCycle: "h23",
});

const pad = (n: number) => String(n).padStart(2, "0");

export function formatKst(iso: string, style: KstStyle): string {
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return "—";
  const p: Record<string, number> = {};
  for (const part of kst.formatToParts(new Date(t))) {
    if (part.type !== "literal") p[part.type] = Number(part.value);
  }
  const hhmm = `${pad(p.hour)}:${pad(p.minute)}`;
  switch (style) {
    case "HH:mm":
      return hhmm;
    case "HH:mm:ss":
      return `${hhmm}:${pad(p.second)}`;
    case "M/D":
      return `${p.month}/${p.day}`;
    case "M/D HH:mm":
      return `${p.month}/${p.day} ${hhmm}`;
  }
}

/** How long ago `iso` was, from `now` (ms): "방금", "N분 전", "N시간 전", "N일 전". Null if unreadable. */
export function timeAgo(iso: string, now: number = Date.now()): string | null {
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return null;
  const minutes = Math.floor(Math.max(0, now - t) / 60_000);
  if (minutes < 1) return TIME_TEXT.justNow;
  if (minutes < 60) return TIME_TEXT.minutesAgo(minutes);
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return TIME_TEXT.hoursAgo(hours);
  return TIME_TEXT.daysAgo(Math.floor(hours / 24));
}

/** A logical date `YYYY-MM-DD` (already Korean, spec 6.1) as `M/D`. */
export function formatDay(ymd: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(ymd);
  return m ? `${Number(m[2])}/${Number(m[3])}` : "—";
}
