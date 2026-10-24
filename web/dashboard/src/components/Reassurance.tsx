import { useId } from "react";
import type { CurveReassurance } from "../api/types.gen";
import { reassuranceCopy } from "../lib/curveLayout";
import { CURVE_TEXT as T } from "../lib/labels";

const SHOWN = 6;

function Month({ r, year }: { r: CurveReassurance; year: string }) {
  const month = T.monthLabel(r.period, r.period.slice(0, 4) === year);
  return (
    <li className="reassure" data-period={r.period} data-compared={r.gap !== null || undefined}>
      <p className="reassure-head num">
        <span className="part">{T.remembered(month, r.ladder_now)}</span>
        {r.condition_scaled !== null && r.gap !== null && (
          <>
            {" · "}
            <span className="part">{T.daily(r.condition_scaled)}</span>
          </>
        )}
      </p>
      <p className="reassure-copy">{reassuranceCopy(r.gap)}</p>
    </li>
  );
}

/**
 * 안심 보기 (8.3): each month with a ladder score beside its condition average moved to 0~10, newest first,
 * with the copy of the 8.3 table. It never suggests changing a score. No compared month yet: the 13.4 text.
 */
export function Reassurance({ items }: { items: CurveReassurance[] }) {
  const headingId = useId();
  const months = [...items].sort((a, b) => b.period.localeCompare(a.period));
  const compared = months.some((r) => r.gap !== null);
  const year = months[0]?.period.slice(0, 4) ?? "";
  const shown = months.slice(0, SHOWN);
  const rest = months.slice(SHOWN);
  return (
    <section className="panel reassure-panel" aria-labelledby={headingId}>
      <h2 id={headingId}>{T.reassurance}</h2>
      {!compared ? (
        <p className="empty">{T.empty.reassurance}</p>
      ) : (
        <>
          <ul className="reassures">
            {shown.map((r) => (
              <Month key={r.period} r={r} year={year} />
            ))}
          </ul>
          {rest.length > 0 && (
            <details className="reassure-more">
              <summary className="meta">{T.moreMonths(rest.length)}</summary>
              <ul className="reassures">
                {rest.map((r) => (
                  <Month key={r.period} r={r} year={year} />
                ))}
              </ul>
            </details>
          )}
        </>
      )}
    </section>
  );
}
