import type { LifeReportTrack } from "../../api/types.gen";
import { copyPanel } from "../../lib/copyPanel";
import styles from "../LifeReport.module.css";

const dayNo = (d: string) => {
  const [y, m, day] = d.split("-").map(Number);
  return Date.UTC(y, m - 1, day) / 86_400_000;
};
const md = (d: string) => `${Number(d.slice(5, 7))}/${Number(d.slice(8, 10))}`;

// The 90-day roadmap as a Gantt: a bar per track over the whole span of the tracks (--raised behind,
// --primary bar), and today as a 1px line at the same place in every row, so the rows read as one chart.
export function Roadmap({ tracks, today }: { tracks: LifeReportTrack[]; today: string }) {
  const from = Math.min(...tracks.map((t) => dayNo(t.start)));
  const to = Math.max(...tracks.map((t) => dayNo(t.end)));
  const span = Math.max(1, to - from);
  const x = (d: string) => ((dayNo(d) - from) / span) * 100;
  const t = dayNo(today);
  const todayX = t >= from && t <= to ? ((t - from) / span) * 100 : null;
  return (
    <ul className={styles.list}>
      {tracks.map((tr, i) => (
        <li key={i} className={styles.row}>
          <div className={styles.head}>
            <span className={styles.name}>{tr.track}</span>
            <span className={styles.meta}>{`${md(tr.start)}–${md(tr.end)}`}</span>
          </div>
          <span className={styles.meta}>{tr.kpi}</span>
          <svg className={styles.gantt} viewBox="0 0 100 12" preserveAspectRatio="none" role="img" aria-label={copyPanel.report.roadmapLabel(tr.track)}>
            <rect className={styles.ganttTrack} x="0" y="3" width="100" height="6" rx="1" />
            <rect data-bar="" className={styles.ganttBar} x={x(tr.start).toFixed(2)} y="3" width={Math.max(0.5, x(tr.end) - x(tr.start)).toFixed(2)} height="6" rx="1" />
            {todayX !== null && <line data-today="" className={styles.today} x1={todayX.toFixed(2)} y1="0" x2={todayX.toFixed(2)} y2="12" />}
          </svg>
        </li>
      ))}
    </ul>
  );
}
