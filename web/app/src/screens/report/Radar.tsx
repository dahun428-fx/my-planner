import type { LifeReportScore } from "../../api/types.gen";
import { copyPanel } from "../../lib/copyPanel";
import styles from "../LifeReport.module.css";
import { axisLabel, REPORT_AXES } from "./axes";

// The six axes' national scores (DESIGN.md 레이더): rings --rule, the outline 1.5px --text, no fill.
const SIZE = 320;
const C = SIZE / 2;
const R = 100;
const at = (i: number, n: number, r: number): [number, number] => {
  const a = (Math.PI * 2 * i) / n - Math.PI / 2;
  return [C + r * Math.cos(a), C + r * Math.sin(a)];
};
const pt = (i: number, n: number, v: number) => at(i, n, (Math.max(0, Math.min(100, v)) / 100) * R).map((x) => x.toFixed(1)).join(" ");

/** The outline: closed when every axis has a score; otherwise only the edges between two scored neighbours. */
export function outline(values: (number | null)[]): string {
  const n = values.length;
  if (values.every((v) => v !== null)) return `M${values.map((v, i) => pt(i, n, v as number)).join(" L")} Z`;
  const parts: string[] = [];
  values.forEach((v, i) => {
    const w = values[(i + 1) % n];
    if (v !== null && w !== null) parts.push(`M${pt(i, n, v)} L${pt((i + 1) % n, n, w)}`);
  });
  return parts.join(" ");
}

export function Radar({ scores }: { scores: Record<string, LifeReportScore> }) {
  const n = REPORT_AXES.length;
  const values = REPORT_AXES.map((a) => scores[a]?.national ?? null);
  const ring = (f: number) => REPORT_AXES.map((_, i) => at(i, n, f * R).map((x) => x.toFixed(1)).join(",")).join(" ");
  return (
    <svg className={styles.radar} viewBox={`0 0 ${SIZE} ${SIZE}`} role="img" aria-label={copyPanel.report.radarLabel}>
      {[0.25, 0.5, 0.75, 1].map((f) => (
        <polygon key={f} className={styles.ring} points={ring(f)} />
      ))}
      {REPORT_AXES.map((a, i) => {
        const [x, y] = at(i, n, R);
        return <line key={a} data-axis={a} className={styles.spoke} x1={C} y1={C} x2={x.toFixed(1)} y2={y.toFixed(1)} />;
      })}
      <path data-cohort="national" className={styles.nationalLine} d={outline(values)} />
      {values.map((v, i) => {
        if (v === null) return null;
        const [x, y] = at(i, n, (Math.max(0, Math.min(100, v)) / 100) * R);
        return <circle key={REPORT_AXES[i]} className={styles.radarDot} cx={x.toFixed(1)} cy={y.toFixed(1)} r="2.5" />;
      })}
      {REPORT_AXES.map((a, i) => {
        const [x, y] = at(i, n, R + 16);
        const anchor = Math.abs(x - C) < 4 ? "middle" : x > C ? "start" : "end";
        return (
          <text key={a} className={styles.axisText} x={x.toFixed(1)} y={y.toFixed(1)} textAnchor={anchor} dominantBaseline="middle">
            {axisLabel(a)}
          </text>
        );
      })}
    </svg>
  );
}
