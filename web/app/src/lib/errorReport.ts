import { apiFetch } from "../api/client";
import type { ClientErrorBody } from "../api/types.gen";
import { loadConn } from "./connection";

// Spec 3.3: the app tells the BE which error happened where, never what it said. The message and the
// URL (it can hold a todo title or an id) stay in the browser. The BE rejects any body that does not
// fit these shapes, so each field is checked here and replaced by a safe stand-in when it does not.
const VERSION_RE = /^[A-Za-z0-9._+-]{1,40}$/;
const ROUTE_RE = /^\/[A-Za-z0-9_\-/[\]]{0,119}$/;
const NAME_RE = /^[A-Za-z][A-Za-z0-9_.]{0,79}$/;
const FRAME_RE = /^[A-Za-z0-9_-][A-Za-z0-9_.\-/[\]]*\.js:\d+:\d+$/;
const MAX_FRAMES = 10;
const MAX_FRAME_LEN = 160;
const PER_MINUTE = 5;
const WINDOW_MS = 60_000;

const ID_SEGMENT = /^(?:\d+|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$/i;

/** `router.pathname` is already a `[id]` pattern; digits and UUIDs that still got through become `[id]`. */
export function normalizeRoute(pathname: string): string {
  const path = pathname.split(/[?#]/)[0] ?? "";
  const segments = path.split("/").map((s) => (ID_SEGMENT.test(s) ? "[id]" : s));
  let route = segments.join("/");
  if (route.length > 1 && route.endsWith("/")) route = route.slice(0, -1);
  return ROUTE_RE.test(route) ? route : "/";
}

const CHUNK_PREFIX = "/_next/static/chunks/";

/**
 * `/_next/static/chunks/pages/today-3f9a1c2b.js:1:2345` -> `pages/today.js:1:2345`. Anything that is not
 * this app's own chunk (another origin, other assets) or that the BE would reject gives `null`.
 */
export function stripHash(frame: string, origin: string | undefined = globalThis.location?.origin): string | null {
  let rest = frame;
  if (/^https?:\/\//i.test(rest)) {
    if (!origin || !rest.startsWith(`${origin}/`)) return null;
    rest = rest.slice(origin.length);
  }
  if (!rest.startsWith(CHUNK_PREFIX)) return null;
  const m = /^(.+?)(?:\?[^:]*)?:(\d+):(\d+)$/.exec(rest.slice(CHUNK_PREFIX.length));
  if (!m) return null;
  let path: string;
  try {
    path = decodeURIComponent(m[1] ?? "");
  } catch {
    return null;
  }
  if (!path.endsWith(".js")) return null;
  const base = path.slice(0, -3).replace(/[-.][0-9a-f]{8,}$/, "");
  const out = `${base}.js:${m[2]}:${m[3]}`;
  return out.length <= MAX_FRAME_LEN && FRAME_RE.test(out) ? out : null;
}

function framesOf(err: unknown): string[] {
  const stack = typeof (err as { stack?: unknown } | null)?.stack === "string" ? (err as { stack: string }).stack : "";
  const out: string[] = [];
  for (const line of stack.split("\n")) {
    const m = /(?:^|[\s(@])((?:https?:\/\/|\/)[^\s()@]+:\d+:\d+)\)?\s*$/.exec(line);
    const frame = m?.[1] ? stripHash(m[1]) : null;
    if (frame) out.push(frame);
    if (out.length === MAX_FRAMES) break;
  }
  return out;
}

function nameOf(err: unknown): string {
  const name = (err as { name?: unknown } | null)?.name;
  return typeof name === "string" && NAME_RE.test(name) ? name : "Error";
}

function versionOf(): string {
  const v = process.env.NEXT_PUBLIC_APP_VERSION;
  return v && VERSION_RE.test(v) ? v : "dev";
}

export class ErrorReporter {
  private readonly seen = new Set<string>();
  private sentAt: number[] = [];

  constructor(
    private readonly send: (body: ClientErrorBody) => Promise<void>,
    private readonly now: () => number,
  ) {}

  /** Never throws and never reports its own failure: a broken report path must not make more errors. */
  report(err: unknown, pathname: string): void {
    try {
      if (typeof navigator !== "undefined" && navigator.onLine === false) return;
      const route = normalizeRoute(pathname);
      const name = nameOf(err);
      const key = `${name} ${route}`;
      if (this.seen.has(key)) return;
      const t = this.now();
      this.sentAt = this.sentAt.filter((s) => t - s < WINDOW_MS);
      if (this.sentAt.length >= PER_MINUTE) return;
      this.seen.add(key);
      this.sentAt.push(t);
      const body: ClientErrorBody = {
        app: "app",
        version: versionOf(),
        route,
        name,
        frames: framesOf(err) as ClientErrorBody["frames"],
        at: new Date(t).toISOString(),
      };
      void Promise.resolve(this.send(body)).catch(() => {});
    } catch {
      // dropped
    }
  }
}

const reporter = new ErrorReporter(async (body) => {
  const conn = loadConn();
  if (!conn) return;
  // `conn` given: the call is not counted in the connection state (a failed report is not an outage).
  await apiFetch("POST", "/client-errors", { body, conn });
}, Date.now);

export function reportBrowserError(err: unknown, pathname: string): void {
  reporter.report(err, pathname);
}
