import type { CurveHistory, HistoryChapter, HistoryEvent } from "../api/types.gen";

export type HistoryFilter = "all" | "high" | "low" | "turning_point";
export type HistoryOrder = "recent" | "oldest";

/** How many of the newest chapters a phone shows open (SP8 8.3). */
export const PHONE_OPEN_CHAPTERS = 4;

export function filterEvents(events: HistoryEvent[], f: HistoryFilter): HistoryEvent[] {
  return f === "all" ? events : events.filter((e) => e.kind === f);
}

const hasUnassigned = (h: CurveHistory) => h.unassigned.events.length > 0 || h.unassigned.hidden_sensitive.count > 0;

/**
 * The chapters in the order shown. The BE sends them newest first; the group of events with no chapter
 * ("unassigned") is last then, and first when the oldest come first.
 */
export function orderChapters(h: CurveHistory, order: HistoryOrder): Array<HistoryChapter | "unassigned"> {
  const tail: Array<"unassigned"> = hasUnassigned(h) ? ["unassigned"] : [];
  return order === "recent" ? [...h.chapters, ...tail] : [...tail, ...[...h.chapters].reverse()];
}

/** The ids of chapters a phone folds: all but the newest four, unless opened (`chapters` newest first). */
export function collapsedOnPhone(chapters: HistoryChapter[], expanded: Set<number>): Set<number> {
  return new Set(
    chapters
      .slice(PHONE_OPEN_CHAPTERS)
      .map((c) => c.id)
      .filter((id) => !expanded.has(id)),
  );
}

const year = (ym: string) => ym.slice(0, 4);

/** "2019 – 2022"; a chapter that has not ended is "2026 –". */
export function yearsText(start: string, end: string | null): string {
  return end === null ? `${year(start)} –` : `${year(start)} – ${year(end)}`;
}

/** "2019.03"; a year only is "2018"; a day is "2026.02.14". Only as precise as remembered. */
export function eventDateText(date: string, precision: HistoryEvent["precision"]): string {
  const [y, m, d] = date.split("-");
  if (precision === "year" || !m) return y;
  if (precision === "month" || !d) return `${y}.${m}`;
  return `${y}.${m}.${d}`;
}

/** A whole number has no ".0"; anything else has one decimal (SP8 8.2, plan decision 16). */
export function ladderText(value: number): string {
  return Number.isInteger(value) ? String(value) : value.toFixed(1);
}
