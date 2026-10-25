import type { CurveHistory, HistoryChapter, HistoryEvent } from "../api/types.gen";

export type HistoryFilter = "all" | "high" | "low" | "turning_point";
export type HistoryOrder = "recent" | "oldest";

/** How many of the newest chapters a phone shows open (SP8 8.3). */
export const PHONE_OPEN_CHAPTERS = 4;

export function filterEvents(events: HistoryEvent[], f: HistoryFilter): HistoryEvent[] {
  return f === "all" ? events : events.filter((e) => e.kind === f);
}

/** A group of hidden events alone (the "가려 둔 사건" line, 8.5) is still a group, not an empty head. */
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

/** The key of the group with no chapter in the set of chapters whose sensitive events are opened (chapter ids start at 1). */
export const UNASSIGNED_ID = 0;

const eventYear = (e: HistoryEvent) => Number(e.date.slice(0, 4));

/**
 * What the screen may show of a history that can hold sensitive events (SP8 8.5): in a group that is not opened
 * (and with `all` off) its sensitive events are taken out and counted into `hidden_sensitive`, and the summary
 * is made to count and list only what is left, so a hidden event is never drawn or counted. A response without
 * sensitive events passes through unchanged.
 */
export function applySensitive(h: CurveHistory, opened: Set<number>, all: boolean): CurveHistory {
  let removed = 0;
  const cut = <G extends { events: HistoryEvent[]; hidden_sensitive: CurveHistory["unassigned"]["hidden_sensitive"] }>(g: G, id: number): G => {
    if (all || opened.has(id)) return g;
    const gone = g.events.filter((e) => e.sensitive);
    if (gone.length === 0) return g;
    removed += gone.length;
    const years = [...new Set([...g.hidden_sensitive.years, ...gone.map(eventYear)])].sort((a, b) => a - b);
    return { ...g, events: g.events.filter((e) => !e.sensitive), hidden_sensitive: { count: g.hidden_sensitive.count + gone.length, years } };
  };
  const chapters = h.chapters.map((c) => cut(c, c.id));
  const unassigned = cut(h.unassigned, UNASSIGNED_ID);
  if (removed === 0) return h;
  const turns = [...chapters.flatMap((c) => c.events), ...unassigned.events].filter((e) => e.kind === "turning_point");
  const years = [...new Set(turns.map(eventYear))].sort((a, b) => a - b);
  return { ...h, chapters, unassigned, summary: { ...h.summary, events: h.summary.events - removed, turning_points: { count: turns.length, years } } };
}

// ---- the glance strip (SP8 8.6): the layout is numbers only, GlanceStrip draws it ----

/** Side margin of the strip, the height of a chapter band and the width of a pictogram mark, in px. */
export const GLANCE_PAD = 12;
export const GLANCE_BAND_H = 40;
export const GLANCE_MARK = 16;

export interface Glance {
  ticks: Array<{ x: number; label: string }>;
  bands: Array<{ chapterId: number; x: number; w: number; dashed: boolean; ladderY: number | null }>;
  marks: Array<{ eventId: number; x: number; kind: HistoryEvent["kind"] }>;
}

const monthStart = (ym: string) => {
  const [y, m = "1", d = "1"] = ym.split("-");
  return Date.UTC(Number(y), Number(m) - 1, Number(d));
};
/** The start of the month after `ym`: a chapter that ends in a month covers that month. */
const monthAfter = (ym: string) => {
  const [y, m] = ym.split("-").map(Number);
  return Date.UTC(y, m, 1);
};

/**
 * Chapters as bands and events as marks on a time axis from `since_year` to `today` (`YYYY-MM-DD`), inside
 * `width` px. Ticks: the first year, every decade between, this year. A ladder 0..10 is a height in the band
 * (`ladderY` from its top; 10 is the top), `null` without a ladder.
 */
export function glanceLayout(h: CurveHistory, width: number, today: string): Glance {
  const startYear = h.since_year ?? (h.chapters.length ? Math.min(...h.chapters.map((c) => Number(c.start.slice(0, 4)))) : null);
  if (startYear === null) return { ticks: [], bands: [], marks: [] };
  const t0 = Date.UTC(startYear, 0, 1);
  const t1 = Math.max(monthStart(today), t0 + 1);
  const plot = Math.max(width - 2 * GLANCE_PAD, 1);
  const at = (t: number) => GLANCE_PAD + (Math.min(Math.max(t, t0), t1) - t0) / (t1 - t0) * plot;
  const thisYear = Number(today.slice(0, 4));

  const years = [startYear];
  for (let y = Math.ceil((startYear + 1) / 10) * 10; y < thisYear; y += 10) years.push(y);
  if (thisYear > startYear) years.push(thisYear);
  const ticks = years
    .map((y) => ({ y, x: at(Date.UTC(y, 0, 1)) }))
    // a decade that would sit on top of the first or the last label is left out
    .filter((t, i) => i === 0 || i === years.length - 1 || (t.x - at(t0) > 30 && at(Date.UTC(thisYear, 0, 1)) - t.x > 30))
    .map((t) => ({ x: t.x, label: String(t.y) }));

  const bands = h.chapters.map((c) => {
    const x = at(monthStart(c.start));
    const end = at(c.end === null ? t1 : monthAfter(c.end));
    const v = c.ladder === null ? null : Math.min(Math.max(c.ladder.value, 0), 10);
    return { chapterId: c.id, x, w: Math.max(end - x, 2), dashed: c.certainty === "estimate", ladderY: v === null ? null : GLANCE_BAND_H * (1 - v / 10) };
  });
  const events = [...h.chapters.flatMap((c) => c.events), ...h.unassigned.events];
  const marks = events.map((e) => ({ eventId: e.id, x: at(monthStart(e.date)), kind: e.kind }));
  return { ticks, bands, marks };
}
