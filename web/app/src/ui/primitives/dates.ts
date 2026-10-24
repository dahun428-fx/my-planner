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
