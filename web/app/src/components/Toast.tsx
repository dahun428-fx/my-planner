import { createContext, type ReactNode, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { undoActivity, undoFailureText, useUndo } from "../api/actions";
import { copy } from "../lib/copy";
import { useConnection } from "../lib/ConnectionProvider";
import styles from "./Toast.module.css";

export interface ToastContent {
  text: string;
  undoId?: number | null;
  /** SP9 9.6: several activities of one chat answer; "되돌리기" undoes them all, newest first. */
  undoIds?: number[];
}

export interface ToastApi {
  /** For SHOW_MS (4 s). */
  show(t: ToastContent): void;
  /** For `ms`: the chat's activity toast uses CHAT_ACTIVITY_MS (SP9 9.6); every other toast `show`. */
  showFor(t: ToastContent, ms: number): void;
  /** Subscribe to "something was undone" (a screen's refresh). Returns an unsubscribe function. */
  onUndone(cb: () => void): () => void;
}

const SHOW_MS = 4000;
const RECONNECT_MS = 2000;
/** SP9 9.6: a chat answer's changes stay on the toast this long (only those). */
export const CHAT_ACTIVITY_MS = 6000;

const ToastContext = createContext<ToastApi>({ show: () => {}, showFor: () => {}, onUndone: () => () => {} });

const idsOf = (t: ToastContent): number[] => (t.undoIds && t.undoIds.length > 0 ? t.undoIds : t.undoId != null ? [t.undoId] : []);

export function useToast(): ToastApi {
  return useContext(ToastContext);
}

interface Current extends ToastContent {
  seq: number;
}

// The line above the tab bar (spec F8): 4 s (a chat answer's changes 6 s, SP9 9.6), a new one
// replaces the old one, "되돌리기" when the write can be undone. Also says "다시 연결됐어요" for 2 s
// when the connection comes back.
export function ToastProvider({ children }: { children: ReactNode }) {
  const [current, setCurrent] = useState<Current | null>(null);
  const seq = useRef(0);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const undone = useRef(new Set<() => void>());
  const { onReconnect, state } = useConnection();

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

  const { undo: send, busy } = useUndo(show);
  const notifyUndone = () => undone.current.forEach((cb) => cb());
  const undoOne = async (id: number) => {
    const out = await send(id);
    if (out?.kind === "undone") {
      notifyUndone();
    } else if (out?.kind === "already_undone") {
      setCurrent(null);
      notifyUndone();
    } else if (out?.kind === "blocked") {
      show({ text: copy.activity.undoBlocked[out.reason] });
    }
  };

  // SP9 9.6: several at once go one by one, newest first; the first refusal stops the rest.
  const multi = useRef(new Set<number>());
  const [multiBusy, setMultiBusy] = useState<ReadonlySet<number>>(new Set());
  const undoAll = async (ids: number[]) => {
    if (ids.some((id) => multi.current.has(id))) return; // the first press is still going
    ids.forEach((id) => multi.current.add(id));
    setMultiBusy(new Set(multi.current));
    let k = 0;
    try {
      for (const id of [...ids].sort((a, b) => b - a)) {
        const out = await undoActivity(id);
        if (out.kind === "undone" || out.kind === "already_undone") {
          k += 1;
          continue;
        }
        if (k > 0) show({ text: copy.chat.undonePartly(k) });
        else show({ text: out.kind === "blocked" ? copy.activity.undoBlocked[out.reason] : undoFailureText(out.result) });
        return;
      }
      show({ text: copy.chat.undone });
    } finally {
      ids.forEach((id) => multi.current.delete(id));
      setMultiBusy(new Set(multi.current));
      if (k > 0) notifyUndone();
    }
  };
  const undo = (ids: number[]) => (ids.length === 1 ? undoOne(ids[0]) : undoAll(ids));

  const api = useMemo(() => ({ show, showFor, onUndone }), [show, showFor, onUndone]);
  const ids = current ? idsOf(current) : [];
  // A chat answer's undo (undoIds) is off while not online, as the old chat box's was (read-only).
  const offline = current?.undoIds !== undefined && state?.kind !== "online";
  const pending = offline || ids.some((id) => busy.has(id) || multiBusy.has(id));
  return (
    <ToastContext.Provider value={api}>
      {children}
      <div className={styles.region} role="status">
        {current && (
          <div className={styles.toast} key={current.seq}>
            <span className={styles.text}>{current.text}</span>
            {ids.length > 0 && (
              <button type="button" className={styles.undo} disabled={pending} onClick={() => void undo(ids)}>
                {copy.activity.undo}
              </button>
            )}
          </div>
        )}
      </div>
    </ToastContext.Provider>
  );
}
