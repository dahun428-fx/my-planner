import { useCallback, useEffect, useRef, useState } from "react";
import type { ApiResult } from "../api/client";
import { useConnection } from "./ConnectionProvider";

const isVisible = () => document.visibilityState === "visible";

// Spec 5.4/F2: load now, then every `intervalMs` while the tab is visible; once more when the tab
// comes back and when the connection returns. A 401 stops it (the key has to be fixed first).
export function usePolling<T>(
  load: () => Promise<ApiResult<T>>,
  intervalMs = 60_000,
): { result: ApiResult<T> | null; refresh(): Promise<void> } {
  const { onReconnect, conn } = useConnection();
  const beUrl = conn?.beUrl;
  const token = conn?.token;
  const [result, setResult] = useState<ApiResult<T> | null>(null);
  const loadRef = useRef(load);
  const seq = useRef(0);
  const stopped = useRef(false);
  const alive = useRef(true);

  useEffect(() => {
    loadRef.current = load;
  });

  const refresh = useCallback(async () => {
    if (stopped.current) return;
    const mine = ++seq.current;
    const r = await loadRef.current();
    if (!alive.current || mine !== seq.current) return; // unmounted, or a newer load already answered
    if (r.kind === "unauthorized") stopped.current = true;
    setResult(r);
  }, []);

  useEffect(() => {
    alive.current = true;
    stopped.current = false;
    if (isVisible()) void refresh();
    const timer = setInterval(() => {
      if (isVisible()) void refresh();
    }, intervalMs);
    const onVisible = () => {
      if (isVisible()) void refresh();
    };
    document.addEventListener("visibilitychange", onVisible);
    const offReconnect = onReconnect(() => void refresh());
    return () => {
      alive.current = false;
      clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisible);
      offReconnect();
    };
    // beUrl/token: a new connection starts polling afresh, even after a 401 stopped the old one.
  }, [intervalMs, onReconnect, refresh, beUrl, token]);

  return { result, refresh };
}
