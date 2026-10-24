import { useId } from "react";
import { PolarAngleAxis, PolarGrid, PolarRadiusAxis, Radar, RadarChart } from "recharts";
import type { CurveAreas } from "../api/types.gen";
import { type RadarRow, radarRows } from "../lib/curveLayout";
import { CURVE_TEXT as T } from "../lib/labels";
import { useWidth } from "../lib/useWidth";

interface TickProps {
  x?: number | string;
  y?: number | string;
  textAnchor?: "start" | "end" | "middle" | "inherit";
  payload?: { value?: string };
}

interface DotProps {
  cx?: number;
  cy?: number;
  payload?: { area?: string; now?: number | null };
}

/** A vertex of this quarter: an area dot (DESIGN.md: area colours are dots and lines, never fills). */
function AreaDot({ cx, cy, payload }: DotProps) {
  if (cx === undefined || cy === undefined || payload?.now === null || payload?.now === undefined) return <g />;
  return <circle className="radar-dot" data-area={payload.area} cx={cx} cy={cy} r={4} />;
}

/**
 * Area radar (13.4): the latest quarter solid, the quarter right before it dashed, ↓ beside an area that went
 * down. A missing area has no vertex (the polygon skips it, it is not 0). Values are also a list for readers.
 * With no scored quarter yet, `emptyText` says on which day the scores come (DU-05).
 */
export function AreaRadar({ areas, emptyText }: { areas: CurveAreas[]; emptyText: string }) {
  const headingId = useId();
  const { ref: box, width } = useWidth<HTMLDivElement>(296);
  const { latest, previous, rows } = radarRows(areas);
  const byLabel = new Map<string, RadarRow>(rows.map((r) => [r.label, r]));
  const size = Math.min(width, 320);

  const Tick = ({ x = 0, y = 0, textAnchor = "middle", payload }: TickProps) => {
    const row = payload?.value ? byLabel.get(payload.value) : undefined;
    if (!row) return <g />;
    return (
      <text
        x={Number(x)}
        y={Number(y)}
        textAnchor={textAnchor}
        dominantBaseline="central"
        className="radar-tick"
        data-area={row.area}
        data-down={row.down || undefined}
      >
        {row.label}
        <tspan className="radar-tick-value num"> {row.now ?? "—"}</tspan>
        {row.down && <tspan className="radar-down"> ↓</tspan>}
      </text>
    );
  };

  return (
    <section className="panel radar-panel" aria-labelledby={headingId}>
      <h2 id={headingId}>{latest ? T.areas(latest, previous) : T.areasTitle}</h2>
      {latest === null ? (
        <p className="empty">{emptyText}</p>
      ) : (
        <div className="radar" ref={box}>
          <div aria-hidden="true" className="radar-figure">
            <RadarChart
              width={size}
              height={Math.round(size * 0.82)}
              data={rows}
              outerRadius="66%"
              margin={{ top: 4, right: 8, bottom: 4, left: 8 }}
              accessibilityLayer={false}
            >
              <PolarGrid className="radar-grid" gridType="polygon" />
              <PolarAngleAxis dataKey="label" tick={Tick} tickLine={false} axisLine={false} />
              <PolarRadiusAxis domain={[0, 10]} tick={false} axisLine={false} tickCount={3} />
              {previous && <Radar dataKey="prev" className="radar-prev" connectNulls isAnimationActive={false} dot={false} />}
              <Radar dataKey="now" className="radar-now" connectNulls isAnimationActive={false} dot={AreaDot} />
            </RadarChart>
          </div>
          <ul className="visually-hidden">
            {rows.map((r) => (
              <li key={r.area}>{T.areaRow(r.label, r.now, r.prev, previous, r.down)}</li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}
