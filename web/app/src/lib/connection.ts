import type { ApiResult } from "../api/client";
import type { Health } from "../api/types.gen";
import { copy } from "./copy";
import { formatKst } from "./time";

export type Conn = { beUrl: string; token: string };

const K_URL = "mp.beUrl";
const K_TOKEN = "mp.token";
const K_OK = "mp.lastHealthOk";
// Device pairing spec 5.4: set when this device connected with a pairing code (its own device token).
const K_KIND = "mp.tokenKind";
const K_DEVICE = "mp.deviceId";

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

// Device pairing spec 6.1: the optional build-time BE address that fills the connect screen. Used only
// when it passes the same check as a typed address; otherwise the field starts empty.
export function defaultBeUrl(value: string | undefined = process.env.NEXT_PUBLIC_DEFAULT_BE_URL): string {
  if (!value || !value.trim()) return "";
  const norm = normalizeBeUrl(value);
  return norm.ok ? norm.url : "";
}

// Device pairing spec 3.3: `#be=<address>&code=<6 digits>` from the pairing sheet's QR. Either part may
// be missing; a code that is not 6 digits is dropped.
export function parsePairHash(hash: string): { be: string | null; code: string | null } | null {
  const raw = hash.replace(/^#/, "");
  if (!raw) return null;
  const params = new URLSearchParams(raw);
  const be = params.get("be");
  const code = params.get("code");
  if (be === null && code === null) return null;
  return { be: be && be.trim() ? be.trim() : null, code: code && /^\d{6}$/.test(code) ? code : null };
}

// Device pairing spec 6.2: the device's kind from the user agent, then where it runs.
export function deviceLabel(ua: string, where: string): string {
  let kind = "";
  if (/iPhone/.test(ua)) kind = "iPhone";
  else if (/iPad/.test(ua) || (/Macintosh/.test(ua) && typeof navigator !== "undefined" && navigator.maxTouchPoints > 1)) kind = "iPad";
  else if (/Android/.test(ua)) kind = "Android";
  else if (/Macintosh|Mac OS X/.test(ua)) kind = "Mac";
  else if (/Windows/.test(ua)) kind = "Windows";
  else if (/Linux|X11/.test(ua)) kind = "Linux";
  return `${kind || copy.devices.someDevice} · ${where}`;
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

function remove(key: string): void {
  try {
    localStorage.removeItem(key);
  } catch {
    // blocked storage
  }
}

// `device` is the paired device when the token came from a pairing code (spec 5.4); a key connect
// (no `device`) drops what an earlier code connect left.
export function saveConn(c: Conn, device?: { id: number }): void {
  write(K_URL, c.beUrl);
  write(K_TOKEN, c.token);
  if (device) {
    write(K_KIND, "device");
    write(K_DEVICE, String(device.id));
  } else {
    remove(K_KIND);
    remove(K_DEVICE);
  }
  announce();
}

// This device's id at the BE when its saved token is a device token, else null (a key connect).
export function loadDeviceId(): number | null {
  if (read(K_KIND) !== "device") return null;
  const id = Number(read(K_DEVICE));
  return Number.isInteger(id) && id > 0 ? id : null;
}

export function loadLastHealthOk(): string | null {
  return read(K_OK);
}

export function saveLastHealthOk(iso: string): void {
  write(K_OK, iso);
}

// ---- results reported by apiFetch to the connection provider --------------------------------
// A tiny emitter so client.ts need not import the React provider (no import cycle).

type Listener = (r: ApiResult<unknown>, conn: Conn) => void;
const listeners = new Set<Listener>();

// `conn` is the connection the request was sent with, so a late answer from an old BE can be ignored.
export function reportResult(r: ApiResult<unknown>, conn: Conn): void {
  listeners.forEach((l) => l(r, conn));
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
