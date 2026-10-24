// Pure layout of the life curve (spec 8.2, 8.3, 13.4). The x axis is time in ms, read as Korean wall time:
// `kstX(y, m, d, h)` is that hour in Asia/Seoul. Nothing here draws; CurveChart and AreaRadar do.
import type { Curve, CurveAreas, CurveChapter, CurveCondition, CurveLadder } from "../api/types.gen";
import { AREA_LABELS, AREAS, type Area, CURVE_TEXT } from "./labels";

export type Zoom = Curve["zoom"];

const KST_OFFSET_MS = 9 * 3_600_000;
const DAY_MS = 86_400_000;

/** `h` o'clock Korean time on y-m-d, as epoch ms (months are 1-based; overflow rolls like Date.UTC). */
export const kstX = (y: number, m: number, d: number, h = 0): number => Date.UTC(y, m - 1, d, h) - KST_OFFSET_MS;

const parts = (ymd: string): [number, number, number] => {
  const [y, m, d] = ymd.split("-").map(Number);
  return [y, m || 1, d || 1];
};

/** 00:00 Korean time of a `YYYY-MM-DD` (or `YYYY-MM`, `YYYY`: its first day). */
export const dayStart = (ymd: string): number => {
  const [y, m, d] = parts(ymd);
  return kstX(y, m, d);
};

/** The end of a `YYYY-MM-DD` range: 00:00 of the next day. */
export const dayEnd = (ymd: string): number => dayStart(ymd) + DAY_MS;

/** Korean wall-clock date parts of an x. */
export function wall(x: number): { y: number; m: number; d: number } {
  const t = new Date(x + KST_OFFSET_MS);
  return { y: t.getUTCFullYear(), m: t.getUTCMonth() + 1, d: t.getUTCDate() };
}

const pad = (n: number) => String(n).padStart(2, "0");
const monthKey = (y: number, m: number) => `${y}-${pad(m)}`;

export interface LadderPoint {
  period: string;
  x: number;
  now: number | null;
  future: number | null;
}

/**
 * One point per month from the month of `from` to the month of `to`, on the 15th at noon (8.2). A month with
 * no score is `null`, so the line breaks there instead of dropping to 0 (P2).
 */
export function ladderSeries(ladder: CurveLadder[], from: string, to: string): LadderPoint[] {
  const byPeriod = new Map(ladder.map((l) => [l.period, l]));
  const [fy, fm] = parts(from);
  const [ty, tm] = parts(to);
  const out: LadderPoint[] = [];
  for (let i = fy * 12 + fm - 1; i <= ty * 12 + tm - 1; i++) {
    const y = Math.floor(i / 12);
    const m = (i % 12) + 1;
    const period = monthKey(y, m);
    const l = byPeriod.get(period);
    out.push({ period, x: kstX(y, m, 15, 12), now: l?.now ?? null, future: l?.future ?? null });
  }
  return out;
}

/**
 * The day and week zooms show the ladder as steps (8.2): each month's score is flat from its first day to its
 * last, an empty month stays a break. Two points per scored month, one `null` point per empty month.
 */
export function ladderSteps(points: LadderPoint[]): LadderPoint[] {
  return points.flatMap((p) => {
    if (p.now === null && p.future === null) return [p];
    const [y, m] = parts(p.period);
    return [
      { ...p, x: kstX(y, m, 1) },
      { ...p, x: kstX(y, m + 1, 1) - 1 },
    ];
  });
}

/** Where a milestone sits: a day at its noon, a month on the 15th (like the ladder), a year on 1 July. */
export function milestoneX(date: string, precision: "year" | "month" | "day"): number {
  const [y, m, d] = parts(date);
  if (precision === "year") return kstX(y, 7, 1, 12);
  if (precision === "month") return kstX(y, m, 15, 12);
  return kstX(y, m, d, 12);
}

export interface ConditionPoint {
  bucket: string;
  x: number;
  y: number;
  average: number;
  daysLogged: number;
}

/** Condition averages moved to the 0~10 axis, `(average − 1) × 2.5` (6.3.5), at the middle of each bucket. */
export function conditionSeries(buckets: CurveCondition[]): ConditionPoint[] {
  return buckets
    .filter((b): b is CurveCondition & { average: number } => b.average !== null)
    .map((b) => ({
      bucket: b.bucket,
      x: (dayStart(b.start) + dayEnd(b.end)) / 2,
      y: (b.average - 1) * 2.5,
      average: b.average,
      daysLogged: b.days_logged,
    }));
}

export interface ChapterBand {
  id: number;
  title: string;
  sketch: string | null;
  estimate: boolean;
  start: string;
  end: string | null;
  x1: number;
  x2: number;
  index: number; // alternates the band tone
}

/** Chapters as bands from their first month to the end of their last (an open chapter runs to `to`), clipped. */
export function chapterBands(chapters: CurveChapter[], from: string, to: string): ChapterBand[] {
  const lo = dayStart(from);
  const hi = dayEnd(to);
  return chapters
    .map((c) => {
      const [ey, em] = c.end ? parts(c.end) : [0, 0];
      return {
        id: c.id,
        title: c.title,
        sketch: c.sketch,
        estimate: c.certainty === "estimate",
        start: c.start,
        end: c.end,
        x1: Math.max(lo, dayStart(c.start)),
        x2: Math.min(hi, c.end ? kstX(ey, em + 1, 1) : hi),
      };
    })
    .filter((b) => b.x2 > b.x1)
    .sort((a, b) => a.x1 - b.x1)
    .map((b, index) => ({ ...b, index }));
}

/** The 8.3 table. `gap` is `condition_scaled − ladder_now`, one decimal, from the BE. */
export function reassuranceCopy(gap: number | null): string {
  if (gap === null) return CURVE_TEXT.copy.few;
  if (gap >= 1.0) return CURVE_TEXT.copy.better;
  if (gap <= -1.0) return CURVE_TEXT.copy.harder;
  return CURVE_TEXT.copy.similar;
}

/**
 * The range the chart shows. The API's own range, except the year zoom: the screen asks for it from
 * `YEAR_FROM` (so a milestone older than every chapter is not cut off) and shows it from the year of the
 * earliest thing it got, or this year when there is nothing.
 */
export function visibleRange(c: Curve): { from: string; to: string } {
  if (c.zoom !== "year") return { from: c.from, to: c.to };
  const years = [
    ...c.chapters.map((x) => x.start),
    ...c.milestones.map((x) => x.date),
    ...c.ladder.map((x) => x.period),
    ...c.areas.map((x) => x.period),
    ...c.condition.filter((x) => x.average !== null).map((x) => x.start),
  ].map((s) => Number(s.slice(0, 4)));
  const first = years.length > 0 ? Math.min(...years) : Number(c.to.slice(0, 4));
  return { from: `${Math.max(first, Number(c.from.slice(0, 4)))}-01-01`, to: c.to };
}

export interface Tick {
  x: number;
  label: string;
}

/** A few x labels per zoom: weeks counted back from the last day, months, quarters' months, years. */
export function axisTicks(zoom: Zoom, from: string, to: string): Tick[] {
  const lo = dayStart(from);
  const hi = dayEnd(to);
  const out: Tick[] = [];
  if (zoom === "day") {
    for (let x = dayStart(to); x >= lo; x -= 7 * DAY_MS) {
      const w = wall(x);
      out.unshift({ x: x + DAY_MS / 2, label: `${w.m}/${w.d}` });
    }
    return out;
  }
  const [fy, fm] = parts(from);
  const [ty] = parts(to);
  if (zoom === "week" || zoom === "month") {
    const months = zoom === "week" ? [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12] : [1, 4, 7, 10];
    const span = (hi - lo) / (30 * DAY_MS);
    const step = zoom === "week" && span > 8 ? 2 : 1;
    let k = 0;
    for (let y = fy; y <= ty; y++) {
      for (const m of months) {
        const x = kstX(y, m, 1);
        if (x < lo || x >= hi || (y === fy && m < fm)) continue;
        if (k++ % step === 0) out.push({ x, label: m === 1 ? String(y) : `${m}월` });
      }
    }
    return out;
  }
  const years = ty - fy + 1;
  const step = Math.max(1, Math.ceil(years / 6));
  for (let y = fy; y <= ty; y += step) out.push({ x: kstX(y, 1, 1), label: String(y) });
  return out;
}

/** At most `max` labels on a narrow plot: every k-th tick from the first (which keeps the January year labels). */
export function thinTicks(ticks: Tick[], max: number): Tick[] {
  if (ticks.length <= max) return ticks;
  const k = Math.ceil(ticks.length / max);
  return ticks.filter((_, i) => i % k === 0);
}

export interface RadarRow {
  area: Area;
  label: string;
  now: number | null;
  prev: number | null;
  down: boolean;
}

const quarterBefore = (period: string): string => {
  const y = Number(period.slice(0, 4));
  const q = Number(period.slice(6));
  return q === 1 ? `${y - 1}-Q4` : `${y}-Q${q - 1}`;
};

/** The latest quarter (solid) against the quarter right before it (dashed), in SP1 area order (13.4). */
export function radarRows(areas: CurveAreas[]): { latest: string | null; previous: string | null; rows: RadarRow[] } {
  if (areas.length === 0) return { latest: null, previous: null, rows: [] };
  const sorted = [...areas].sort((a, b) => a.period.localeCompare(b.period));
  const latest = sorted.at(-1)!;
  const before = sorted.find((a) => a.period === quarterBefore(latest.period)) ?? null;
  const rows = AREAS.map((area) => {
    const now = latest.scores[area] ?? null;
    const prev = before?.scores[area] ?? null;
    return { area, label: AREA_LABELS[area], now, prev, down: now !== null && prev !== null && now < prev };
  });
  return { latest: latest.period, previous: before?.period ?? null, rows };
}
