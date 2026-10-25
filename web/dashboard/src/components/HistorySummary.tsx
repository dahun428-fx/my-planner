import type { HistorySummary as SummaryData } from "../api/types.gen";
import { ladderText } from "../lib/history";
import { HISTORY_TEXT as T } from "../lib/labels";
import { Pictogram, type PictogramName } from "./pictograms.gen";

/** The four side lines of SP8 8.6 (a line with no value is left out) and the help box. */
export function HistorySummary({ summary: s }: { summary: SummaryData }) {
  const lines: Array<{ icon: PictogramName; text: string }> = [];
  if (s.highest) lines.push({ icon: "level", text: T.summary.highest(s.highest.title, ladderText(s.highest.ladder)) });
  if (s.turning_points.count > 0) lines.push({ icon: "turning_point", text: T.summary.turningPoints(s.turning_points.count, s.turning_points.years) });
  if (s.longest) lines.push({ icon: "chapter", text: T.summary.longest(s.longest.title, s.longest.years) });
  if (s.records_since !== null) lines.push({ icon: "review", text: T.summary.since(s.records_since) });
  return (
    <div className="history-summary" role="group" aria-label={T.summary.label}>
      {lines.length > 0 && (
        <ul className="history-summary-lines">
          {lines.map((l) => (
            <li key={l.icon}>
              <Pictogram name={l.icon} size={20} />
              <span>{l.text}</span>
            </li>
          ))}
        </ul>
      )}
      <p className="history-help">
        <Pictogram name="assistant" size={20} />
        <span>{T.summary.help}</span>
      </p>
    </div>
  );
}
