import { copy } from "../../lib/copy";
import { formatKst } from "../../lib/time";
import type { PartTodo } from "../types";

// Dates on the parts (SP6 spec 5.3.5, 6.2, 6.4). A logical date (YYYY-MM-DD) is calendar
// arithmetic with no time zone; only `scheduled_at`, an instant, is shown in Seoul time.

const parts = (date: string) => date.split("-").map(Number) as [number, number, number];
const dayNumber = (date: string) => {
  const [y, m, d] = parts(date);
  return Date.UTC(y, m - 1, d) / 86_400_000;
};

export function weekdayKo(date: string): string {
  const [y, m, d] = parts(date);
  return copy.parts.weekdays[new Date(Date.UTC(y, m - 1, d)).getUTCDay()];
}

/** "10월 27일 (화)" */
export function dayLabel(date: string): string {
  const [, m, d] = parts(date);
  return copy.parts.dayLabel(m, d, weekdayKo(date));
}

export function relativeDay(date: string, today: string): "today" | "tomorrow" | "yesterday" | null {
  switch (dayNumber(date) - dayNumber(today)) {
    case 0:
      return "today";
    case 1:
      return "tomorrow";
    case -1:
      return "yesterday";
    default:
      return null;
  }
}

/**
 * The grey line at the right of a to-do row (5.3.5): "뺌" for a dropped one, its time when it has
 * one, its day when it is planned for another day than `today`, otherwise nothing. Without
 * `today` (an older BE) the day is not shown: it cannot be told apart from today.
 */
export function rowMeta(todo: PartTodo, today: string | undefined): string | null {
  if (todo.status === "dropped") return copy.parts.dropped;
  if (todo.scheduled_at) return formatKst(todo.scheduled_at, "HH:mm");
  if (todo.planned_for && today !== undefined && todo.planned_for !== today) return dayLabel(todo.planned_for);
  return null;
}

const fromDayNumber = (n: number): string => new Date(n * 86_400_000).toISOString().slice(0, 10);

/** The ISO week (`YYYY-Www`, as in `priorities.period`) of a logical date. */
export function isoWeekOf(date: string): string {
  const n = dayNumber(date);
  const dow = (new Date(n * 86_400_000).getUTCDay() + 6) % 7; // Monday 0
  const thursday = n - dow + 3; // the week belongs to the year of its Thursday
  const year = Number(fromDayNumber(thursday).slice(0, 4));
  const week = Math.floor((thursday - dayNumber(`${year}-01-01`)) / 7) + 1;
  return `${year}-W${String(week).padStart(2, "0")}`;
}

/** The Monday of an ISO week. */
export function weekMonday(week: string): string {
  const [y, w] = week.split("-W").map(Number);
  const jan4 = dayNumber(`${y}-01-04`);
  const dow = (new Date(jan4 * 86_400_000).getUTCDay() + 6) % 7;
  return fromDayNumber(jan4 - dow + (w - 1) * 7);
}

const monthDay = (date: string) => {
  const [, m, d] = parts(date);
  return copy.parts.monthDay(m, d);
};

/** ui_period_list's title for a day (6.4): 오늘 / 내일 / 어제 from `today`, otherwise "10월 27일 (화)". */
export function dayTitle(day: string, today: string | undefined): string {
  const rel = today === undefined ? null : relativeDay(day, today);
  return rel ? copy.parts[rel] : dayLabel(day);
}

/** ui_period_list's title for a week (6.4): this / next / last week from `today`, otherwise "10월 26일 ~ 11월 1일". */
export function weekTitle(week: string, today: string | undefined): string {
  if (today !== undefined) {
    const by = (dayNumber(weekMonday(week)) - dayNumber(weekMonday(isoWeekOf(today)))) / 7;
    if (by === 0) return copy.parts.thisWeek;
    if (by === 1) return copy.parts.nextWeek;
    if (by === -1) return copy.parts.lastWeek;
  }
  const monday = weekMonday(week);
  return copy.parts.weekRange(monthDay(monday), monthDay(fromDayNumber(dayNumber(monday) + 6)));
}

/** A ui_date_choice candidate (6.2): "오늘 · 10월 24일 (토)", "내일 · 10월 25일 (일)", otherwise "10월 27일 (화)". */
export function candidateLabel(date: string, today: string | undefined): string {
  const rel = today === undefined ? null : relativeDay(date, today);
  return rel === "today" || rel === "tomorrow" ? copy.parts.relativeDay(copy.parts[rel], dayLabel(date)) : dayLabel(date);
}
