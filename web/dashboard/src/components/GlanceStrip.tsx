import type { CurveHistory } from "../api/types.gen";
import { GLANCE_BAND_H, GLANCE_MARK, GLANCE_PAD, glanceLayout, ladderText, yearsText } from "../lib/history";
import { CURVE_TEXT, HISTORY_TEXT as T } from "../lib/labels";
import { Pictogram } from "./pictograms.gen";

const MARK_TOP = 2;
const BAND_TOP = MARK_TOP + GLANCE_MARK + 6;
const AXIS_Y = BAND_TOP + GLANCE_BAND_H + 16;
const HEIGHT = AXIS_Y + 6;

/** The Korean calendar day of now, `YYYY-MM-DD`. */
const kstToday = () => new Date(Date.now() + 9 * 3_600_000).toISOString().slice(0, 10);

/**
 * 한눈에 보는 지난 길 (SP8 8.6): chapters as bands on a time axis, a short ink line in each at its ladder, a kind
 * pictogram where each event falls. A bare SVG as wide as it is shown (`viewBox` = `width`). No fill under a curve,
 * no area colour. The same content is a table for reading by screen. `history` holds only what may be shown.
 */
export function GlanceStrip({ history: h, width, today = kstToday() }: { history: CurveHistory; width: number; today?: string }) {
  const g = glanceLayout(h, width, today);
  const byId = new Map([...h.chapters.flatMap((c) => c.events), ...h.unassigned.events].map((e) => [e.id, e]));
  return (
    <figure className="glance">
      <figcaption>
        <h3 className="glance-title">{T.glance.title}</h3>
        <p className="meta glance-sub">{T.glance.subtitle}</p>
      </figcaption>
      <svg className="glance-svg" width={width} height={HEIGHT} viewBox={`0 0 ${width} ${HEIGHT}`} role="group" aria-label={T.glance.title}>
        {g.bands.map((b) => (
          <g key={b.chapterId} data-band-id={b.chapterId}>
            <rect className={b.dashed ? "glance-band glance-band-dashed" : "glance-band"} x={b.x} y={BAND_TOP} width={b.w} height={GLANCE_BAND_H} />
            {b.ladderY !== null && (
              <line
                className="glance-ladder"
                x1={b.x + Math.min(3, b.w / 4)}
                x2={b.x + b.w - Math.min(3, b.w / 4)}
                y1={BAND_TOP + b.ladderY}
                y2={BAND_TOP + b.ladderY}
              />
            )}
          </g>
        ))}
        {g.marks.map((m) => (
          <g key={m.eventId} className="glance-mark" data-event-id={m.eventId} transform={`translate(${m.x - GLANCE_MARK / 2} ${MARK_TOP})`}>
            <Pictogram name={m.kind} size={16} label={`${CURVE_TEXT.kinds[m.kind]} ${byId.get(m.eventId)!.title}`} />
          </g>
        ))}
        {g.ticks.map((t, i) => (
          <g key={t.label}>
            <line className="glance-tick" x1={t.x} x2={t.x} y1={BAND_TOP + GLANCE_BAND_H} y2={BAND_TOP + GLANCE_BAND_H + 4} />
            <text
              className="glance-tick-label num"
              x={t.x}
              y={AXIS_Y}
              textAnchor={i === 0 ? "start" : i === g.ticks.length - 1 && t.x > width - GLANCE_PAD - 14 ? "end" : "middle"}
            >
              {t.label}
            </text>
          </g>
        ))}
      </svg>
      <table className="visually-hidden">
        <caption>{T.glance.tableCaption}</caption>
        <thead>
          <tr>
            <th scope="col">{T.glance.chapter}</th>
            <th scope="col">{T.glance.years}</th>
            <th scope="col">{T.glance.ladder}</th>
            <th scope="col">{T.glance.events}</th>
          </tr>
        </thead>
        <tbody>
          {h.chapters.map((c) => (
            <tr key={c.id}>
              <th scope="row">{c.title}</th>
              <td>{yearsText(c.start, c.end)}</td>
              <td>{c.ladder ? ladderText(c.ladder.value) : T.glance.noLadder}</td>
              <td>{c.events.length}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </figure>
  );
}
