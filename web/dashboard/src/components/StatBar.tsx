import { STATUS_TEXT as T } from "../lib/labels";

/** The ramp step (DESIGN.md 단계 램프, 1-5) of a score out of `max`: fill only, never a letter colour. */
export const rampStep = (score: number, max = 10): number => Math.min(5, Math.max(1, Math.ceil((score / max) * 5)));

/** One area's score (1-10) at its true ratio; no score is an empty track and a dash (spec 13.5, 9.3). */
export function StatBar({ label, score, bonus = 0, max = 10 }: { label: string; score: number | null; bonus?: number; max?: number }) {
  const ratio = score === null ? 0 : Math.min(1, Math.max(0, score / max));
  // The recent bonus follows the base as empty cells with a 1px ink outline: told apart by shape, not colour (spec 10.1).
  const cells = score === null ? 0 : Math.max(0, Math.min(max - score, Math.ceil(bonus)));
  const cell = 100 / max;
  return (
    <svg className="stat-bar" viewBox="0 0 100 8" preserveAspectRatio="none" role="img" aria-label={T.statBar(label, score)}>
      <rect className="bar-track" x="0" y="0" width="100" height="8" rx="1.2" ry="4" />
      {ratio > 0 && <rect className="stat-fill" x="0" y="0" width={ratio * 100} height="8" rx="1.2" ry="4" />}
      {cells > 0 && <rect className="stat-bonus" x={ratio * 100} y="0" width={cells * cell} height="8" rx="1.2" ry="4" />}
    </svg>
  );
}
