import { useId } from "react";
import type { ConditionItem } from "../api/types.gen";
import { CONDITION_TEXT as T } from "../lib/labels";
import { formatDay } from "../lib/time";

const DAY_MS = 86_400_000;
const SCORES = [5, 4, 3, 2, 1] as const;
const TICK_STEP = 7; // one label a week, counted back from the last day so the step lands on it

const dayIndex = (ymd: string): number => {
  const [y, m, d] = ymd.split("-").map(Number);
  return Math.round(Date.UTC(y, m - 1, d) / DAY_MS);
};

const ymdOf = (index: number): string => new Date(index * DAY_MS).toISOString().slice(0, 10);


/**
 * 30-day condition dots (spec 13.3). One column per day from `from` to `to`; a logged day is one dot at
 * its score, an empty day is nothing at all (no dot, no line, not a zero: 6.3.4). The plot stretches to the
 * panel's width; dots are zero-length round-capped lines with a non-scaling stroke, so they stay round.
 * The head shows the API's own `average` and `days_logged` (6.3.4), never a number worked out here, so it
 * reads the same as `/conditions` and Telegram.
 */
export function ConditionDots({
  items,
  from,
  to,
  average: apiAverage,
  daysLogged,
}: {
  items: ConditionItem[];
  from: string;
  to: string;
  average: number | null;
  daysLogged: number;
}) {
  const headingId = useId();
  const start = dayIndex(from);
  const days = Math.max(1, dayIndex(to) - start + 1);
  const average = apiAverage === null || daysLogged === 0 ? null : apiAverage.toFixed(1);
  const shown = items.filter((c) => {
    const i = dayIndex(c.date) - start;
    return i >= 0 && i < days && c.score >= 1 && c.score <= 5;
  });

  return (
    <section className="panel" aria-labelledby={headingId}>
      <div className="panel-head">
        <h2 id={headingId}>{T.title(days)}</h2>
        {average !== null && <span className="meta num">{T.head(average, daysLogged)}</span>}
      </div>
      {average === null ? (
        <p className="empty">{T.empty}</p>
      ) : (
        <div className="cdots">
          <div className="cdots-y" aria-hidden="true">
            {SCORES.map((s) => (
              <span key={s} className="num">
                {s}
              </span>
            ))}
          </div>
          <div className="cdots-frame">
            <svg
              className="cdots-plot"
              viewBox={`0 0 ${days} 4`}
              preserveAspectRatio="none"
              role="img"
              aria-label={T.chart(days, daysLogged, average)}
            >
              {SCORES.map((s) => (
                <line
                  key={s}
                  className="cdots-grid"
                  data-score={s}
                  x1={0}
                  x2={days}
                  y1={5 - s}
                  y2={5 - s}
                  vectorEffect="non-scaling-stroke"
                />
              ))}
              {shown.map((c) => {
                const x = dayIndex(c.date) - start + 0.5;
                return (
                  <line
                    key={c.date}
                    className="cdots-dot"
                    data-date={c.date}
                    data-score={c.score}
                    x1={x}
                    x2={x}
                    y1={5 - c.score}
                    y2={5 - c.score}
                    vectorEffect="non-scaling-stroke"
                  />
                );
              })}
            </svg>
          </div>
          <ul className="visually-hidden" aria-label={T.listLabel}>
            {shown.map((c) => (
              <li key={c.date}>{T.dayScore(formatDay(c.date), c.score)}</li>
            ))}
          </ul>
          <div className="cdots-x" aria-hidden="true">
            {Array.from({ length: days }, (_, i) => (
              <span key={i} className={i === days - 1 ? "num end" : "num"}>
                {(days - 1 - i) % TICK_STEP === 0 ? formatDay(ymdOf(start + i)) : ""}
              </span>
            ))}
          </div>
        </div>
      )}
    </section>
  );
}
