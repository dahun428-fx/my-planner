import { useId } from "react";
import type { Moment } from "../api/types.gen";
import { STATUS_TEXT as T, momentDay } from "../lib/labels";
import { Pictogram } from "./pictograms.gen";

/** The moments grouped by day, in the order they came (newest day first). */
function byDay(moments: Moment[]): { date: string; items: Moment[] }[] {
  const days: { date: string; items: Moment[] }[] = [];
  for (const m of moments) {
    const last = days.at(-1);
    if (last && last.date === m.date) last.items.push(m);
    else days.push({ date: m.date, items: [m] });
  }
  return days;
}

/** 이룬 순간: the last days' moments, read only. Hiding and deleting are in the ops app (SP8 10.1). */
export function MomentsPanel({ moments }: { moments: Moment[] }) {
  const headingId = useId();
  return (
    <section className="panel" aria-labelledby={headingId}>
      <h2 id={headingId} className="with-icon">
        <Pictogram name="memory" size={20} />
        {T.momentsHeading}
      </h2>
      {moments.length === 0 ? (
        <p className="empty">{T.momentsEmpty}</p>
      ) : (
        <>
          {byDay(moments).map((day) => (
            <div key={day.date} className="moment-day">
              <h3 className="sub-heading">{momentDay(day.date)}</h3>
              <ul className="moments">
                {day.items.map((m) => (
                  <li key={m.id} className="moment" data-area={m.area ?? undefined}>
                    <Pictogram name={m.area ?? "memory"} size={20} />
                    <span className="moment-text">{m.text}</span>
                  </li>
                ))}
              </ul>
            </div>
          ))}
          <p className="hint meta">{T.momentsFooter}</p>
        </>
      )}
    </section>
  );
}
