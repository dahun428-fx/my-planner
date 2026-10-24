import { STATUS_TEXT as T } from "../lib/labels";

/** HP is today's condition (1-5) in five cells; no record is five empty cells and words (9.3). */
export function HpCells({ score }: { score: number | null }) {
  return (
    <div className="hp">
      <div className="hp-head">
        <span className="hp-value num">{score === null ? T.hpNone : T.hp(score)}</span>
        <span className="meta">{T.hpWhat}</span>
      </div>
      <svg className="hp-bar" viewBox="0 0 108 10" preserveAspectRatio="none" role="img" aria-label={T.hpBar(score)}>
        {[0, 1, 2, 3, 4].map((i) => (
          <rect key={i} className="hp-cell" data-on={score !== null && i < score} x={i * 22} y="0" width="20" height="10" rx="2" />
        ))}
      </svg>
    </div>
  );
}
