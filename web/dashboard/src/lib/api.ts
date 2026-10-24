// The browser calls the BE directly (ADR 0008). One result type for every screen, mapped from the
// common states table of spec 13.1. Shapes are checked by hand: a field the BE adds later is ignored,
// a field a screen needs that is missing or of the wrong type is `broken("shape")`.
import type { Health, SafeModeHealth } from "../api/types.gen";
import type { Conn } from "./connection";

export type ApiResult<T> =
  | { kind: "ok"; data: T }
  | { kind: "offline" }
  | { kind: "unauthorized" }
  | { kind: "rate_limited" }
  | { kind: "safe_mode" }
  | { kind: "broken"; code: string };

export const TIMEOUT_MS = 10_000;

export interface FetchOpts {
  signal?: AbortSignal;
}

export async function fetchApi<T>(conn: Conn, path: string, isT: (v: unknown) => v is T, opts: FetchOpts = {}): Promise<ApiResult<T>> {
  const ac = new AbortController();
  const timer = setTimeout(() => ac.abort(), TIMEOUT_MS);
  const onAbort = () => ac.abort();
  opts.signal?.addEventListener("abort", onAbort);
  if (opts.signal?.aborted) ac.abort();
  try {
    let res: Response;
    try {
      res = await fetch(`${conn.beUrl}/api/v1${path}`, {
        method: "GET",
        headers: { Authorization: `Bearer ${conn.token}`, Accept: "application/json" },
        signal: ac.signal,
        cache: "no-store",
        credentials: "omit",
        referrerPolicy: "no-referrer",
      });
    } catch {
      return { kind: "offline" }; // network failure, or no answer within 10 s (spec 13.1)
    }
    if (res.status === 401) return { kind: "unauthorized" };
    if (res.status === 429) return { kind: "rate_limited" };

    let body: unknown;
    let parsed = true;
    try {
      body = await res.json();
    } catch {
      // The 10 s timer can fire after the headers, while the body is still coming: that is "off".
      if (ac.signal.aborted) return { kind: "offline" };
      parsed = false;
    }
    if (!res.ok) {
      const e = isObj(body) && isObj(body.error) ? body.error : null;
      const code = e && typeof e.code === "string" && /^[a-z0-9_]{1,40}$/.test(e.code) ? e.code : `http_${res.status}`;
      if (res.status === 503 && code === "safe_mode") return { kind: "safe_mode" };
      return { kind: "broken", code };
    }
    if (!parsed || !isT(body)) return { kind: "broken", code: "shape" };
    return { kind: "ok", data: body };
  } finally {
    clearTimeout(timer);
    opts.signal?.removeEventListener("abort", onAbort);
  }
}

/** `/health` answers 200 with Health, or with `{status: "safe_mode"}` in DB safe mode (6.3.1). */
export async function getHealth(conn: Conn, opts?: FetchOpts): Promise<ApiResult<Health>> {
  const r = await fetchApi(conn, "/health", (v): v is Health | SafeModeHealth => isHealth(v) || isSafeModeHealth(v), opts);
  if (r.kind !== "ok") return r;
  return isSafeModeHealth(r.data) ? { kind: "safe_mode" } : { kind: "ok", data: r.data };
}

// ---- hand checkers ---------------------------------------------------------------------------

type Obj = Record<string, unknown>;
const isObj = (v: unknown): v is Obj => typeof v === "object" && v !== null && !Array.isArray(v);
const str = (v: unknown): v is string => typeof v === "string";
const int = (v: unknown): v is number => typeof v === "number" && Number.isInteger(v);
const strOrNull = (v: unknown) => v === null || str(v);
const intOrNull = (v: unknown) => v === null || int(v);

function isVersion(v: unknown): boolean {
  return isObj(v) && str(v.app) && str(v.api) && intOrNull(v.schema) && str(v.ui_catalog);
}

function isRun(v: unknown): boolean {
  return (
    isObj(v) &&
    int(v.id) &&
    str(v.loop) &&
    str(v.cadence) &&
    str(v.scheduled_for) &&
    str(v.status) &&
    strOrNull(v.skip_reason) &&
    Array.isArray(v.delivered_via) &&
    v.delivered_via.every(str) &&
    strOrNull(v.checkin_state)
  );
}

export function isHealth(v: unknown): v is Health {
  if (!isObj(v) || (v.status !== "ok" && v.status !== "degraded")) return false;
  const { brain, proactive, notify, errors, push } = v;
  return (
    isVersion(v.version) &&
    str(v.now) &&
    str(v.started_at) &&
    strOrNull(v.last_tick_at) &&
    str(v.polling) &&
    isObj(brain) &&
    str(brain.auth) &&
    strOrNull(brain.checked_at) &&
    strOrNull(brain.limited_until) &&
    int(brain.calls_today) &&
    int(brain.calls_cap) &&
    isObj(proactive) &&
    int(proactive.sent_today) &&
    int(proactive.cap) &&
    strOrNull(v.paused_until) &&
    typeof v.plan_open === "boolean" &&
    isObj(notify) &&
    str(notify.primary) &&
    str(notify.effective) &&
    Array.isArray(v.runs_today) &&
    v.runs_today.every(isRun) &&
    isObj(errors) &&
    int(errors.window_hours) &&
    str(errors.since) &&
    int(errors.total) &&
    isObj(errors.by_event) &&
    Object.values(errors.by_event).every(int) &&
    isObj(push) &&
    int(push.subscriptions) &&
    strOrNull(push.last_success_at)
  );
}

export function isSafeModeHealth(v: unknown): v is SafeModeHealth {
  return isObj(v) && v.status === "safe_mode" && str(v.now) && isVersion(v.version);
}
