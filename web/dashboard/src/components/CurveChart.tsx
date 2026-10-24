import { type KeyboardEvent, type MouseEvent, useMemo } from "react";
import { CartesianGrid, ComposedChart, Line, ReferenceArea, ReferenceLine, Scatter, XAxis, YAxis } from "recharts";
import type { Curve, CurveMilestone } from "../api/types.gen";
import {
  axisTicks,
  thinTicks,
  type ChapterBand,
  chapterBands,
  conditionSeries,
  dayEnd,
  dayStart,
  ladderSeries,
  ladderSteps,
  markerRows,
  nearestIndex,
  milestoneX,
  visibleRange,
} from "../lib/curveLayout";
import { CURVE_TEXT as T } from "../lib/labels";
import { useWidth } from "../lib/useWidth";
import { formatMilestoneDate } from "./MilestonePopover";

// The 0~10 plot (ladder, condition), then a lane for milestones and a strip for chapters above it.
const Y_MAX = 13;
const LANE_Y = 11.05;
const STRIP = [12, 13] as const;
const Y_TICKS = [0, 5, 10];
const CHAR_PX = 13.5; // a Korean glyph at the 13 px strip label (label role), a little generous
const MARGIN = { top: 2, right: 12, bottom: 0, left: 0 };
const X_AXIS_H = 24;
const Y_AXIS_W = 24;
const GLYPH_GAP = 14; // px: closer centres than this go on alternate rows above and below the lane
const ROW_PX = 7; // how far a crowded marker moves off the lane
const TAP_PX = 22; // a tap opens the nearest marker centre within this distance: a 44px target

interface Marker {
  x: number;
  m: CurveMilestone;
}

/** ▲ high, ▼ low, ◆ turning point, as paths (font glyphs differ per device). Hollow when only estimated. */
function glyphPath(kind: CurveMilestone["kind"], cx: number, cy: number): string {
  const r = 6;
  if (kind === "high") return `M${cx} ${cy - r}L${cx + r} ${cy + r * 0.75}L${cx - r} ${cy + r * 0.75}Z`;
  if (kind === "low") return `M${cx} ${cy + r}L${cx + r} ${cy - r * 0.75}L${cx - r} ${cy - r * 0.75}Z`;
  return `M${cx} ${cy - r}L${cx + r} ${cy}L${cx} ${cy + r}L${cx - r} ${cy}Z`;
}

/**
 * A milestone as a button (13.4: tap for details) for the keyboard and screen readers. Drawn over the chart
 * rather than inside Recharts, so the element stays the same across renders and keeps focus. Pointer taps
 * go to the lane's tap layer, which opens the marker whose centre is nearest (`nearestIndex`).
 */
function MilestoneMarker({
  m,
  cx,
  cy,
  selected,
  onSelect,
}: {
  m: CurveMilestone;
  cx: number;
  cy: number;
  selected: boolean;
  onSelect: (m: CurveMilestone) => void;
}) {
  const open = () => onSelect(m);
  const onKey = (e: KeyboardEvent<SVGGElement>) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      open();
    }
  };
  return (
    <g
      className="curve-marker"
      role="button"
      tabIndex={0}
      aria-label={T.milestoneButton(T.kinds[m.kind], formatMilestoneDate(m.date, m.precision), m.title)}
      aria-pressed={selected}
      data-kind={m.kind}
      data-estimate={m.certainty === "estimate" || undefined}
      data-sensitive={m.sensitive || undefined}
      data-selected={selected || undefined}
      data-milestone-id={m.id}
      data-cx={cx}
      data-cy={cy}
      onKeyDown={onKey}
    >
      <circle className="curve-marker-hit" cx={cx} cy={cy} r={10} />
      {selected && <circle className="curve-marker-ring" cx={cx} cy={cy} r={11} />}
      <path className="curve-marker-glyph" d={glyphPath(m.kind, cx, cy)} />
    </g>
  );
}

function ChapterLabel({ viewBox, band }: { viewBox?: { x?: number; y?: number; width?: number; height?: number }; band: ChapterBand }) {
  const { x = 0, y = 0, width = 0, height = 0 } = viewBox ?? {};
  const full = `${band.title}${band.sketch ? ` ${band.sketch}` : ""}`;
  const fits = Math.floor((width - 10) / CHAR_PX);
  if (fits < 2) return null;
  const text = full.length <= fits ? full : `${full.slice(0, fits - 1)}…`;
  return (
    <text x={x + 6} y={y + height / 2} dominantBaseline="central" className="curve-chapter-label">
      {text}
    </text>
  );
}

export function CurveChart({
  curve,
  selected,
  onSelect,
}: {
  curve: Curve;
  selected: number | null;
  onSelect: (m: CurveMilestone) => void;
}) {
  const { ref: box, width } = useWidth<HTMLDivElement>();
  const height = width < 480 ? 260 : 320;
  const range = visibleRange(curve);
  const lo = dayStart(range.from);
  const hi = dayEnd(range.to);
  const stepped = curve.zoom === "day" || curve.zoom === "week";

  const { ladder, condition, bands, markers, ticks } = useMemo(() => {
    // The BE sends every milestone that overlaps the range; one whose middle falls outside sits on the edge.
    const markers: Marker[] = curve.milestones.map((m) => ({ x: Math.min(hi - 1, Math.max(lo, milestoneX(m.date, m.precision))), m }));
    return {
      ladder: stepped ? ladderSteps(ladderSeries(curve.ladder, range.from, range.to)) : ladderSeries(curve.ladder, range.from, range.to),
      condition: conditionSeries(curve.condition).filter((p) => p.x >= lo && p.x < hi),
      bands: chapterBands(curve.chapters, range.from, range.to),
      markers,
      ticks: thinTicks(axisTicks(curve.zoom, range.from, range.to), width < 480 ? 5 : 10),
    };
  }, [curve, range.from, range.to, lo, hi, stepped, width]);
  const tickLabel = new Map(ticks.map((t) => [t.x, t.label]));
  // The plot box Recharts lays out from the margin and the axis sizes; milestone buttons sit on it.
  const plot = {
    left: MARGIN.left + Y_AXIS_W,
    top: MARGIN.top,
    width: width - MARGIN.left - Y_AXIS_W - MARGIN.right,
    height: height - MARGIN.top - MARGIN.bottom - X_AXIS_H,
  };
  const laneY = plot.top + (1 - LANE_Y / Y_MAX) * plot.height;
  const xs = markers.map((p) => plot.left + ((p.x - lo) / (hi - lo)) * plot.width);
  const rows = markerRows(xs, GLYPH_GAP);
  const centres = markers.map((p, i) => ({ m: p.m, cx: xs[i], cy: laneY + rows[i] * ROW_PX }));
  const stripBottom = plot.top + (1 - STRIP[0] / Y_MAX) * plot.height;
  const plotTen = plot.top + (1 - 10 / Y_MAX) * plot.height;
  const onTap = (e: MouseEvent<SVGRectElement>) => {
    const box = e.currentTarget.ownerSVGElement?.getBoundingClientRect();
    const i = nearestIndex(centres, e.clientX - (box?.left ?? 0), e.clientY - (box?.top ?? 0), TAP_PX);
    if (i !== null) onSelect(centres[i].m);
  };
  const hasNow = ladder.some((p) => p.now !== null);
  const hasFuture = ladder.some((p) => p.future !== null);

  return (
    <div className="curve" ref={box}>
      <div className="curve-legend meta" aria-hidden="true">
        {hasNow && (
          <span className="curve-key" data-key="now">
            <svg viewBox="0 0 20 8" className="curve-swatch">
              <line x1="1" y1="4" x2="19" y2="4" />
            </svg>
            {T.legendNow}
          </span>
        )}
        {hasFuture && (
          <span className="curve-key" data-key="future">
            <svg viewBox="0 0 20 8" className="curve-swatch">
              <line x1="1" y1="4" x2="19" y2="4" />
            </svg>
            {T.legendFuture}
          </span>
        )}
        {condition.length > 0 && (
          <span className="curve-key" data-key="condition">
            <svg viewBox="0 0 8 8" className="curve-swatch dot">
              <circle cx="4" cy="4" r="3" />
            </svg>
            {T.legendCondition}
          </span>
        )}
      </div>
      <figure className="curve-figure" aria-label={T.chart(range.from, range.to)}>
        <ComposedChart width={width} height={height} margin={MARGIN} accessibilityLayer={false}>
          <CartesianGrid vertical={false} className="curve-grid" />
          <XAxis
            type="number"
            dataKey="x"
            domain={[lo, hi]}
            allowDataOverflow
            ticks={ticks.map((t) => t.x)}
            tickFormatter={(x: number) => tickLabel.get(x) ?? ""}
            tickLine={false}
            axisLine={false}
            interval={0}
            className="curve-axis"
            height={X_AXIS_H}
          />
          <YAxis type="number" domain={[0, Y_MAX]} ticks={Y_TICKS} allowDataOverflow tickLine={false} axisLine={false} width={Y_AXIS_W} className="curve-axis" />
          {bands.map((b) => (
            <ReferenceArea
              key={`band-${b.id}`}
              x1={b.x1}
              x2={b.x2}
              y1={STRIP[0]}
              y2={STRIP[1]}
              className={`curve-band tone-${b.index % 2}${b.estimate ? " estimate" : ""}`}
              ifOverflow="hidden"
              label={(p: { viewBox?: { x?: number; y?: number; width?: number; height?: number } }) => <ChapterLabel viewBox={p.viewBox} band={b} />}
            />
          ))}
          {bands
            .filter((b) => b.x1 > lo)
            .map((b) => (
              <ReferenceLine key={`edge-${b.id}`} x={b.x1} segment={[{ x: b.x1, y: 0 }, { x: b.x1, y: STRIP[1] }]} className="curve-edge" ifOverflow="hidden" />
            ))}
          <Scatter data={condition} dataKey="y" className="curve-condition" isAnimationActive={false} shape={<CondDot />} />
          {hasFuture && (
            <Line
              data={ladder}
              dataKey="future"
              type="linear"
              className="curve-future"
              connectNulls={false}
              isAnimationActive={false}
              dot={stepped ? false : { r: 3, className: "curve-dot-future" }}
              activeDot={false}
            />
          )}
          {hasNow && (
            <Line
              data={ladder}
              dataKey="now"
              type="linear"
              className="curve-now"
              connectNulls={false}
              isAnimationActive={false}
              dot={stepped ? false : { r: 3, className: "curve-dot-now" }}
              activeDot={false}
            />
          )}
        </ComposedChart>
        <svg className="curve-overlay" width={width} height={height} viewBox={`0 0 ${width} ${height}`}>
          {centres.length > 0 && (
            <rect
              className="curve-tap"
              x={plot.left - TAP_PX}
              y={stripBottom}
              width={plot.width + 2 * TAP_PX}
              height={plotTen - stripBottom}
              onClick={onTap}
              aria-hidden="true"
            />
          )}
          {centres.map((p) => (
            <MilestoneMarker key={p.m.id} m={p.m} cx={p.cx} cy={p.cy} selected={selected === p.m.id} onSelect={onSelect} />
          ))}
        </svg>
      </figure>
      <ul className="visually-hidden" aria-label={T.dataList}>
        {bands.map((b) => (
          <li key={`c${b.id}`}>{T.chapterRow(b.title, b.start, b.end)}</li>
        ))}
        {ladder
          .filter((p) => p.now !== null || p.future !== null)
          .map((p) => (
            <li key={`l${p.period}`}>{T.ladderRow(p.period, p.now, p.future)}</li>
          ))}
        {condition.map((p) => (
          <li key={`d${p.bucket}`}>{T.conditionRow(p.bucket, p.average, p.daysLogged)}</li>
        ))}
      </ul>
    </div>
  );
}

function CondDot(props: { cx?: number; cy?: number }) {
  if (props.cx === undefined || props.cy === undefined) return <g />;
  return <circle className="curve-cond-dot" cx={props.cx} cy={props.cy} r={3} />;
}
