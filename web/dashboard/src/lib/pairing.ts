// Device pairing spec 3.3, 5.3, 6, 6.2: what the settings screen reads off the browser, and the dashboard's
// only two writes (`POST /pair`, `DELETE /devices/{id}` of its own token). They stay in this one file: the rest
// of the dashboard only reads (ADR 0008; the BE test `test_dashboard_reads_only` allows these two here).
import type { PairBody, PairResult } from "../api/types.gen";
import { type ApiResult, errorCode, TIMEOUT_MS } from "./api";
import type { Conn } from "./connection";

/**
 * Spec 6.2: one word for this device from its user agent, null when none fits (labels.ts says "기기").
 * iPadOS Safari reports a Mac user agent; touch points tell it apart from a real Mac.
 */
export function deviceName(ua: string, touchPoints = 0): string | null {
  if (/iPhone|iPod/.test(ua)) return "iPhone";
  if (/iPad/.test(ua) || (/Macintosh/.test(ua) && touchPoints > 1)) return "iPad";
  if (/Android/i.test(ua)) return "Android";
  if (/Macintosh|Mac OS X/.test(ua)) return "Mac";
  if (/Windows/i.test(ua)) return "Windows";
  if (/Linux|X11|CrOS/i.test(ua)) return "Linux";
  return null;
}

export type PairHash = { be: string | null; code: string | null };

/**
 * Spec 3.3: the QR opens `/settings/#be=<BE 주소>&code=482913`. Null when the hash carries neither. A code
 * that is not six digits is dropped (the boxes stay empty); the address is checked later like a typed one.
 */
export function readPairHash(hash: string): PairHash | null {
  const q = new URLSearchParams(hash.replace(/^#/, ""));
  const be = q.get("be")?.trim() || null;
  const raw = q.get("code")?.replace(/\s/g, "") ?? "";
  const code = /^\d{6}$/.test(raw) ? raw : null;
  return be === null && !q.has("code") ? null : { be, code };
}

/** `bad_code`: a wrong or expired code. `old_be`: 401 `unauthorized`, a BE without `/pair` (auth stops it first). */
export type PairOutcome = { kind: "ok"; data: PairResult } | { kind: "bad_code" } | { kind: "old_be" } | Exclude<ApiResult<never>, { kind: "ok" } | { kind: "unauthorized" }>;

/**
 * `POST /pair`: no Authorization, the code is the credential. Not folded into fetchApi: its 401 is read by
 * `error.code`. JSON Content-Type on purpose (the BE refuses a simple request, spec 4.5).
 */
export async function postPair(beUrl: string, body: PairBody): Promise<PairOutcome> {
  const ac = new AbortController();
  const timer = setTimeout(() => ac.abort(), TIMEOUT_MS);
  try {
    let res: Response;
    try {
      res = await fetch(`${beUrl}/api/v1/pair`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify(body),
        signal: ac.signal,
        cache: "no-store",
        credentials: "omit",
        referrerPolicy: "no-referrer",
      });
    } catch {
      return { kind: "offline" };
    }
    let data: unknown = null;
    try {
      data = await res.json();
    } catch {
      if (ac.signal.aborted) return { kind: "offline" };
    }
    const code = errorCode(data, res.status);
    if (res.status === 401) return code === "bad_code" ? { kind: "bad_code" } : { kind: "old_be" };
    if (res.status === 429) return { kind: "rate_limited" };
    if (res.status === 503 && code === "safe_mode") return { kind: "safe_mode" };
    if (!res.ok) return { kind: "broken", code };
    return isPairResult(data) ? { kind: "ok", data } : { kind: "broken", code: "shape" };
  } finally {
    clearTimeout(timer);
  }
}

/** `DELETE /devices/{id}` with this browser's own device token (spec 6: its one write). Any failure is false. */
export async function deleteDevice(conn: Conn, id: number): Promise<boolean> {
  const ac = new AbortController();
  const timer = setTimeout(() => ac.abort(), TIMEOUT_MS);
  try {
    const res = await fetch(`${conn.beUrl}/api/v1/devices/${id}`, {
      method: "DELETE",
      headers: { Authorization: `Bearer ${conn.token}` },
      signal: ac.signal,
      cache: "no-store",
      credentials: "omit",
      referrerPolicy: "no-referrer",
    });
    return res.ok;
  } catch {
    return false;
  } finally {
    clearTimeout(timer);
  }
}

// The token goes into an Authorization header: visible ASCII only.
export function isPairResult(v: unknown): v is PairResult {
  const d = isObj(v) ? v.device : null;
  return isObj(v) && typeof v.token === "string" && /^[\x21-\x7e]+$/.test(v.token) && isObj(d) && Number.isSafeInteger(d.id) && (d.id as number) > 0 && typeof d.label === "string" && (d.client === "app" || d.client === "dashboard");
}

const isObj = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null && !Array.isArray(v);
