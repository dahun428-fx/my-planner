import type { StatusStat } from "../api/types.gen";
import { AREAS, STATUS_TEXT as T } from "../lib/labels";
import { Pictogram } from "./pictograms.gen";

/** The areas with a bonus, biggest first and in the SP1 area order on a tie (spec 10.1). */
export function recentAreas(stats: StatusStat[]): StatusStat[] {
  return stats
    .filter((s) => s.bonus > 0)
    .sort((a, b) => b.bonus - a.bonus || AREAS.indexOf(a.area) - AREAS.indexOf(b.area));
}

/** 요즘 손이 간 영역: where the last four weeks went. A line per area; no earlier value, no direction. */
export function RecentAreas({ stats, headingId }: { stats: StatusStat[]; headingId: string }) {
  const rows = recentAreas(stats);
  return (
    <section className="panel" aria-labelledby={headingId}>
      <h2 id={headingId} className="with-icon">
        <Pictogram name="status" size={20} />
        {T.recentHeading}
      </h2>
      {rows.length === 0 ? (
        <p className="empty">{T.recentAreasEmpty}</p>
      ) : (
        <ul className="recent-areas">
          {rows.map((s) => (
            <li key={s.area} className="recent-area" data-area={s.area}>
              <span className="recent-name">
                <Pictogram name={s.area} size={20} />
                {s.label}
              </span>
              <span className="recent-bonus num">{T.recentLine(s.bonus)}</span>
              <span className="recent-counts meta">{T.recentCounts(s.activity)}</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
