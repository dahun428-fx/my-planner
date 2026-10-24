import { Fragment, type ReactNode } from "react";
import type { Health, HealthRun } from "../api/types.gen";
import { StateNotice } from "../components/StateNotice";
import { useConnection } from "../lib/ConnectionProvider";
import {
  AUTH_LABELS,
  HEALTH_TEXT as T,
  POLLING_LABELS,
  channelLabel,
  checkinLabel,
  loopLabel,
  runStatusLabel,
} from "../lib/labels";
import { formatKst } from "../lib/time";

type Tone = "positive" | "negative" | "neutral" | "hue";

function Dot({ tone }: { tone: Tone }) {
  return <span className="dot" data-tone={tone} aria-hidden="true" />;
}

/** "a · b · c" where each part keeps its words together (no "푸시 구독 / 1" line breaks at 360 px). */
function Parts({ children }: { children: ReactNode[] }) {
  return (
    <>
      {children.map((part, i) => (
        <Fragment key={i}>
          {i > 0 && " · "}
          <span className="part">{part}</span>
        </Fragment>
      ))}
    </>
  );
}

function future(iso: string | null, now: string): string | null {
  return iso !== null && Date.parse(iso) > Date.parse(now) ? iso : null;
}

/** A usage bar at its true ratio with both ends labelled (taste: "limits and usage"). SVG, no inline style. */
function Meter({ label, value, cap, tone }: { label: string; value: number; cap: number; tone: "ink" | "hue" }) {
  const ratio = cap > 0 ? Math.min(1, Math.max(0, value / cap)) : 0;
  return (
    <div className="meter">
      <div className="meter-head">
        <span>{label}</span>
        <span className="num">
          {value} / {cap}
        </span>
      </div>
      <svg className="meter-bar" viewBox="0 0 100 6" preserveAspectRatio="none" role="img" aria-label={`${label} ${value} / ${cap}`}>
        <rect className="meter-track" x="0" y="0" width="100" height="6" rx="3" />
        {ratio > 0 && <rect className="meter-fill" data-tone={tone} x="0" y="0" width={ratio * 100} height="6" rx="3" />}
      </svg>
    </div>
  );
}

function runTone(run: HealthRun): Tone {
  if (run.status === "done") return "hue"; // the secretary sent it
  if (run.status === "failed" || run.status === "interrupted") return "negative";
  return "neutral";
}

function RunRow({ run }: { run: HealthRun }) {
  const via = run.status === "done" && run.delivered_via.length > 0 ? ` (${run.delivered_via.map(channelLabel).join("·")})` : "";
  const checkin = checkinLabel(run.checkin_state);
  return (
    <li className="run" data-status={run.status}>
      <span className="run-time num">{formatKst(run.scheduled_for, "HH:mm")}</span>
      <span className="run-name">{loopLabel(run.loop)}</span>
      <span className="run-state">
        <Dot tone={runTone(run)} />
        {runStatusLabel(run)}
        {via}
        {checkin && ` · ${checkin}`}
      </span>
    </li>
  );
}

function warningsLine(errors: Health["errors"]): string {
  if (errors.total === 0) return T.noWarnings;
  const parts = Object.entries(errors.by_event)
    .map(([event, n]) => `${event} ${n}`)
    .join(", ");
  return T.warnings(errors.total, parts);
}

export function HealthView({ health: h }: { health: Health }) {
  const limited = future(h.brain.limited_until, h.now);
  const paused = future(h.paused_until, h.now);
  const authOk = h.brain.auth === "ok";
  const pollingOk = h.polling === "running";
  return (
    <div className="panels">
      <section className="panel panel-wide" aria-label={T.title}>
        <p className="row">
          <Parts>{T.version(h.version.app, h.version.api, h.version.schema).split(" · ")}</Parts>
        </p>
        <p className="row">
          <Parts>
            {[
              T.lastTick(h.last_tick_at ? formatKst(h.last_tick_at, "HH:mm") : null),
              <>
                {T.polling} <Dot tone={pollingOk ? "positive" : "negative"} />
                {POLLING_LABELS[h.polling] ?? h.polling}
              </>,
            ]}
          </Parts>
        </p>
        <p className="row">
          <Parts>
            {[
              <>
                {T.login} <Dot tone={authOk ? "positive" : h.brain.auth === "unknown" ? "neutral" : "negative"} />
                {AUTH_LABELS[h.brain.auth] ?? h.brain.auth}
              </>,
              limited ? T.limitedUntil(formatKst(limited, "HH:mm")) : T.noLimit,
            ]}
          </Parts>
        </p>
        <p className="row">
          <Parts>
            {[
              paused ? T.pausedUntil(formatKst(paused, "M/D HH:mm")) : T.noPause,
              T.primary(channelLabel(h.notify.primary), channelLabel(h.notify.effective)),
              T.push(h.push.subscriptions),
            ]}
          </Parts>
        </p>
      </section>

      <section className="panel" aria-labelledby="runs-heading">
        <h2 id="runs-heading">{T.runsHeading}</h2>
        {h.runs_today.length === 0 ? (
          <p className="empty">{T.noRuns}</p>
        ) : (
          <ul className="runs">
            {h.runs_today.map((r) => (
              <RunRow key={r.id} run={r} />
            ))}
          </ul>
        )}
      </section>

      <section className="panel" aria-label={`${T.brainCalls}, ${T.proactive}`}>
        <Meter label={T.brainCalls} value={h.brain.calls_today} cap={h.brain.calls_cap} tone="ink" />
        <Meter label={T.proactive} value={h.proactive.sent_today} cap={h.proactive.cap} tone="hue" />
        <p className="row meta">{warningsLine(h.errors)}</p>
      </section>
    </div>
  );
}

function Loading() {
  return (
    <div className="loading" aria-busy="true">
      <div className="panel skeleton" />
      <div className="panel skeleton" />
      <div className="panel skeleton" />
    </div>
  );
}

/** (a) 비서 상태, spec 13.2: the first screen. Reads the shared `/health` poll. */
export function HealthScreen() {
  const { ready, conn, health } = useConnection();
  return (
    <>
      <h1>{T.title}</h1>
      {!ready || !conn || health === null ? <Loading /> : health.kind === "ok" ? <HealthView health={health.data} /> : <StateNotice result={health} />}
    </>
  );
}

export default HealthScreen;
