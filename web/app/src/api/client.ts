import { type Conn, loadConn, reportResult } from "../lib/connection";
import type { Health } from "./types.gen";
import { type ModelName, validateModel } from "./validate";

export type ApiResult<T> =
  | { kind: "ok"; data: T }
  | { kind: "offline" }
  | { kind: "unauthorized" }
  | { kind: "rate_limited" }
  | { kind: "safe_mode" }
  | { kind: "error"; status: number; code: string; message?: string };

export interface FetchOpts {
  body?: unknown;
  model?: ModelName;
  signal?: AbortSignal;
  /** Try this connection instead of the saved one (first-connect check). Such a call is not reported. */
  conn?: Conn;
  /**
   * A longer wait for a call the BE answers slowly because it waits on others (a test push). Running
   * out of it says nothing about the connection: the answer is `error` "timeout", not offline.
   */
  timeoutMs?: number;
}

const TIMEOUT_MS = 10_000;

async function request<T>(method: string, path: string, opts: FetchOpts, conn: Conn, timing: { timedOut: boolean }): Promise<ApiResult<T>> {
  const ac = new AbortController();
  const timer = setTimeout(() => {
    timing.timedOut = true;
    ac.abort();
  }, opts.timeoutMs ?? TIMEOUT_MS);
  const onCallerAbort = () => ac.abort();
  opts.signal?.addEventListener("abort", onCallerAbort);
  if (opts.signal?.aborted) ac.abort();

  try {
    const headers: Record<string, string> = { Authorization: `Bearer ${conn.token}`, Accept: "application/json" };
    if (opts.body !== undefined) headers["Content-Type"] = "application/json";
    let res: Response;
    try {
      res = await fetch(`${conn.beUrl}/api/v1${path}`, {
        method,
        headers,
        body: opts.body === undefined ? undefined : JSON.stringify(opts.body),
        signal: ac.signal,
        cache: "no-store",
      });
    } catch {
      // Timeout and network failure both mean "the secretary cannot be reached" (spec 5.4).
      if (opts.signal?.aborted && !timing.timedOut) return { kind: "error", status: 0, code: "aborted" };
      if (timing.timedOut && opts.timeoutMs !== undefined) return { kind: "error", status: 0, code: "timeout" };
      return { kind: "offline" };
    }

    if (res.status === 401) return { kind: "unauthorized" };
    if (res.status === 429) return { kind: "rate_limited" };

    let json: unknown = null;
    if (res.status !== 204) {
      try {
        json = await res.json();
      } catch {
        if (res.ok) return { kind: "error", status: 200, code: "shape" };
      }
    }
    if (!res.ok) {
      const e = (json as { error?: { code?: unknown; message?: unknown } } | null)?.error;
      const code = typeof e?.code === "string" ? e.code : `http_${res.status}`;
      if (res.status === 503 && code === "safe_mode") return { kind: "safe_mode" };
      const out: ApiResult<T> = { kind: "error", status: res.status, code };
      if (typeof e?.message === "string") out.message = e.message;
      return out;
    }
    if (res.status === 204) return { kind: "ok", data: null as T };
    if (opts.model && !validateModel(opts.model, json)) return { kind: "error", status: 200, code: "shape" };
    return { kind: "ok", data: json as T };
  } finally {
    clearTimeout(timer);
    opts.signal?.removeEventListener("abort", onCallerAbort);
  }
}

export async function apiFetch<T>(
  method: "GET" | "POST" | "PUT" | "DELETE",
  path: string,
  opts: FetchOpts = {},
): Promise<ApiResult<T>> {
  const conn = opts.conn ?? loadConn();
  if (!conn) return { kind: "error", status: 0, code: "no_connection" };
  const result = await request<T>(method, path, opts, conn, { timedOut: false });
  if (!opts.conn && !(result.kind === "error" && (result.code === "aborted" || result.code === "timeout"))) reportResult(result, conn);
  return result;
}

export function apiGet<T>(path: string, model: ModelName): Promise<ApiResult<T>> {
  return apiFetch<T>("GET", path, { model });
}

// `/health` answers 200 with either Health or {status: "safe_mode"} (SP3-4 6.3.1).
export async function getHealth(conn?: Conn): Promise<ApiResult<Health>> {
  const r = await apiFetch<unknown>("GET", "/health", { conn });
  if (r.kind !== "ok") return r;
  if ((r.data as { status?: unknown } | null)?.status === "safe_mode") {
    return validateModel("SafeModeHealth", r.data) ? { kind: "safe_mode" } : { kind: "error", status: 200, code: "shape" };
  }
  return validateModel("Health", r.data) ? { kind: "ok", data: r.data as Health } : { kind: "error", status: 200, code: "shape" };
}
