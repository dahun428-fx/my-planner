import { useRouter } from "next/router";
import { createContext, type ReactNode, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { getHealth } from "../api/client";
import {
  CONN_CHANGED,
  type Conn,
  type ConnState,
  deriveState,
  loadConn,
  loadLastHealthOk,
  saveLastHealthOk,
  subscribeResults,
} from "./connection";

export interface ConnectionValue {
  state: ConnState | null;
  conn: Conn | null;
  /** The saved connection has been read from device storage (it cannot be read while prerendering). */
  ready: boolean;
  recheck(): Promise<void>;
  /** Called when the connection goes from offline back to online. Returns an unsubscribe function. */
  onReconnect(cb: () => void): () => void;
}

export const ConnectionContext = createContext<ConnectionValue>({
  state: null,
  conn: null,
  ready: false,
  recheck: async () => {},
  onReconnect: () => () => {},
});

export function useConnection(): ConnectionValue {
  return useContext(ConnectionContext);
}

/**
 * Whether a screen takes writes: what it shows is live (`live` false: a snapshot, or a read that was
 * refused) and the connection is online, or not known yet (before the first /health answer, so live
 * data does not flicker read-only). `strict` (the chat launcher) waits for "online": the sheet needs it.
 */
export function useWritable(live = true, opts: { strict?: boolean } = {}): boolean {
  const { state } = useConnection();
  return live && (state?.kind === "online" || (state === null && !opts.strict));
}

const HEALTH_EVERY_MS = 30_000;
const HEALTH_ERRORS_TO_OFFLINE = 3;
const isVisible = () => typeof document === "undefined" || document.visibilityState === "visible";
const sameConn = (a: Conn | null, b: Conn | null) => a?.beUrl === b?.beUrl && a?.token === b?.token;

// Spec F1/F2: holds the saved connection, watches /health, and sends the person to /connect/ when none is saved.
export function ConnectionProvider({ children }: { children: ReactNode }) {
  const router = useRouter();
  const [conn, setConn] = useState<Conn | null>(null);
  const [ready, setReady] = useState(false);
  const [state, setState] = useState<ConnState | null>(null);
  const stateRef = useRef<ConnState | null>(null);
  const connRef = useRef<Conn | null>(null);
  const seq = useRef(0);
  const inFlight = useRef(0);
  const errorStreak = useRef(0);
  const reconnect = useRef(new Set<() => void>());

  const apply = useCallback((next: ConnState | null) => {
    const prev = stateRef.current;
    stateRef.current = next;
    setState(next);
    if (prev?.kind === "offline" && next?.kind === "online") reconnect.current.forEach((cb) => cb());
  }, []);

  // Read the saved connection after mount, and again when it changes (connect screen, other tab).
  useEffect(() => {
    const read = () => {
      const next = loadConn();
      if (!sameConn(connRef.current, next)) {
        connRef.current = next;
        seq.current += 1;
        errorStreak.current = 0;
        stateRef.current = null;
        setState(null);
        setConn(next);
      }
      setReady(true);
    };
    read();
    window.addEventListener(CONN_CHANGED, read);
    window.addEventListener("storage", read);
    return () => {
      window.removeEventListener(CONN_CHANGED, read);
      window.removeEventListener("storage", read);
    };
  }, []);

  const recheck = useCallback(async () => {
    if (!connRef.current) return;
    const mine = ++seq.current;
    inFlight.current += 1;
    let r: Awaited<ReturnType<typeof getHealth>>;
    try {
      r = await getHealth();
    } finally {
      inFlight.current -= 1;
    }
    if (mine !== seq.current || !connRef.current) return; // a newer check or another connection took over
    if (r.kind === "error") {
      // One bad answer changes nothing (5.4 handles it inside the block that asked); a streak of
      // three (about 90 s) means the secretary is not really there.
      errorStreak.current += 1;
      if (stateRef.current === null || errorStreak.current >= HEALTH_ERRORS_TO_OFFLINE) {
        apply({ kind: "offline", lastOk: loadLastHealthOk() });
      }
      return;
    }
    errorStreak.current = 0;
    if (r.kind === "ok") saveLastHealthOk(new Date().toISOString());
    apply(deriveState(r, loadLastHealthOk()));
  }, [apply]);

  // /health every 30 s while visible, at once when the page comes back (F2).
  useEffect(() => {
    if (!conn) return;
    if (isVisible()) void recheck();
    const timer = setInterval(() => {
      if (isVisible()) void recheck();
    }, HEALTH_EVERY_MS);
    const onVisible = () => {
      if (isVisible()) void recheck();
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [conn, recheck]);

  // Any other request that fails to connect (or is refused) changes the state at once (F2, 5.4).
  useEffect(
    () =>
      subscribeResults((r, from) => {
        const cur = connRef.current;
        if (!cur || cur.beUrl !== from.beUrl || cur.token !== from.token) return; // answer for an old connection
        if (r.kind === "offline") apply({ kind: "offline", lastOk: loadLastHealthOk() });
        else if (r.kind === "unauthorized" || r.kind === "safe_mode" || r.kind === "rate_limited") apply({ kind: r.kind });
        else if (r.kind === "ok" && inFlight.current === 0 && stateRef.current?.kind !== "online") void recheck();
      }),
    [apply, recheck],
  );

  // No saved connection: every screen but /connect/ goes there.
  const onConnect = router.pathname.replace(/\/$/, "") === "/connect";
  useEffect(() => {
    if (ready && !conn && !onConnect) void router.replace("/connect/");
  }, [ready, conn, onConnect, router]);

  const onReconnect = useCallback((cb: () => void) => {
    reconnect.current.add(cb);
    return () => {
      reconnect.current.delete(cb);
    };
  }, []);

  const value = useMemo(
    () => ({ state, conn, ready, recheck, onReconnect }),
    [state, conn, ready, recheck, onReconnect],
  );
  return <ConnectionContext.Provider value={value}>{children}</ConnectionContext.Provider>;
}
