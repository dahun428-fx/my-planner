import { type Conn, loadConn, reportResult } from "../lib/connection";
import type { AgentNotes, DeviceList, Health, InboxCount, PairBody, PairCreated, PairResult, PairStatus } from "./types.gen";
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
  /**
   * No `Authorization` header, and a 401 keeps its error code (`POST /pair`, device pairing spec 5.3:
   * `bad_code` and an old BE's `unauthorized` mean different things). Use with `conn`.
   */
  anonymous?: boolean;
  /** A `multipart/form-data` body instead of JSON (`POST /photos`, SP10 5.3); the browser sets its boundary. */
  form?: FormData;
  /**
   * 429 codes that are a daily limit of this route, not the BE's auth rate limit (SP10 `photo_limit`,
   * `photo_read_limit`): they come back as `error` with their code and leave the connection state alone.
   */
  limitCodes?: ReadonlySet<string>;
  /** With `conn`: report the result to the connection provider all the same (a call on the saved connection). */
  report?: boolean;
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
    const headers: Record<string, string> = { Accept: "application/json" };
    if (!opts.anonymous) headers.Authorization = `Bearer ${conn.token}`;
    if (opts.body !== undefined && !opts.form) headers["Content-Type"] = "application/json";
    let res: Response;
    try {
      res = await fetch(`${conn.beUrl}/api/v1${path}`, {
        method,
        headers,
        body: opts.form ?? (opts.body === undefined ? undefined : JSON.stringify(opts.body)),
        signal: ac.signal,
        cache: "no-store",
      });
    } catch {
      // Timeout and network failure both mean "the secretary cannot be reached" (spec 5.4).
      if (opts.signal?.aborted && !timing.timedOut) return { kind: "error", status: 0, code: "aborted" };
      if (timing.timedOut && opts.timeoutMs !== undefined) return { kind: "error", status: 0, code: "timeout" };
      return { kind: "offline" };
    }

    if (res.status === 401 && !opts.anonymous) return { kind: "unauthorized" };
    if (res.status === 429 && !opts.limitCodes) return { kind: "rate_limited" };

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
      if (res.status === 429 && !opts.limitCodes?.has(code)) return { kind: "rate_limited" };
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
  if ((!opts.conn || opts.report) && !(result.kind === "error" && (result.code === "aborted" || result.code === "timeout"))) reportResult(result, conn);
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

// ---- device pairing (spec 4.5, 5) -----------------------------------------------------------------

// `POST /pair` with the code instead of a key. A 401 comes back as `error` with its code
// (`bad_code`, or `unauthorized` from a BE that has no `/pair` yet).
export function postPair(beUrl: string, body: PairBody): Promise<ApiResult<PairResult>> {
  return apiFetch<PairResult>("POST", "/pair", { conn: { beUrl, token: "" }, body, model: "PairResult", anonymous: true });
}

export function getDevices(): Promise<ApiResult<DeviceList>> {
  return apiGet<DeviceList>("/devices", "DeviceList");
}

// `conn` when the caller holds the connection itself (disconnecting: not reported to the provider).
export function deleteDevice(id: number, conn?: Conn): Promise<ApiResult<null>> {
  return apiFetch<null>("DELETE", `/devices/${id}`, { conn });
}

export function createPairCode(): Promise<ApiResult<PairCreated>> {
  return apiFetch<PairCreated>("POST", "/devices/pair", { model: "PairCreated" });
}

export function getPairStatus(signal?: AbortSignal): Promise<ApiResult<PairStatus>> {
  return apiFetch<PairStatus>("GET", "/devices/pair", { model: "PairStatus", signal });
}

// ---- the partners (SP14 10장, 11장) ---------------------------------------------------------------

// "새로 본 것 n개": what the partner has not yet seen. Reading it calls no brain.
export function getInboxCount(agent: "mate" | "manager"): Promise<ApiResult<InboxCount>> {
  return apiGet<InboxCount>(`/agents/${agent}/inbox/count`, "InboxCount");
}

// More › "비서 메모": the partners' notes of the last `days` days (403 for a dashboard device).
export function getAgentNotes(days = 7): Promise<ApiResult<AgentNotes>> {
  return apiGet<AgentNotes>(`/agents/notes?days=${days}`, "AgentNotes");
}
