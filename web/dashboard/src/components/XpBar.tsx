import { STATUS_TEXT as T } from "../lib/labels";

/**
 * Level and the XP gathered inside it (spec 13.5, 9.2). XP only rises (ADR 0006): the bar shows what is
 * already gathered, never what is left. A zero has no stub.
 */
export function XpBar({ level, into, forNext }: { level: number; into: number; forNext: number }) {
  const ratio = forNext > 0 ? Math.min(1, Math.max(0, into / forNext)) : 0;
  return (
    <div className="xp">
      <div className="xp-head">
        <span className="xp-level num">{T.level(level)}</span>
        <span className="xp-amount num">{T.xp(into, forNext)}</span>
      </div>
      <svg className="xp-bar" viewBox="0 0 100 10" preserveAspectRatio="none" role="img" aria-label={T.xpBar(into, forNext)}>
        <rect className="bar-track" x="0" y="0" width="100" height="10" rx="1.5" ry="5" />
        {ratio > 0 && <rect className="xp-fill" x="0" y="0" width={ratio * 100} height="10" rx="1.5" ry="5" />}
      </svg>
    </div>
  );
}

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
