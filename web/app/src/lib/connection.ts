import type { ApiResult } from "../api/client";
import type { Health } from "../api/types.gen";
import { copy } from "./copy";
import { formatKst } from "./time";

export type Conn = { beUrl: string; token: string };

const K_URL = "mp.beUrl";
const K_TOKEN = "mp.token";
const K_OK = "mp.lastHealthOk";

// ---- BE address and key -------------------------------------------------------------------

export type NormalizedUrl = { ok: true; url: string } | { ok: false; reason: "not_https" | "out_of_range" | "invalid" };

// `allowed` is NEXT_PUBLIC_CONNECT_SRC: space separated `https://*.<tailnet>.ts.net`, `*` = one name.
function hostMatches(host: string, allowed: string): boolean {
  return allowed
    .split(/\s+/)
    .filter(Boolean)
    .some((entry) => {
      const pattern = entry.replace(/^https:\/\//i, "").replace(/\/.*$/, "").toLowerCase();
      const have = host.split(".");
      const want = pattern.split(".");
      return have.length === want.length && want.every((w, i) => w === "*" ? have[i] !== "" : w === have[i]);
    });
}

export function normalizeBeUrl(input: string, allowed: string = process.env.NEXT_PUBLIC_CONNECT_SRC ?? ""): NormalizedUrl {
  let u: URL;
  try {
    u = new URL(input.trim());
  } catch {
    return { ok: false, reason: "invalid" };
  }
  if (u.protocol === "http:") return { ok: false, reason: "not_https" };
  if (u.protocol !== "https:" || u.username || u.password || u.search || u.hash) return { ok: false, reason: "invalid" };
  const path = u.pathname.replace(/\/+$/, "").replace(/\/api\/v1$/, "");
  if (path !== "") return { ok: false, reason: "invalid" };
  if (!hostMatches(u.host, allowed)) return { ok: false, reason: "out_of_range" };
  return { ok: true, url: u.origin };
}

export function normalizeToken(input: string): string {
  return input.trim();
}

// ---- device storage (spec 4.7); blocked storage reads as "nothing" -------------------------

function read(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

function write(key: string, value: string): void {
  try {
    localStorage.setItem(key, value);
  } catch {
    // blocked storage: the app stays on the connect screen
  }
}

export const CONN_CHANGED = "mp:conn";

function announce(): void {
  try {
    window.dispatchEvent(new Event(CONN_CHANGED));
  } catch {
    // no window (prerender)
  }
}

export function loadConn(): Conn | null {
  const beUrl = read(K_URL);
  const token = read(K_TOKEN);
  return beUrl && token ? { beUrl, token } : null;
}

export function saveConn(c: Conn): void {
  write(K_URL, c.beUrl);
  write(K_TOKEN, c.token);
  announce();
}

export function loadLastHealthOk(): string | null {
  return read(K_OK);
}

export function saveLastHealthOk(iso: string): void {
  write(K_OK, iso);
}

// ---- results reported by apiFetch to the connection provider --------------------------------
// A tiny emitter so client.ts need not import the React provider (no import cycle).

type Listener = (r: ApiResult<unknown>) => void;
const listeners = new Set<Listener>();

export function reportResult(r: ApiResult<unknown>): void {
  listeners.forEach((l) => l(r));
}

export function subscribeResults(l: Listener): () => void {
  listeners.add(l);
  return () => listeners.delete(l);
}

// ---- connection state (spec 5.4) --------------------------------------------------------------

export type ConnState =
  | { kind: "online"; health: Health; degraded: string | null }
  | { kind: "offline"; lastOk: string | null }
  | { kind: "unauthorized" }
  | { kind: "rate_limited" }
  | { kind: "safe_mode" };

// 5.4 "비서 상태 나쁨": brain login/billing, or a limit that is still ahead. polling:down only is not shown.
export function degradedNotice(health: Health): string | null {
  if (health.brain.auth === "login" || health.brain.auth === "billing") return copy.status.relogin;
  const until = health.brain.limited_until;
  if (until && Date.parse(until) > Date.parse(health.now)) return copy.status.limited(formatKst(until, "HH:mm"));
  return null;
}

export function deriveState(r: ApiResult<Health>, lastOk: string | null): ConnState {
  switch (r.kind) {
    case "ok":
      if ((r.data as { status?: string }).status === "safe_mode") return { kind: "safe_mode" };
      return { kind: "online", health: r.data, degraded: degradedNotice(r.data) };
    case "unauthorized":
      return { kind: "unauthorized" };
    case "rate_limited":
      return { kind: "rate_limited" };
    case "safe_mode":
      return { kind: "safe_mode" };
    case "offline":
    case "error":
      return { kind: "offline", lastOk };
  }
}
