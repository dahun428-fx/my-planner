import { STATUS_TEXT as T } from "../lib/labels";

/** One area's score (1-10) at its true ratio; no score is an empty track and a dash (spec 13.5, 9.3). */
export function StatBar({ label, score, max = 10 }: { label: string; score: number | null; max?: number }) {
  const ratio = score === null ? 0 : Math.min(1, Math.max(0, score / max));
  return (
    <svg className="stat-bar" viewBox="0 0 100 8" preserveAspectRatio="none" role="img" aria-label={T.statBar(label, score)}>
      <rect className="bar-track" x="0" y="0" width="100" height="8" rx="1.2" ry="4" />
      {ratio > 0 && <rect className="stat-fill" x="0" y="0" width={ratio * 100} height="8" rx="1.2" ry="4" />}
    </svg>
  );
}
