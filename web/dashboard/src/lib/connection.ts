// The BE URL and API token live only in this browser's localStorage (spec 13.1, 14). Every read and
// write is wrapped: blocked storage (a private window, a strict browser) reads as "nothing".

export type Conn = { beUrl: string; token: string };
export type LastHealthOk = { at: string; lastTickAt: string | null };

const K_CONN = "mp.connection";
const K_LAST_OK = "mp.lastHealthOk";

// ---- BE URL --------------------------------------------------------------------------------

export type NormalizedUrl = { ok: true; url: string } | { ok: false; reason: "not_https" | "out_of_range" | "invalid" };

// `allowed` is NEXT_PUBLIC_CONNECT_SRC: space separated sources such as `https://*.<tailnet>.ts.net`.
// A `*` stands for exactly one host label, so `a.b.<tailnet>.ts.net` and the bare tailnet name are out.
function hostMatches(host: string, allowed: string): boolean {
  return allowed
    .split(/\s+/)
    .filter(Boolean)
    .some((entry) => {
      const pattern = entry.replace(/^https:\/\//i, "").replace(/\/.*$/, "").toLowerCase();
      const have = host.split(".");
      const want = pattern.split(".");
      return have.length === want.length && want.every((w, i) => (w === "*" ? have[i] !== "" : w === have[i]));
    });
}

/** Pasted BE address -> its origin. A trailing `/api/v1` (how the BE is usually written) is dropped. */
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

// ---- storage ---------------------------------------------------------------------------------

function read(key: string): unknown {
  try {
    const raw = localStorage.getItem(key);
    return raw === null ? null : JSON.parse(raw);
  } catch {
    return null;
  }
}

function write(key: string, value: unknown): void {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
    // blocked storage: nothing is kept, the screens ask again next time
  }
}

const isObj = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null && !Array.isArray(v);
const nonEmpty = (v: unknown): v is string => typeof v === "string" && v !== "";

export function loadConnection(): Conn | null {
  const v = read(K_CONN);
  return isObj(v) && nonEmpty(v.beUrl) && nonEmpty(v.token) ? { beUrl: v.beUrl, token: v.token } : null;
}

export function saveConnection(c: Conn): void {
  write(K_CONN, { beUrl: c.beUrl, token: c.token });
}

/** When this browser last got a good `/health` (spec 13.1 "마지막 응답"), and the BE's last tick then. */
export function loadLastHealthOk(): LastHealthOk | null {
  const v = read(K_LAST_OK);
  if (!isObj(v) || !nonEmpty(v.at)) return null;
  return { at: v.at, lastTickAt: nonEmpty(v.lastTickAt) ? v.lastTickAt : null };
}

export function saveLastHealthOk(v: LastHealthOk): void {
  write(K_LAST_OK, { at: v.at, lastTickAt: v.lastTickAt });
}
