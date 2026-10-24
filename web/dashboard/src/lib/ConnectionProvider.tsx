import { createContext, type ReactNode, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { Health } from "../api/types.gen";
import { type ApiResult, getHealth } from "./api";
import { type Conn, type LastHealthOk, loadConnection, loadLastHealthOk, saveConnection, saveLastHealthOk } from "./connection";
import { usePolling } from "./polling";

// One `/health` poll for the whole dashboard: the connection band and the status screen read it
// (spec 13.1, 13.2). Nothing from the BE is kept but the time of the last good answer.
export interface ConnectionState {
  /** false until the browser storage has been read (the static HTML has no connection). */
  ready: boolean;
  conn: Conn | null;
  health: ApiResult<Health> | null;
  lastOk: LastHealthOk | null;
  check(): Promise<void>;
  connect(c: Conn): void;
}

const NONE: ApiResult<Health> = { kind: "broken", code: "no_connection" };

const Ctx = createContext<ConnectionState>({
  ready: false,
  conn: null,
  health: null,
  lastOk: null,
  check: async () => {},
  connect: () => {},
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
  const { result, refresh } = usePolling(load, intervalMs, key);

  const connect = useCallback((c: Conn) => {
    saveConnection(c);
    setConn(c);
  }, []);

  const value = useMemo<ConnectionState>(
    () => ({ ready, conn, health: ready && conn ? result : null, lastOk, check: refresh, connect }),
    [ready, conn, result, lastOk, refresh, connect],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export const useConnection = () => useContext(Ctx);
