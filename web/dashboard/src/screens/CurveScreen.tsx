import { useCallback, useEffect, useRef, useState } from "react";
import type { Curve, CurveMilestone } from "../api/types.gen";
import { AreaRadar } from "../components/AreaRadar";
import { CurveChart } from "../components/CurveChart";
import { MilestonePopover } from "../components/MilestonePopover";
import { Reassurance } from "../components/Reassurance";
import { StateNotice } from "../components/StateNotice";
import { type ApiResult, fetchApi, isCurve } from "../lib/api";
import { useConnection } from "../lib/ConnectionProvider";
import type { Zoom } from "../lib/curveLayout";
import { CURVE_TEXT as T } from "../lib/labels";
import { usePolling } from "../lib/polling";

const NONE = { kind: "broken", code: "no_connection" } as const;
const ZOOMS: Zoom[] = ["day", "week", "month", "quarter", "year"];

/**
 * The year zoom asks from here. Its BE default starts at the earliest chapter (6.3.5), which would leave out
 * a milestone remembered from before any chapter; the chart then starts at the year of its earliest data.
 */
export const YEAR_FROM = "1900-01-01";

export function curvePath(zoom: Zoom, sensitive: boolean): string {
  const q = new URLSearchParams({ zoom });
  if (zoom === "year") q.set("from", YEAR_FROM);
  if (sensitive) q.set("include_sensitive", "true");
  return `/curve?${q.toString()}`;
}

// "민감한 사건 보기" lasts only while this tab has the dashboard open (13.4): module memory, never storage.
// Leaving for another screen and coming back keeps it; a reload or a new tab starts with it off.
const memory: { zoom: Zoom; sensitive: boolean } = { zoom: "month", sensitive: false };

/** For tests: start again as a fresh tab would. */
export function resetCurveMemory() {
  memory.zoom = "month";
  memory.sensitive = false;
}

function Loading() {
  return (
    <div aria-busy="true">
      <div className="panel skeleton tall" />
      <div className="panel skeleton short" />
    </div>
  );
}

/**
 * `wideAreas` are the area scores of the wide (year, from 1900) request: the radar compares the latest scored
 * quarter with the one before it whatever zoom is shown (13.4). Until that answer is in, the zoom's own `areas`.
 */
export function CurveView({ curve: c, wideAreas = null }: { curve: Curve; wideAreas?: Curve["areas"] | null }) {
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const selected = c.milestones.find((m) => m.id === selectedId) ?? null;
  const close = useCallback(() => {
    setSelectedId((id) => {
      if (id !== null) document.querySelector<SVGGElement>(`.curve-marker[data-milestone-id="${id}"]`)?.focus();
      return null;
    });
  }, []);
  const select = useCallback((m: CurveMilestone) => setSelectedId((id) => (id === m.id ? null : m.id)), []);

  const noEvents = c.chapters.length === 0 && c.milestones.length === 0;
  const noLadder = c.ladder.every((l) => l.now === null); // five-years-ahead alone draws no "now" line
  const noCondition = c.condition.every((b) => b.average === null);
  const drawn = !(noEvents && noLadder && noCondition);

  return (
    <>
      <section className="panel curve-panel" aria-label={T.title}>
        {drawn && <CurveChart curve={c} selected={selected?.id ?? null} onSelect={select} />}
        {selected && <MilestonePopover milestone={selected} onClose={close} />}
        {(noEvents || noLadder) && (
          <div className="curve-empty">
            {noEvents && <p className="empty">{T.empty.events}</p>}
            {noLadder && <p className="empty">{T.empty.ladder}</p>}
          </div>
        )}
      </section>
      <div className="curve-pair">
        <AreaRadar areas={wideAreas ?? c.areas} />
        <Reassurance items={c.reassurance} />
      </div>
    </>
  );
}

interface Loaded {
  path: string;
  curve: Curve;
}

const isLoaded = (r: ApiResult<Curve>, path: string): ApiResult<Loaded> => (r.kind === "ok" ? { kind: "ok", data: { path, curve: r.data } } : r);

/** The wide request: the year zoom from `YEAR_FROM`, without sensitive milestones (they do not touch areas). */
const WIDE_PATH = curvePath("year", false);

/**
 * (c) 인생곡선, spec 13.4: `GET /curve?zoom=<z>` for the chosen zoom, plus one wide `GET` (`WIDE_PATH`) the
 * radar reads its quarters from. When the chosen zoom is that same request, the wide answer is reused.
 * Read only.
 */
export function CurveScreen() {
  const { ready, conn } = useConnection();
  const [zoom, setZoomState] = useState<Zoom>(memory.zoom);
  const [sensitive, setSensitiveState] = useState(memory.sensitive);
  const path = curvePath(zoom, sensitive);
  const auth = ready && conn ? `${conn.beUrl}\n${conn.token}` : "";

  const wideLoad = useCallback(async (): Promise<ApiResult<Curve>> => (conn ? fetchApi(conn, WIDE_PATH, isCurve) : NONE), [conn]);
  const wide = usePolling(wideLoad, 60_000, auth);
  const wideRef = useRef(wide.result);
  wideRef.current = wide.result;

  const load = useCallback(async (): Promise<ApiResult<Loaded>> => {
    if (!conn) return NONE;
    const cached = wideRef.current;
    if (path === WIDE_PATH && cached?.kind === "ok") return isLoaded(cached, path);
    return isLoaded(await fetchApi(conn, path, isCurve), path);
  }, [conn, path]);
  const { result } = usePolling(load, 60_000, auth ? `${auth}\n${path}` : "");

  useEffect(() => {
    memory.zoom = zoom;
    memory.sensitive = sensitive;
  }, [zoom, sensitive]);

  // Only the answer to the request the controls show is drawn (not an older zoom or sensitive setting).
  const shown = result?.kind === "ok" && result.data.path !== path ? null : result;
  const wideAreas = wide.result?.kind === "ok" ? wide.result.data.areas : null;

  return (
    <>
      <h1>{T.title}</h1>
      <div className="curve-controls">
        <div className="zoom-row">
          <span className="zoom-label meta" aria-hidden="true">
            {T.zoomLabel}
          </span>
          <div className="tabs zooms" role="group" aria-label={T.zoomLabel}>
            {ZOOMS.map((z) => (
              <button key={z} type="button" className="tab" aria-pressed={z === zoom} onClick={() => setZoomState(z)}>
                {T.zooms[z]}
              </button>
            ))}
          </div>
        </div>
        <label className="check">
          <input type="checkbox" checked={sensitive} onChange={(e) => setSensitiveState(e.target.checked)} />
          <span>{T.sensitive}</span>
        </label>
      </div>
      {!ready || !conn || shown === null ? <Loading /> : shown.kind === "ok" ? <CurveView curve={shown.data.curve} wideAreas={wideAreas} /> : <StateNotice result={shown} />}
    </>
  );
}

export default CurveScreen;
