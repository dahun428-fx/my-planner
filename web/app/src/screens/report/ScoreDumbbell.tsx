import type { LifeReportScore } from "../../api/types.gen";
import { copyPanel } from "../../lib/copyPanel";
import { standingCopy } from "../../lib/copyStanding";
import styles from "../LifeReport.module.css";
import { axisLabel, REPORT_AXES } from "./axes";

// 0..100 on a 200-wide drawing, 8 in from each end so a dot at 0 or 100 is whole.
const X0 = 8;
const W = 184;
const xOf = (v: number) => (X0 + (Math.max(0, Math.min(100, v)) / 100) * W).toFixed(1);

// The score board: per axis the national and the peer score as two dots on one line (a dumbbell), the
// stored copy of the numbers beside the name. A low-reliability axis is faded; an estimate says so.
export function ScoreDumbbell({ scores }: { scores: Record<string, LifeReportScore> }) {
  return (
    <ul className={styles.list}>
      {REPORT_AXES.map((axis) => {
        const s = scores[axis] ?? { national: null, peer: null, reliability: null, estimate: false };
        const label = axisLabel(axis);
        const both = s.national !== null && s.peer !== null;
        return (
          <li key={axis} className={`${styles.row} ${s.reliability === "low" ? styles.faded : ""}`} data-axis={axis} data-faded={s.reliability === "low" ? "" : undefined}>
            <div className={styles.head}>
              <span className={styles.name}>
                {label}
                {s.estimate && (
                  <>
                    {" "}
                    <span className={styles.tag}>{copyPanel.report.estimate}</span>
                  </>
                )}
              </span>
              <span className={styles.numbers}>
                <span>{standingCopy.national(s.national)}</span>
                <span>{standingCopy.peer(s.peer)}</span>
              </span>
            </div>
            <svg className={styles.bell} viewBox="0 0 200 16" role="img" aria-label={copyPanel.report.dumbbellLabel(label)}>
              <line className={styles.bellTrack} x1={X0} y1="8" x2={X0 + W} y2="8" />
              {both && <line className={styles.bellBar} x1={xOf(s.national!)} y1="8" x2={xOf(s.peer!)} y2="8" />}
              {s.peer !== null && <circle data-cohort="peer" className={styles.dotPeer} cx={xOf(s.peer)} cy="8" r="5" />}
              {s.national !== null && <circle data-cohort="national" className={styles.dotNational} cx={xOf(s.national)} cy="8" r="5" />}
            </svg>
          </li>
        );
      })}
    </ul>
  );
}
