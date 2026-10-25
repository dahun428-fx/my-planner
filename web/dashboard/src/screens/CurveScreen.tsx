import { useRouter } from "next/router";
import { useCallback, useEffect, useRef, useState } from "react";
import type { Curve, CurveHistory, CurveMilestone } from "../api/types.gen";
import { AreaRadar } from "../components/AreaRadar";
import { CurveChart } from "../components/CurveChart";
import { MilestonePopover } from "../components/MilestonePopover";
import { Reassurance } from "../components/Reassurance";
import { StateNotice } from "../components/StateNotice";
import { Pictogram } from "../components/pictograms.gen";
import { Upcoming, type UpcomingMark } from "../components/Upcoming";
import { type ApiResult, fetchApi, isCurve, isCurveHistory } from "../lib/api";
import { useConnection } from "../lib/ConnectionProvider";
import type { Zoom } from "../lib/curveLayout";
import { memory, resetMemory } from "../lib/curveMemory";
import { CURVE_TEXT as T, HISTORY_TEXT as H } from "../lib/labels";
import { useIsPhone } from "../lib/useIsPhone";
import { HistoryView } from "./HistoryView";
import { usePolling } from "../lib/polling";
import { nextMonthlyReview, nextQuarterReview, reviewDayLabel, seoulLogicalToday } from "../lib/reviews";

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

/** For tests: start again as a fresh tab would. */
export function resetCurveMemory() {
  resetMemory();
}

function Loading() {
  return (
    <div aria-busy="true">
      <div className="panel skeleton tall" />
      <div className="panel skeleton short" />
    </div>
  );
}

const hasLadder = (c: Curve) => c.ladder.some((l) => l.now !== null); // five-years-ahead alone draws no "now" line

/**
 * `wide` is the answer to the wide (year, from 1900) request. The radar compares the latest scored quarter with
 * the one before it, and 안심 보기 lists every compared month, whatever zoom is shown (13.4, B2). It also says
 * whether a ladder score exists at all, so an empty zoom does not call the next one the first. Until that
 * answer is in, the zoom's own answer stands in for it.
 * The empty curve shows the next review days (DU-05), worked out from the logical date in Korea (04:00 turn).
 */
export function CurveView({ curve: c, wide = null }: { curve: Curve; wide?: Curve | null }) {
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
  const noLadder = !hasLadder(c);
  const noCondition = c.condition.every((b) => b.average === null);
  const drawn = !(noEvents && noLadder && noCondition);

  const all = wide ?? c;
  const areas = all.areas;
  const firstLadder = !hasLadder(all);
  const today = seoulLogicalToday();
  const ladderDay = nextMonthlyReview(today);
  const areasDay = nextQuarterReview(today);
  // The month the next review asks for is already scored (11.1 skips step 1 then): nothing to promise.
  const asked = ladderDay.slice(0, 7);
  const alreadyScored = all.ladder.some((l) => l.period === asked && l.now !== null);
  const askLadder = noLadder && !alreadyScored;
  const marks: UpcomingMark[] = [];
  if (askLadder) marks.push({ day: ladderDay, what: firstLadder ? T.upcoming.firstLadderMark : T.upcoming.ladderMark });
  if (askLadder && areas.length === 0) marks.push({ day: areasDay, what: T.upcoming.areasMark });
  const ladderLine = (firstLadder ? T.upcoming.firstLadder : T.upcoming.ladder)(reviewDayLabel(ladderDay));

  return (
    <>
      <section className="panel curve-panel" aria-label={T.title}>
        {drawn && <CurveChart curve={c} selected={selected?.id ?? null} onSelect={select} />}
        {selected && <MilestonePopover milestone={selected} onClose={close} />}
        {(noEvents || askLadder) && (
          <div className="curve-empty">
            {noEvents && <p className="empty">{T.empty.events}</p>}
            {askLadder && (
              <>
                <Upcoming marks={marks} />
                <p className="empty">{ladderLine}</p>
              </>
            )}
          </div>
        )}
      </section>
      <div className="curve-pair">
        <AreaRadar areas={areas} emptyText={T.upcoming.areas(reviewDayLabel(areasDay))} />
        <Reassurance items={all.reassurance} />
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
function CurvePane() {
  const { ready, conn, backOnline } = useConnection();
  const [zoom, setZoomState] = useState<Zoom>(memory.zoom);
  const [sensitive, setSensitiveState] = useState(memory.sensitive);
  const path = curvePath(zoom, sensitive);
  const auth = ready && conn ? `${conn.beUrl}\n${conn.token}` : "";

  const wideLoad = useCallback(async (): Promise<ApiResult<Curve>> => (conn ? fetchApi(conn, WIDE_PATH, isCurve) : NONE), [conn]);
  const wide = usePolling(wideLoad, 60_000, auth, { wake: backOnline });
  const wideRef = useRef(wide.result);
  wideRef.current = wide.result;

  const load = useCallback(async (): Promise<ApiResult<Loaded>> => {
    if (!conn) return NONE;
    const cached = wideRef.current;
    if (path === WIDE_PATH && cached?.kind === "ok") return isLoaded(cached, path);
    return isLoaded(await fetchApi(conn, path, isCurve), path);
  }, [conn, path]);
  const { result } = usePolling(load, 60_000, auth ? `${auth}\n${path}` : "", { wake: backOnline });

  useEffect(() => {
    memory.zoom = zoom;
    memory.sensitive = sensitive;
  }, [zoom, sensitive]);

  // Only the answer to the request the controls show is drawn (not an older zoom or sensitive setting).
  const shown = result?.kind === "ok" && result.data.path !== path ? null : result;
  const wideCurve = wide.result?.kind === "ok" ? wide.result.data : null;

  return (
    <>
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
      {!ready || !conn || shown === null ? <Loading /> : shown.kind === "ok" ? <CurveView curve={shown.data.curve} wide={wideCurve} /> : <StateNotice result={shown} />}
    </>
  );
}

type Tab = "curve" | "history";
const tabFrom = (q: unknown): Tab => (q === "history" ? "history" : "curve");

/**
 * 히스토리 탭 (SP8 8.3): `GET /curve/history`, with sensitive events only while "민감한 사건 보기" is on in this
 * tab (the same state as the curve's). Read only.
 */
function HistoryPane() {
  const { ready, conn, backOnline } = useConnection();
  const path = memory.sensitive ? "/curve/history?include_sensitive=true" : "/curve/history";
  const auth = ready && conn ? `${conn.beUrl}\n${conn.token}` : "";
  const load = useCallback(async (): Promise<ApiResult<CurveHistory>> => (conn ? fetchApi(conn, path, isCurveHistory) : NONE), [conn, path]);
  const { result } = usePolling(load, 60_000, auth ? `${auth}\n${path}` : "", { wake: backOnline });
  const isPhone = useIsPhone();
  return (
    <div>
      {!ready || !conn || result === null ? <Loading /> : result.kind === "ok" ? <HistoryView history={result.data} isPhone={isPhone} /> : <StateNotice result={result} />}
    </div>
  );
}

/**
 * (c) 인생곡선 with its two tabs `곡선 | 히스토리`. The chosen tab is kept in the address (`?tab=history`), so a
 * reload shows the same tab; the curve is the default.
 */
export function CurveScreen() {
  const router = useRouter();
  const queryTab = router.isReady ? tabFrom(router.query.tab) : null;
  const [tab, setTab] = useState<Tab>(queryTab ?? "curve");
  useEffect(() => {
    if (queryTab !== null) setTab(queryTab);
  }, [queryTab]);
  const choose = (next: Tab) => {
    setTab(next);
    void router.replace({ query: { tab: next } }, undefined, { shallow: true });
  };
  return (
    <>
      <h1>{T.title}</h1>
      <div className="tabs curve-tabs" role="group" aria-label={H.tabsLabel}>
        {(["curve", "history"] as const).map((id) => (
          <button key={id} type="button" className="tab with-icon" aria-pressed={id === tab} onClick={() => choose(id)}>
            <Pictogram name={id === "curve" ? "curve" : "list"} size={16} />
            {H.tabs[id]}
          </button>
        ))}
      </div>
      {!router.isReady ? <Loading /> : tab === "history" ? <HistoryPane /> : <CurvePane />}
    </>
  );
}

export default CurveScreen;
