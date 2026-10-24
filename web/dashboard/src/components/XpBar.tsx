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
      <svg className="xp-bar" viewBox="0 0 100 6" preserveAspectRatio="none" role="img" aria-label={T.xpBar(into, forNext)}>
        <rect className="bar-track" x="0" y="0" width="100" height="6" rx="1" ry="3" />
        {ratio > 0 && <rect className="xp-fill" x="0" y="0" width={ratio * 100} height="6" rx="1" ry="3" />}
      </svg>
    </div>
  );
}
