import type { HistorySummary as SummaryData } from "../api/types.gen";
import { ladderText } from "../lib/history";
import { HISTORY_TEXT as T } from "../lib/labels";
import { Pictogram, type PictogramName } from "./pictograms.gen";

/** The four side lines of SP8 8.6 (a line with no value is left out) and the help box. */
export function HistorySummary({ summary: s }: { summary: SummaryData }) {
  const lines: Array<{ icon: PictogramName; head: string; value: string }> = [];
  if (s.highest) lines.push({ icon: "level", head: T.summary.highest.head, value: T.summary.highest.value(s.highest.title, ladderText(s.highest.ladder)) });
  if (s.turning_points.count > 0) lines.push({ icon: "turning_point", head: T.summary.turningPoints.head, value: T.summary.turningPoints.value(s.turning_points.count, s.turning_points.years) });
  if (s.longest) lines.push({ icon: "chapter", head: T.summary.longest.head, value: T.summary.longest.value(s.longest.title, s.longest.years) });
  if (s.records_since !== null) lines.push({ icon: "review", head: T.summary.since.head, value: T.summary.since.value(s.records_since) });
  return (
    <div className="history-summary" role="group" aria-label={T.summary.label}>
      {lines.length > 0 && (
        <ul className="history-summary-lines">
          {lines.map((l) => (
            <li key={l.icon}>
              <Pictogram name={l.icon} size={20} />
              <span className="history-summary-text">
                <span className="meta">{l.head}</span>
                <span className="history-summary-value">{l.value}</span>
              </span>
            </li>
          ))}
        </ul>
      )}
      <p className="history-help">
        <Pictogram name="assistant" size={20} />
        <span className="history-summary-text">
          <span className="history-summary-value">{T.summary.helpTitle}</span>
          <span>{T.summary.help}</span>
        </span>
      </p>
    </div>
  );
}
