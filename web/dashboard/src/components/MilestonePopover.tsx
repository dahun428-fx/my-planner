import { useEffect, useId, useRef } from "react";
import type { CurveMilestone } from "../api/types.gen";
import { CURVE_TEXT as T } from "../lib/labels";

/** `2019년`, `2025년 9월`, `2026년 2월 14일`: only as precise as remembered (5.4 `precision`). */
export function formatMilestoneDate(date: string, precision: CurveMilestone["precision"]): string {
  const [y, m, d] = date.split("-").map(Number);
  if (precision === "year" || !m) return `${y}년`;
  if (precision === "month" || !d) return `${y}년 ${m}월`;
  return `${y}년 ${m}월 ${d}일`;
}

/**
 * What a tapped milestone shows (13.4): date, kind, title, note. Opening moves focus to its title, so a
 * screen reader reads what opened; Escape or 닫기 closes it (the screen puts focus back on the marker).
 */
export function MilestonePopover({ milestone: m, onClose }: { milestone: CurveMilestone; onClose: () => void }) {
  const titleId = useId();
  const title = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    title.current?.focus();
  }, [m.id]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div className="milestone" role="dialog" aria-modal="false" aria-labelledby={titleId} data-kind={m.kind}>
      <div className="milestone-head">
        <p className="milestone-meta meta num">
          <span className="milestone-glyph" aria-hidden="true">
            {T.glyphs[m.kind]}
          </span>{" "}
          {formatMilestoneDate(m.date, m.precision)} · {T.kinds[m.kind]}
          {m.certainty === "estimate" && ` ${T.estimate}`}
          {m.sensitive && ` · ${T.sensitiveMark}`}
        </p>
        <button type="button" className="text-button" onClick={onClose}>
          {T.close}
        </button>
      </div>
      <h3 id={titleId} className="milestone-title" tabIndex={-1} ref={title}>
        {m.title}
      </h3>
      {m.note && <p className="milestone-note">{m.note}</p>}
    </div>
  );
}
