import Link from "next/link";
import { useEffect } from "react";
import { useAction } from "../api/actions";
import { apiGet } from "../api/client";
import type { AxisScoreOut, Standing as StandingData, StandingAxis, StandingMarket, StandingMeasure, StandingMeasures } from "../api/types.gen";
import { BlockError } from "../components/BlockError";
import { Group } from "../components/Group";
import { LargeTitle } from "../components/LargeTitle";
import { OfflineNotice } from "../components/OfflineNotice";
import { Skeleton } from "../components/Skeleton";
import { useToast } from "../components/Toast";
import { useConnection } from "../lib/ConnectionProvider";
import { copy } from "../lib/copy";
import { standingCopy } from "../lib/copyStanding";
import { usePolling } from "../lib/polling";
import page from "../styles/page.module.css";
import styles from "./Standing.module.css";

const T = standingCopy;
const MARKETS = ["marriage", "career"] as const;

const metricLabel = (metric: string) => T.metrics[metric] ?? metric;

/** A measure's value as the list writes it: money in 만 원, a choice by its name (spec 6.2, 10.3). */
export function measureValue(m: Pick<StandingMeasure, "metric" | "value_num" | "value_text" | "unit">): string {
  if (m.value_num !== null) return m.metric.endsWith("_krw") ? T.krw(m.value_num) : `${String(m.value_num)}${m.unit ?? ""}`;
  const v = m.value_text ?? "";
  if (m.metric === "cert") {
    if (v.startsWith("toeic:")) return T.toeic(v.slice(6));
    if (v.startsWith("other:")) return v.slice(6);
  }
  return T.values[m.metric]?.[v] ?? v;
}

function Markets({ data }: { data: StandingData }) {
  const axisLabel = (axis: string) => data.axes.find((a) => a.axis === axis)?.label ?? axis;
  const row = (name: (typeof MARKETS)[number], m: StandingMarket) => (
    <li key={name} className={styles.row}>
      <div className={styles.head}>
        <span className={styles.name}>{T.markets[name]}</span>
        <span className={styles.scores}>
          <span className={styles.score}>{T.national(m.national)}</span>
          <span className={styles.peer}>{T.peer(m.peer)}</span>
        </span>
      </div>
      {name === "marriage" && <span className={styles.meta}>{T.marriageNote}</span>}
      {m.excluded.length > 0 && <span className={styles.meta}>{T.excluded(m.excluded.map(axisLabel).join(", "))}</span>}
    </li>
  );
  return (
    <Group heading={T.marketsHeading}>
      <ul className={styles.list}>{MARKETS.map((n) => row(n, data.markets[n]))}</ul>
    </Group>
  );
}

// The radar (DESIGN.md 대시보드 레이더): rings in --rule, the national cohort 1.5px --text, the peer
// cohort 1px dashed --muted. Drawing attributes only: the CSP has no inline style attribute.
const SIZE = 320;
const C = SIZE / 2;
const R = 104;
const at = (i: number, n: number, r: number): [number, number] => {
  const a = (Math.PI * 2 * i) / n - Math.PI / 2;
  return [C + r * Math.cos(a), C + r * Math.sin(a)];
};
/**
 * A cohort's outline as a path: an edge is drawn only between two neighbouring axes that both have a
 * score, so an axis with none is a gap in the line (never a point pulled to the centre as 0).
 */
export function cohortPath(values: (number | null)[]): string {
  const n = values.length;
  const p = (i: number) => at(i, n, (Math.max(0, Math.min(100, values[i] as number)) / 100) * R).map((x) => x.toFixed(1)).join(" ");
  const all = values.every((v) => v !== null);
  const parts: string[] = [];
  for (let i = 0; i < n; i++) {
    const j = (i + 1) % n;
    if (values[i] === null || values[j] === null) continue;
    parts.push(`M${p(i)} L${p(j)}`);
  }
  // A lone scored axis between two gaps still gets a mark: a zero-length segment with round caps.
  values.forEach((v, i) => {
    if (v !== null && values[(i + n - 1) % n] === null && values[(i + 1) % n] === null) parts.push(`M${p(i)} L${p(i)}`);
  });
  return all ? `M${values.map((_, i) => p(i)).join(" L")} Z` : parts.join(" ");
}
const pts = (values: number[]) => values.map((v, i) => at(i, values.length, (Math.max(0, Math.min(100, v)) / 100) * R).map((x) => x.toFixed(1)).join(",")).join(" ");

function Radar({ axes }: { axes: StandingAxis[] }) {
  const n = axes.length;
  const ring = (f: number) => pts(axes.map(() => f * 100));
  return (
    <Group heading={T.radarHeading}>
      <div className={styles.radarBox}>
        <svg className={styles.radar} viewBox={`0 0 ${SIZE} ${SIZE}`} role="img" aria-label={T.radarLabel}>
          {[0.25, 0.5, 0.75, 1].map((f) => (
            <polygon key={f} className={styles.ring} points={ring(f)} />
          ))}
          {axes.map((a, i) => {
            const [x, y] = at(i, n, R);
            return <line key={a.axis} data-axis={a.axis} className={styles.spoke} x1={C} y1={C} x2={x.toFixed(1)} y2={y.toFixed(1)} />;
          })}
          <path data-cohort="peer" className={styles.peerLine} d={cohortPath(axes.map((a) => a.peer?.score ?? null))} />
          <path data-cohort="national" className={styles.nationalLine} d={cohortPath(axes.map((a) => a.national?.score ?? null))} />
          {axes.map((a, i) => {
            const [x, y] = at(i, n, R + 16);
            const anchor = Math.abs(x - C) < 4 ? "middle" : x > C ? "start" : "end";
            return (
              <text key={a.axis} className={styles.axisText} x={x.toFixed(1)} y={y.toFixed(1)} textAnchor={anchor} dominantBaseline="middle">
                {a.label}
              </text>
            );
          })}
        </svg>
        <p className={styles.legend}>
          <span className={styles.keyNational} aria-hidden="true" />
          {T.legendNational}
          <span className={styles.keyPeer} aria-hidden="true" />
          {T.legendPeer}
        </p>
      </div>
    </Group>
  );
}

function AxisBar({ s }: { s: AxisScoreOut }) {
  return (
    <svg className={styles.axisBar} viewBox="0 0 100 10" preserveAspectRatio="none" aria-hidden="true">
      <rect className={styles.track} x="0" y="3" width="100" height="4" rx="2" />
      {s.score > 0 && <rect data-part="fill" className={styles.fill} x="0" y="3" width={s.score} height="4" rx="2" />}
      <rect data-part="band" className={styles.band} x={s.low} y="1" width={Math.max(0, s.high - s.low)} height="8" rx="1" />
    </svg>
  );
}

function Axes({ axes }: { axes: StandingAxis[] }) {
  return (
    <Group heading={T.axesHeading}>
      <ul className={styles.list}>
        {axes.map((a) => {
          const s = a.national;
          const peer = a.peer?.score ?? null;
          const meta = s ? [T.band(s.low, s.high), T.reliability[s.reliability], s.estimate ? T.estimate : "", s.measured_on ? T.measuredOn(s.measured_on) : ""].filter(Boolean).join(" · ") : T.noScore;
          return (
            <li key={a.axis} className={styles.row} data-axis={a.axis}>
              <div className={styles.head}>
                <span className={styles.name}>{a.label}</span>
                {s && (
                  <span className={styles.scores}>
                    <span className={styles.score}>{s.score}</span>
                    {peer !== null && peer !== s.score && <span className={styles.peer}>{T.peer(peer)}</span>}
                  </span>
                )}
              </div>
              {s && <AxisBar s={s} />}
              <span className={styles.meta}>{meta}</span>
              {s && s.missing.length > 0 && (
                <>
                  <span className={styles.meta}>{T.missing(s.missing.map(metricLabel).join(", "))}</span>
                  <span className={styles.meta}>{T.assumedNote}</span>
                </>
              )}
            </li>
          );
        })}
      </ul>
    </Group>
  );
}

function Measures({ list, onDelete, pending }: { list: StandingMeasure[]; onDelete(m: StandingMeasure): void; pending(id: number): boolean }) {
  return (
    <Group heading={T.measuresHeading}>
      {list.length === 0 ? (
        <p className={styles.empty}>{T.measuresEmpty}</p>
      ) : (
        <ul className={styles.list}>
          {list.map((m) => (
            <li key={m.id} className={styles.measure} data-metric={m.metric}>
              <span className={styles.text}>
                <span className={styles.name}>{m.label}</span>
                <span className={styles.meta}>{T.measureMeta(m.measured_on, T.sources[m.source_kind])}</span>
              </span>
              <span className={styles.value}>{measureValue(m)}</span>
              <button type="button" className={styles.delete} aria-label={T.deleteLabel(m.label)} disabled={pending(m.id)} onClick={() => onDelete(m)}>
                {T.delete}
              </button>
            </li>
          ))}
        </ul>
      )}
    </Group>
  );
}

// SP13 10.3 `/status/standing/`: markets, the radar, each axis, and the measures behind them.
// Off the tabs, reached from the status screen; like the status screen it is not kept offline.
export function Standing() {
  const { state, recheck } = useConnection();
  const toast = useToast();
  const { run, isPending } = useAction();
  const standing = usePolling<StandingData>(() => apiGet<StandingData>("/standing", "Standing"));
  const measures = usePolling<StandingMeasures>(() => apiGet<StandingMeasures>("/standing/measures", "StandingMeasures"));
  const refresh = standing.refresh;
  const refreshMeasures = measures.refresh;
  const offline = state?.kind === "offline" || standing.result?.kind === "offline";

  useEffect(() => toast.onUndone(() => void Promise.all([refresh(), refreshMeasures()])), [toast, refresh, refreshMeasures]);

  const remove = async (m: StandingMeasure) => {
    const out = await run("delete_measure", { id: m.id });
    if (out?.kind === "applied") await Promise.all([refresh(), refreshMeasures()]);
  };

  const s = standing.result;
  const l = measures.result;
  let body;
  if (offline) {
    body = <p className={styles.empty}>{copy.statusScreen.offline}</p>;
  } else if (s === null) {
    body = (
      <Group>
        <Skeleton size="row" />
        <Skeleton size="row" />
      </Group>
    );
  } else if (s.kind !== "ok") {
    body = (
      <Group>
        <BlockError code={s.kind === "error" ? s.code : s.kind} onRetry={() => void refresh()} />
      </Group>
    );
  } else {
    body = (
      <>
        <Markets data={s.data} />
        <Radar axes={s.data.axes} />
        <Axes axes={s.data.axes} />
        {l === null ? null : l.kind === "ok" ? (
          <Measures list={l.data.measures} pending={(id) => isPending("delete_measure", { id })} onDelete={(m) => void remove(m)} />
        ) : (
          <Group heading={T.measuresHeading}>
            <BlockError code={l.kind === "error" ? l.code : l.kind} onRetry={() => void refreshMeasures()} />
          </Group>
        )}
      </>
    );
  }

  return (
    <main className={`${page.main} ${styles.main}`}>
      <nav className={styles.nav}>
        <Link href="/status/" className={styles.back}>
          {T.back}
        </Link>
      </nav>
      <LargeTitle title={T.title} />
      {offline && <OfflineNotice savedAt={null} onRetry={() => void recheck()} />}
      {body}
    </main>
  );
}
