import type { LifeReportLever } from "../../api/types.gen";
import { copyPanel } from "../../lib/copyPanel";
import styles from "../LifeReport.module.css";
import { axisLabel, REPORT_AXES } from "./axes";

// Three line weights, one per strength.
export const LEVER_WIDTH: Record<LifeReportLever["strength"], number> = { weak: 1, mid: 2.5, strong: 4 };

const W = 320;
const STEP = 36;
const LEFT = 20; // the numbered actions' centre
const RIGHT = 196; // the axes' dot; their names start after it

// Which action moves which axis, and how hard: numbered actions at the left (their words in the list
// under the drawing, where they can wrap), the six axes at the right, a line per lever.
export function LeverMap({ levers }: { levers: LifeReportLever[] }) {
  const actions = [...new Set(levers.map((l) => l.action))];
  const rows = Math.max(actions.length, REPORT_AXES.length);
  const h = rows * STEP;
  const yA = (i: number) => (h / actions.length) * (i + 0.5);
  const yX = (i: number) => (h / REPORT_AXES.length) * (i + 0.5);
  return (
    <>
      <svg className={styles.map} viewBox={`0 0 ${W} ${h}`} role="img" aria-label={copyPanel.report.leverLabel}>
        {levers.map((l, i) => (
          <line
            key={i}
            data-strength={l.strength}
            className={styles.lever}
            x1={LEFT + 11}
            y1={yA(actions.indexOf(l.action)).toFixed(1)}
            x2={RIGHT - 4}
            y2={yX(REPORT_AXES.indexOf(l.axis)).toFixed(1)}
            strokeWidth={LEVER_WIDTH[l.strength]}
          />
        ))}
        {actions.map((a, i) => (
          <g key={a}>
            <circle className={styles.node} cx={LEFT} cy={yA(i).toFixed(1)} r="11" />
            <text className={styles.nodeText} x={LEFT} y={yA(i).toFixed(1)} textAnchor="middle" dominantBaseline="central">
              {i + 1}
            </text>
          </g>
        ))}
        {REPORT_AXES.map((axis, i) => (
          <g key={axis}>
            <circle className={styles.axisNode} cx={RIGHT} cy={yX(i).toFixed(1)} r="4" />
            <text className={styles.mapText} x={RIGHT + 10} y={yX(i).toFixed(1)} dominantBaseline="central">
              {axisLabel(axis)}
            </text>
          </g>
        ))}
      </svg>
      <ol className={styles.actions}>
        {actions.map((a, i) => (
          <li key={a}>
            <span className={styles.num} aria-hidden="true">
              {i + 1}
            </span>
            <span>
              {a}
              <span className={styles.meta}>
                {" → "}
                {levers
                  .filter((l) => l.action === a)
                  .map((l) => axisLabel(l.axis))
                  .join(", ")}
              </span>
            </span>
          </li>
        ))}
      </ol>
    </>
  );
}
