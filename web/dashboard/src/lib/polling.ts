import { useCallback, useEffect, useRef, useState } from "react";
import type { ApiResult } from "./api";

const isVisible = () => document.visibilityState === "visible";

export interface PollingOptions {
  /**
   * While loads come back `offline`, wait these in turn before the next one (the last repeats), instead of
   * `intervalMs`. Any other answer goes back to `intervalMs`.
   */
  retryDelays?: readonly number[];
  /** A new value loads at once (DU-03: the BE came back). The first value does not. */
  wake?: number;
}

/**
 * Spec 13.1 "새로 고침": load when the screen opens and every `intervalMs` while the tab is visible,
 * once more when a hidden tab comes back. A 401 stops the timer (the token has to be fixed first);
 * `refresh()` (the "연결 확인" button) always loads, and an offline answer to it puts the wait back to the
 * first retry step instead of moving it up. A new `resetKey` (another BE or token) starts over.
 * The next load is counted from the end of the last one. `retryMs` is the wait in use while offline.
 */
export function usePolling<T>(
  load: () => Promise<ApiResult<T>>,
  intervalMs = 60_000,
  resetKey = "",
  { retryDelays, wake }: PollingOptions = {},
): { result: ApiResult<T> | null; refresh(): Promise<void>; retryMs: number | null } {
  const [result, setResult] = useState<ApiResult<T> | null>(null);
  const [retryMs, setRetryMs] = useState<number | null>(null);
  const loadRef = useRef(load);
  const delaysRef = useRef(retryDelays);
  const intervalRef = useRef(intervalMs);
  const seq = useRef(0);
  const stopped = useRef(false);
  const alive = useRef(true);
  const offlineRun = useRef(0);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const tickRef = useRef<() => void>(() => {});

  useEffect(() => {
    loadRef.current = load;
    delaysRef.current = retryDelays;
    intervalRef.current = intervalMs;
  });

  const schedule = useCallback((ms: number) => {
    if (timer.current !== null) clearTimeout(timer.current);
    timer.current = setTimeout(() => tickRef.current(), ms);
  }, []);

  const run = useCallback(async (manual = false) => {
    const mine = ++seq.current;
    const r = await loadRef.current();
    if (!alive.current || mine !== seq.current) return; // unmounted, or a newer load answered first
    stopped.current = r.kind === "unauthorized";
    if (manual) offlineRun.current = 0; // a press starts the ladder again, it never climbs it
    const delays = delaysRef.current;
    let next = intervalRef.current;
    let retry: number | null = null;
    if (r.kind === "offline" && delays && delays.length > 0) {
      retry = delays[Math.min(offlineRun.current, delays.length - 1)];
      offlineRun.current++;
      next = retry;
    } else {
      offlineRun.current = 0;
    }
    setResult(r);
    setRetryMs(retry);
    if (stopped.current) {
      if (timer.current !== null) clearTimeout(timer.current);
      timer.current = null;
    } else schedule(next);
  }, [schedule]);

  const tick = useCallback(() => {
    if (stopped.current) return; // only refresh() or a new resetKey starts it again
    if (isVisible()) void run();
    else schedule(intervalRef.current);
  }, [run, schedule]);
  tickRef.current = tick;

  useEffect(() => {
    alive.current = true;
    stopped.current = false;
    offlineRun.current = 0;
    setResult(null);
    setRetryMs(null);
    tick();
    document.addEventListener("visibilitychange", tick);
    return () => {
      alive.current = false;
      seq.current++;
      if (timer.current !== null) clearTimeout(timer.current);
      timer.current = null;
      document.removeEventListener("visibilitychange", tick);
    };
  }, [intervalMs, resetKey, tick]);

  const lastWake = useRef(wake);
  useEffect(() => {
    if (wake === lastWake.current) return;
    lastWake.current = wake;
    void run();
  }, [wake, run]);

  const refresh = useCallback(() => run(true), [run]);
  return { result, refresh, retryMs };
}
