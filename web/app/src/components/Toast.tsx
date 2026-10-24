import { createContext, type ReactNode, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { failureText, undoActivity } from "../api/actions";
import { copy } from "../lib/copy";
import { useConnection } from "../lib/ConnectionProvider";
import styles from "./Toast.module.css";

export interface ToastContent {
  text: string;
  undoId?: number | null;
}

export interface ToastApi {
  show(t: ToastContent): void;
  /** Subscribe to "something was undone" (a screen's refresh). Returns an unsubscribe function. */
  onUndone(cb: () => void): () => void;
}

const SHOW_MS = 4000;
const RECONNECT_MS = 2000;

const ToastContext = createContext<ToastApi>({ show: () => {}, onUndone: () => () => {} });

export function useToast(): ToastApi {
  return useContext(ToastContext);
}

interface Current extends ToastContent {
  seq: number;
}

// The line above the tab bar (spec F8): 4 s, a new one replaces the old one, "되돌리기" when the
// write can be undone. Also says "다시 연결됐어요" for 2 s when the connection comes back.
export function ToastProvider({ children }: { children: ReactNode }) {
  const [current, setCurrent] = useState<Current | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);
  const undoing = useRef(new Set<number>());
  const seq = useRef(0);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const undone = useRef(new Set<() => void>());
  const { onReconnect } = useConnection();

  const showFor = useCallback((t: ToastContent, ms: number) => {
    if (timer.current) clearTimeout(timer.current);
    const mine = ++seq.current;
    setCurrent({ ...t, seq: mine });
    timer.current = setTimeout(() => {
      setCurrent((c) => (c?.seq === mine ? null : c));
    }, ms);
  }, []);

  const show = useCallback((t: ToastContent) => showFor(t, SHOW_MS), [showFor]);

  const onUndone = useCallback((cb: () => void) => {
    undone.current.add(cb);
    return () => {
      undone.current.delete(cb);
    };
  }, []);

  useEffect(() => onReconnect(() => showFor({ text: copy.status.reconnected }, RECONNECT_MS)), [onReconnect, showFor]);
  useEffect(
    () => () => {
      if (timer.current) clearTimeout(timer.current);
    },
    [],
  );

  const undo = useCallback(
    async (id: number) => {
      if (undoing.current.has(id)) return;
      undoing.current.add(id);
      setBusyId(id);
      try {
        const out = await undoActivity(id);
        if (out.kind === "undone") {
          show({ text: out.confirmation });
          undone.current.forEach((cb) => cb());
        } else if (out.kind === "already_undone") {
          setCurrent(null);
          undone.current.forEach((cb) => cb());
        } else if (out.kind === "blocked") {
          show({ text: copy.activity.undoBlocked[out.reason] });
        } else {
          const k = out.result.kind;
          const known = k === "offline" || k === "unauthorized" || k === "rate_limited" || k === "safe_mode";
          show({ text: known ? failureText(out.result) : copy.actions.undoFailed });
        }
      } finally {
        undoing.current.delete(id);
        setBusyId((b) => (b === id ? null : b));
      }
    },
    [show],
  );

  const api = useMemo(() => ({ show, onUndone }), [show, onUndone]);
  const undoId = current?.undoId ?? null;
  return (
    <ToastContext.Provider value={api}>
      {children}
      <div className={styles.region} role="status">
        {current && (
          <div className={styles.toast} key={current.seq}>
            <span className={styles.text}>{current.text}</span>
            {undoId !== null && (
              <button type="button" className={styles.undo} disabled={busyId === undoId} onClick={() => void undo(undoId)}>
                {copy.activity.undo}
              </button>
            )}
          </div>
        )}
      </div>
    </ToastContext.Provider>
  );
}
