import type { HabitWeek } from "../api/types.gen";
import { copy } from "../lib/copy";
import { addDays } from "../lib/time";
import styles from "./HabitGrid.module.css";

const DAYS = 28;
/** Today and the six days before it: the only days a check can be given or taken back (SP7 5.3). */
const PRESSABLE_DAYS = 7;

const partsOf = (date: string) => date.split("-").map(Number) as [number, number, number];

/** The Monday of the week `date` (YYYY-MM-DD) is in. Calendar arithmetic only, no time zone. */
export function mondayOf(date: string): string {
  const [y, m, d] = partsOf(date);
  const dow = new Date(Date.UTC(y, m - 1, d)).getUTCDay(); // 0 = Sunday
  return addDays(date, -((dow + 6) % 7));
}

/** The first cell of the four-week grid: the Monday three weeks before this week's (SP7 6.2, 5.5 `from`). */
export function gridFrom(today: string): string {
  return addDays(mondayOf(today), -21);
}

/** The Monday of an ISO week ("2026-W43" -> "2026-10-19"): week 1 is the week with 4 January in it. */
export function isoWeekMonday(week: string): string {
  const m = /^(\d{4})-W(\d{2})$/.exec(week);
  if (!m) return "";
  return addDays(mondayOf(`${m[1]}-01-04`), (Number(m[2]) - 1) * 7);
}

/**
 * The lines under the grid (SP7 6.2, appendix A): weeks with checks only, newest first. A week the
 * BE leaves out, or one with 0, gets no line: the screen never says how many were not done.
 */
export function weekLines(weeks: readonly HabitWeek[], today: string): string[] {
  const thisWeek = mondayOf(today);
  const lastWeek = addDays(thisWeek, -7);
  return weeks
    .filter((w) => w.count > 0)
    .map((w) => ({ monday: isoWeekMonday(w.week), n: w.count }))
    .filter((w) => w.monday !== "")
    .sort((a, b) => b.monday.localeCompare(a.monday))
    .map(({ monday, n }) => {
      if (monday === thisWeek) return copy.habits.week(n);
      if (monday === lastWeek) return copy.habits.lastWeek(n);
      const [, mm, dd] = partsOf(monday);
      return copy.habits.weekOf(mm, dd, n);
    });
}

export interface HabitGridProps {
  /** The Monday of the first row (`GET /habits/{id}` `from`). */
  from: string;
  /** The BE's logical today. */
  today: string;
  checkedDates: readonly string[];
  /** Check or uncheck that day. Left out, the grid is only for looking (offline). */
  onToggle?(date: string): void;
  /** Days whose answer has not come yet. */
  busy?: ReadonlySet<string>;
}

/**
 * The last four weeks, 7 × 4 from Monday (SP7 6.2). Every cell has its small grey date number; a
 * checked day also has a dot. A day without a check draws nothing more: no ring, no X, no red (10장).
 * Today's number is bold and the days after it are faint. Only today and the six days before it
 * can be pressed; the other cells are only to look at.
 */
export function HabitGrid({ from, today, checkedDates, onToggle, busy }: HabitGridProps) {
  const checked = new Set(checkedDates);
  const firstPressable = addDays(today, -(PRESSABLE_DAYS - 1));
  const cells = Array.from({ length: DAYS }, (_, i) => addDays(from, i));
  return (
    <div className={styles.grid} role="group" aria-label={copy.habits.gridLabel}>
      {cells.map((date) => {
        const [, m, d] = partsOf(date);
        const isChecked = checked.has(date);
        const cls = [styles.cell, date === today ? styles.today : "", date > today ? styles.future : ""].join(" ");
        const inner = (
          <>
            <span className={styles.num}>{d}</span>
            {isChecked && <span className={styles.dot} data-dot="" aria-hidden="true" />}
          </>
        );
        if (onToggle && date >= firstPressable && date <= today) {
          return (
            <button
              key={date}
              type="button"
              data-date={date}
              className={`${cls} ${styles.pressable}`}
              aria-label={copy.dateParts.monthDay(m, d)}
              aria-pressed={isChecked}
              disabled={busy?.has(date) ?? false}
              onClick={() => onToggle(date)}
            >
              {inner}
            </button>
          );
        }
        return (
          <span key={date} data-date={date} className={cls}>
            {inner}
          </span>
        );
      })}
    </div>
  );
}
