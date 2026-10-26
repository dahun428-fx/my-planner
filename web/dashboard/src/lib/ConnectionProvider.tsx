import { createContext, type ReactNode, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import type { Health } from "../api/types.gen";
import { type ApiResult, getHealth } from "./api";
import { type Conn, type LastHealthOk, clearConnection, loadConnection, loadLastHealthOk, saveConnection, saveLastHealthOk } from "./connection";
import { deleteDevice } from "./pairing";
import { usePolling } from "./polling";

// One `/health` poll for the whole dashboard: the connection band and the status screen read it
// (spec 13.1, 13.2). Nothing from the BE is kept but the time of the last good answer.
export interface ConnectionState {
  /** false until the browser storage has been read (the static HTML has no connection). */
  ready: boolean;
  conn: Conn | null;
  health: ApiResult<Health> | null;
  lastOk: LastHealthOk | null;
  /** Goes up by one each time `/health` turns from offline to ok: every screen's poll loads again (DU-03). */
  backOnline: number;
  /** While `/health` is offline, the wait before the next check (10 s, 20 s, 40 s, then 60 s); else null. */
  retryMs: number | null;
  check(): Promise<void>;
  connect(c: Conn): void;
  /** "연결 지우기": a device token is revoked first (device pairing spec 5.4, failure ignored), then forgotten. */
  disconnect(): Promise<void>;
}

/** DU-03: how long to wait between `/health` checks while the BE does not answer. */
export const OFFLINE_RETRY_MS = [10_000, 20_000, 40_000, 60_000] as const;

const NONE: ApiResult<Health> = { kind: "broken", code: "no_connection" };

const Ctx = createContext<ConnectionState>({
  ready: false,
  conn: null,
  health: null,
  lastOk: null,
  backOnline: 0,
  retryMs: null,
  check: async () => {},
  connect: () => {},
  disconnect: async () => {},
});

export function ConnectionProvider({ children, intervalMs = 60_000 }: { children: ReactNode; intervalMs?: number }) {
  const [ready, setReady] = useState(false);
  const [conn, setConn] = useState<Conn | null>(null);
  const [lastOk, setLastOk] = useState<LastHealthOk | null>(null);

  useEffect(() => {
    setConn(loadConnection());
    setLastOk(loadLastHealthOk());
    setReady(true);
  }, []);

  const load = useCallback(async (): Promise<ApiResult<Health>> => {
    if (!conn) return NONE;
    const r = await getHealth(conn);
    if (r.kind === "ok") {
      const seen = { at: new Date().toISOString(), lastTickAt: r.data.last_tick_at };
      saveLastHealthOk(seen);
      setLastOk(seen);
    }
    return r;
  }, [conn]);

  const key = !ready ? "" : conn ? `${conn.beUrl}\n${conn.token}` : "none";
  const { result, refresh, retryMs } = usePolling(load, intervalMs, key, { retryDelays: OFFLINE_RETRY_MS });

  // offline -> ok: one shared signal the screens' polls wake on. Another BE or token starts with no history.
  const [backOnline, setBackOnline] = useState(0);
  const wasOffline = useRef(false);
  useEffect(() => {
    wasOffline.current = false;
  }, [key]);
  useEffect(() => {
    if (result === null) return;
    if (result.kind === "ok" && wasOffline.current) setBackOnline((n) => n + 1);
    wasOffline.current = result.kind === "offline";
  }, [result]);

  // The same BE and token again (after a 401 stopped the poll) keep the poll's key: check right away.
  const connect = useCallback(
    (c: Conn) => {
      saveConnection(c);
      if (conn && conn.beUrl === c.beUrl && conn.token === c.token) void refresh();
      else setConn(c);
    },
    [conn, refresh],
  );

  const disconnect = useCallback(async () => {
    if (conn?.kind === "device" && conn.deviceId !== undefined) await deleteDevice(conn, conn.deviceId);
    clearConnection();
    setConn(null);
  }, [conn]);

  const value = useMemo<ConnectionState>(
    () => ({
      ready,
      conn,
      health: ready && conn ? result : null,
      lastOk,
      backOnline,
      retryMs: ready && conn ? retryMs : null,
      check: refresh,
      connect,
      disconnect,
    }),
    [ready, conn, result, lastOk, backOnline, retryMs, refresh, connect, disconnect],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export const useConnection = () => useContext(Ctx);
