import { useCallback, useEffect, useRef, useState } from "react";
import type { ApiResult } from "./api";

const isVisible = () => document.visibilityState === "visible";

/**
 * Spec 13.1 "새로 고침": load when the screen opens and every `intervalMs` while the tab is visible,
 * once more when a hidden tab comes back. A 401 stops the timer (the token has to be fixed first);
 * `refresh()` (the "연결 확인" button) always loads. A new `resetKey` (another BE or token) starts over.
 */
export function usePolling<T>(
  load: () => Promise<ApiResult<T>>,
  intervalMs = 60_000,
  resetKey = "",
): { result: ApiResult<T> | null; refresh(): Promise<void> } {
  const [result, setResult] = useState<ApiResult<T> | null>(null);
  const loadRef = useRef(load);
  const seq = useRef(0);
  const stopped = useRef(false);
  const alive = useRef(true);

  useEffect(() => {
    loadRef.current = load;
  });

  const run = useCallback(async () => {
    const mine = ++seq.current;
    const r = await loadRef.current();
    if (!alive.current || mine !== seq.current) return; // unmounted, or a newer load answered first
    stopped.current = r.kind === "unauthorized";
    setResult(r);
  }, []);

  const tick = useCallback(() => {
    if (isVisible() && !stopped.current) void run();
  }, [run]);

  useEffect(() => {
    alive.current = true;
    stopped.current = false;
    setResult(null);
    tick();
    const timer = setInterval(tick, intervalMs);
    document.addEventListener("visibilitychange", tick);
    return () => {
      alive.current = false;
      seq.current++;
      clearInterval(timer);
      document.removeEventListener("visibilitychange", tick);
    };
  }, [intervalMs, resetKey, tick]);

  return { result, refresh: run };
}
