// The browser calls the BE directly (ADR 0008). One result type for every screen, mapped from the
// common states table of spec 13.1. Shapes are checked by hand: a field the BE adds later is ignored,
// a field a screen needs that is missing or of the wrong type is `broken("shape")`.
import type { Conditions, Curve, CurveHistory, Health, SafeModeHealth, Status, Today, Week } from "../api/types.gen";
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

// ---- (b) 할 일 + 컨디션, (d) 상태창 (6.3.2~6.3.4, 6.3.6): only the fields the screens draw ----------

const arr = <T>(v: unknown, each: (x: unknown) => boolean): v is T[] => Array.isArray(v) && v.every(each);
const num = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);

function isTodo(v: unknown): boolean {
  if (!isObj(v)) return false;
  const p = v.priority;
  return (
    int(v.id) &&
    str(v.title) &&
    str(v.status) &&
    strOrNull(v.planned_for) &&
    strOrNull(v.scheduled_at) &&
    intOrNull(v.parent_id) &&
    (p === null || (isObj(p) && str(p.cadence) && int(p.rank)))
  );
}

const isCondition = (v: unknown) => isObj(v) && str(v.date) && int(v.score) && strOrNull(v.note);

export function isToday(v: unknown): v is Today {
  if (!isObj(v)) return false;
  const b = v.brief;
  return (
    str(v.date) &&
    str(v.weekday) &&
    (b === null || (isObj(b) && str(b.loop) && str(b.text) && strOrNull(b.sent_at))) &&
    (v.condition === null || isCondition(v.condition)) &&
    arr(v.todos, (t) => isObj(t) && (t.group === "priority" || t.group === "scheduled" || t.group === "open") && isTodo(t.todo))
  );
}

export function isWeek(v: unknown): v is Week {
  return (
    isObj(v) &&
    str(v.week) &&
    str(v.start) &&
    str(v.end) &&
    arr(v.priorities, isTodo) &&
    arr(v.days, (d) => isObj(d) && str(d.date) && str(d.weekday) && typeof d.is_today === "boolean" && arr(d.todos, isTodo))
  );
}

export function isConditions(v: unknown): v is Conditions {
  return isObj(v) && str(v.from) && str(v.to) && arr(v.items, isCondition) && int(v.days_logged) && (v.average === null || num(v.average));
}

export function isStatus(v: unknown): v is Status {
  if (!isObj(v)) return false;
  const hp = v.hp;
  return (
    int(v.level) &&
    int(v.xp_total) &&
    int(v.xp_into_level) &&
    int(v.xp_for_next) &&
    isObj(hp) &&
    intOrNull(hp.score) &&
    arr(
      v.stats,
      (s) =>
        isObj(s) &&
        str(s.area) &&
        str(s.label) &&
        intOrNull(s.score) &&
        strOrNull(s.period) &&
        intOrNull(s.prev_score) &&
        strOrNull(s.prev_period) &&
        typeof s.debuff === "boolean" &&
        strOrNull(s.recovery_quest),
    ) &&
    arr(
      v.main_quests,
      (q) => isObj(q) && int(q.task_id) && str(q.title) && int(q.rank) && isObj(q.first_steps) && int(q.first_steps.open) && int(q.first_steps.done),
    ) &&
    arr(v.daily_quests, (q) => isObj(q) && int(q.task_id) && str(q.title) && strOrNull(q.parent_title)) &&
    arr(v.titles, (t) => isObj(t) && int(t.milestone_id) && str(t.title)) &&
    arr(v.recent_xp, (x) => isObj(x) && str(x.at) && str(x.label) && int(x.amount))
  );
}

// ---- (c) 인생곡선 (6.3.5) ----------------------------------------------------------------------------

const numOrNull = (v: unknown) => v === null || num(v);
const ZOOMS = ["day", "week", "month", "quarter", "year"];

export function isCurve(v: unknown): v is Curve {
  return (
    isObj(v) &&
    typeof v.zoom === "string" &&
    ZOOMS.includes(v.zoom) &&
    str(v.from) &&
    str(v.to) &&
    arr(v.chapters, (c) => isObj(c) && int(c.id) && str(c.title) && str(c.start) && strOrNull(c.end) && strOrNull(c.sketch) && str(c.certainty)) &&
    arr(
      v.milestones,
      (m) =>
        isObj(m) &&
        int(m.id) &&
        str(m.date) &&
        (m.precision === "year" || m.precision === "month" || m.precision === "day") &&
        (m.kind === "high" || m.kind === "low" || m.kind === "turning_point") &&
        str(m.title) &&
        strOrNull(m.note) &&
        typeof m.sensitive === "boolean" &&
        str(m.certainty),
    ) &&
    arr(v.ladder, (l) => isObj(l) && str(l.period) && intOrNull(l.now) && intOrNull(l.future)) &&
    arr(v.areas, (a) => isObj(a) && str(a.period) && isObj(a.scores) && Object.values(a.scores).every(int)) &&
    arr(v.condition, (c) => isObj(c) && str(c.bucket) && str(c.start) && str(c.end) && numOrNull(c.average) && int(c.days_logged)) &&
    arr(
      v.reassurance,
      (r) => isObj(r) && str(r.period) && int(r.ladder_now) && numOrNull(r.condition_average) && numOrNull(r.condition_scaled) && int(r.days_logged) && numOrNull(r.gap),
    )
  );
}

// ---- 히스토리 (SP8 8.2) -----------------------------------------------------------------------------

const AREA_CODES = ["career", "finance", "health", "relationships", "learning", "quality_of_life"];
const hiddenOk = (h: unknown) => isObj(h) && int(h.count) && arr(h.years, int);
const eventOk = (e: unknown) =>
  isObj(e) &&
  int(e.id) &&
  str(e.date) &&
  (e.precision === "year" || e.precision === "month" || e.precision === "day") &&
  (e.kind === "high" || e.kind === "low" || e.kind === "turning_point") &&
  (e.kind_certainty === "fact" || e.kind_certainty === "estimate") &&
  str(e.title) &&
  strOrNull(e.note) &&
  (e.area === null || (str(e.area) && AREA_CODES.includes(e.area))) &&
  (e.origin === "seed" || e.origin === "chat" || e.origin === "review") &&
  (e.certainty === "fact" || e.certainty === "estimate") &&
  typeof e.sensitive === "boolean";

export function isCurveHistory(v: unknown): v is CurveHistory {
  return (
    isObj(v) &&
    intOrNull(v.since_year) &&
    arr(
      v.chapters,
      (c) =>
        isObj(c) &&
        int(c.id) &&
        str(c.title) &&
        strOrNull(c.theme) &&
        str(c.start) &&
        strOrNull(c.end) &&
        strOrNull(c.sketch) &&
        (c.certainty === "fact" || c.certainty === "estimate") &&
        (c.ladder === null || (isObj(c.ladder) && num(c.ladder.value) && (c.ladder.source === "remembered" || c.ladder.source === "recorded"))) &&
        arr(c.events, eventOk) &&
        hiddenOk(c.hidden_sensitive),
    ) &&
    isObj(v.unassigned) &&
    arr(v.unassigned.events, eventOk) &&
    hiddenOk(v.unassigned.hidden_sensitive) &&
    isObj(v.summary) &&
    int(v.summary.chapters) &&
    int(v.summary.events) &&
    (v.summary.highest === null || (isObj(v.summary.highest) && int(v.summary.highest.chapter_id) && str(v.summary.highest.title) && num(v.summary.highest.ladder))) &&
    (v.summary.longest === null || (isObj(v.summary.longest) && int(v.summary.longest.chapter_id) && str(v.summary.longest.title) && int(v.summary.longest.years))) &&
    isObj(v.summary.turning_points) &&
    int(v.summary.turning_points.count) &&
    arr(v.summary.turning_points.years, int) &&
    intOrNull(v.summary.records_since)
  );
}
