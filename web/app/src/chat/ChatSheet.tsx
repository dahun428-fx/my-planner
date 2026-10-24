import "./zodJitless"; // first: before "@ai-sdk/react" and "ai" build their schemas
import { useChat } from "@ai-sdk/react";
import type { UIMessage } from "ai";
import { type FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { BlockError } from "../components/BlockError";
import { Sheet } from "../components/Sheet";
import { loadConn } from "../lib/connection";
import { useConnection } from "../lib/ConnectionProvider";
import { copy } from "../lib/copy";
import { newClientMsgId } from "../lib/ids";
import { formatKst } from "../lib/time";
import styles from "./ChatSheet.module.css";
import { loadHistory, type Meta } from "./history";
import { saveParts } from "./localParts";
import { MessageView } from "./MessageView";
import { conversationIdOf, toViewParts, type ViewPart } from "./parts";
import { type ChatCtx, InFlightError, makeTransport } from "./transport";

const GAP_MS = 10 * 60_000;
const isObj = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null && !Array.isArray(v);

// --- retries ---

// A cut connection may have hidden an answer the BE did store: resend the same message once.
// An `error` chunk or a refused request (4xx/5xx) is an answer, and is not sent again. A 409 for a
// message still being answered is neither: "다시 받기" sends the same id later (not at once).
const isCut = (e: Error | null) => e instanceof TypeError || e?.name === "AbortError" || e?.name === "StreamCutError";
const isInFlight = (e: Error | null) => e instanceof InFlightError;

const metaOf = (m: UIMessage): Meta => (isObj(m.metadata) ? (m.metadata as Meta) : {});

// --- the sheet ---

export interface ChatSheetProps {
  open: boolean;
  onClose(): void;
  checkinId?: number;
  /** A given conversation (null: a new, empty one). Left out: the latest app conversation. */
  conversationId?: number | null;
  /** Inside a screen (check-in, A06) instead of a sheet. */
  embedded?: boolean;
  /** An answer to a sent message has finished (the screen around an embedded box reads again). */
  onSent?(): void;
}

// Spec 5.5.2, 4.6 대화, F4, F9.
export function ChatSheet({ open, onClose, checkinId, conversationId, embedded = false, onSent }: ChatSheetProps) {
  const { state, conn } = useConnection();
  const online = state?.kind === "online";
  const connRef = useRef(conn);
  connRef.current = conn;
  const onSentRef = useRef(onSent);
  onSentRef.current = onSent;
  const ctx = useRef<ChatCtx>({ conversationId: null, checkinId: checkinId ?? null });
  ctx.current.checkinId = checkinId ?? null;

  const [phase, setPhase] = useState<"queued" | "thinking" | null>(null);
  const [failure, setFailure] = useState<"retry" | "notReceived" | null>(null);
  const [inFlight, setInFlight] = useState(false);
  const [restored, setRestored] = useState<Record<string, ViewPart[]>>({});
  const [elsewhere, setElsewhere] = useState<string[]>([]);
  const [historyCount, setHistoryCount] = useState(0);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [text, setText] = useState("");

  const sending = useRef(false);
  const autoRetried = useRef(false);
  const lastError = useRef<Error | null>(null);
  const regenerateRef = useRef<() => Promise<void>>(async () => {});
  const list = useRef<HTMLDivElement>(null);

  // The BE the last request went to: an answer's parts are kept only while the device is still connected there.
  const sentTo = useRef("");
  const transport = useMemo(
    () =>
      makeTransport(
        () => {
          const c = connRef.current ?? loadConn() ?? { beUrl: "", token: "" };
          sentTo.current = c.beUrl;
          return c;
        },
        () => ctx.current,
      ),
    [],
  );

  const settle = useCallback((f: "retry" | "notReceived" | null) => {
    sending.current = false;
    setInFlight(false);
    setFailure(f);
  }, []);

  const { messages, setMessages, sendMessage, regenerate, status } = useChat({
    transport,
    generateId: newClientMsgId,
    resume: false,
    onData: (part) => {
      if (part.type !== "data-status") return;
      const s = isObj(part.data) ? part.data.state : null;
      if (s === "queued" || s === "thinking") setPhase(s);
    },
    onError: (e) => {
      lastError.current = e;
    },
    onFinish: ({ message, isAbort, isError }) => {
      setPhase(null);
      if (isError || isAbort) {
        // Nothing here aborts on purpose, so an abort is a cut as well.
        const cut = isAbort || isCut(lastError.current);
        const later = isInFlight(lastError.current);
        lastError.current = null;
        if (later) {
          settle("retry");
          return;
        }
        if (cut && !autoRetried.current) {
          autoRetried.current = true;
          void Promise.resolve().then(() => regenerateRef.current());
          return;
        }
        settle(cut ? "retry" : "notReceived");
        return;
      }
      settle(null);
      onSentRef.current?.();
      const conv = conversationIdOf(message);
      if (conv !== null) ctx.current.conversationId = conv;
      void saveParts(message.id, toViewParts(message), sentTo.current);
    },
  });
  regenerateRef.current = () => regenerate();

  // Opening shows the conversation as the BE has it (unless an answer is still coming).
  const seq = useRef(0);
  const load = useCallback(() => {
    const mine = ++seq.current;
    setLoading(true);
    setLoadError(null);
    void loadHistory(conversationId).then((r) => {
      if (mine !== seq.current) return;
      setLoading(false);
      if (r.kind === "offline") return; // the last view stays, read-only (F9)
      if (r.kind === "failed") {
        setLoadError(r.code);
        return;
      }
      const h = r.history;
      ctx.current.conversationId = h.conversationId;
      setMessages(h.messages);
      setHistoryCount(h.messages.length);
      setRestored(h.restored);
      setElsewhere(h.elsewhere);
      setFailure(null);
    });
  }, [conversationId, setMessages]);
  useEffect(() => {
    if (open && !sending.current) load();
  }, [open, load]);

  useEffect(() => {
    const el = list.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages, phase, failure, elsewhere]);

  const busy = inFlight || status === "submitted" || status === "streaming";
  const readOnly = !online;
  const canSend = !readOnly && !loading && !busy;

  const send = (raw: string): boolean => {
    const t = raw.trim();
    if (t === "" || sending.current || !canSend) return false;
    sending.current = true; // a second press before the answer starts is ignored
    autoRetried.current = false;
    lastError.current = null;
    setInFlight(true);
    setFailure(null);
    setPhase(null);
    void sendMessage({ text: t, metadata: { at: new Date().toISOString() } satisfies Meta });
    return true;
  };

  const retry = () => {
    if (sending.current || readOnly) return;
    sending.current = true;
    setInFlight(true);
    setFailure(null);
    void regenerate();
  };

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (send(text)) setText("");
  };

  // Dividers (5.5.2): the time when the conversation changes or after a gap of more than 10 minutes.
  // Right after the history it was read for, not after what is said now.
  const elsewhereLines = elsewhere.map((line, k) => (
    <p key={`e-${k}`} className={styles.elsewhere}>
      {copy.chat.elsewhere(line)}
    </p>
  ));
  const rows: React.ReactNode[] = [];
  let prevConv: number | null = null;
  let prevAt: string | null = null;
  messages.forEach((m, i) => {
    const meta = metaOf(m);
    let conv = conversationIdOf(m);
    if (conv === null && m.role === "user") {
      const reply = messages.slice(i + 1).find((n) => n.role === "assistant");
      conv = reply ? conversationIdOf(reply) : null;
    }
    const newConv = conv !== null && prevConv !== null && conv !== prevConv;
    const at = typeof meta.at === "string" ? meta.at : prevAt;
    const gap = at !== null && prevAt !== null && Date.parse(at) - Date.parse(prevAt) > GAP_MS;
    if (newConv) {
      rows.push(
        <p key={`c-${m.id}`} className={styles.divider}>
          {copy.chat.newConversation}
        </p>,
      );
    }
    if (at !== null && (i === 0 || newConv || gap)) {
      rows.push(
        <p key={`t-${m.id}`} className={`${styles.time} tnum`}>
          {formatKst(at, "HH:mm")}
        </p>,
      );
    }
    const parts = [...toViewParts(m), ...(restored[m.id] ?? [])];
    rows.push(<MessageView key={m.id} message={m} parts={parts} readOnly={readOnly || busy} onChoose={(label) => void send(label)} />);
    if (i === historyCount - 1) rows.push(elsewhereLines);
    if (conv !== null) prevConv = conv;
    if (at !== null) prevAt = at;
  });

  const last = messages[messages.length - 1];
  const answering = busy && last?.role === "assistant" && toViewParts(last).length > 0;
  const reason =
    state?.kind === "offline"
      ? copy.offline.chatLater
      : state?.kind === "unauthorized" || state?.kind === "rate_limited" || state?.kind === "safe_mode"
        ? copy.chat.launcherBlocked[state.kind]
        : null;

  const content = (
    <div className={embedded ? styles.embedded : styles.frame}>
      {!embedded && (
        <header className={styles.header}>
          <button type="button" className={styles.close} onClick={onClose}>
            {copy.chat.close}
          </button>
          <h2 className={styles.title}>{copy.chat.title}</h2>
          <p className={styles.subtitle}>{copy.chat.subtitle}</p>
        </header>
      )}
      <div ref={list} className={styles.list} role="log" aria-label={copy.chat.messages}>
        {rows}
        {busy && !answering && phase === "queued" && (
          <p className={styles.status} role="status">
            {copy.chat.queued}
          </p>
        )}
        {busy && !answering && phase === "thinking" && (
          <p className={styles.dots} role="status" aria-label={copy.chat.thinking}>
            <span className={styles.dot} />
            <span className={styles.dot} />
            <span className={styles.dot} />
          </p>
        )}
        {failure && (
          <p className={styles.failure}>
            <span>{copy.chat.notReceived}</span>
            {failure === "retry" && (
              <button type="button" className={styles.retry} disabled={readOnly} onClick={retry}>
                {copy.chat.retry}
              </button>
            )}
          </p>
        )}
        {online && loadError !== null && <BlockError code={loadError} onRetry={load} />}
      </div>
      {reason && <p className={styles.reason}>{reason}</p>}
      <form className={styles.composer} onSubmit={onSubmit}>
        <input
          className={styles.input}
          type="text"
          aria-label={copy.chat.inputLabel}
          value={text}
          disabled={readOnly || loading}
          enterKeyHint="send"
          autoComplete="off"
          onChange={(e) => setText(e.target.value)}
        />
        <button type="submit" className={styles.send} disabled={!canSend || text.trim() === ""}>
          {copy.chat.send}
        </button>
      </form>
    </div>
  );

  if (embedded) return content;
  return (
    <Sheet open={open} onClose={onClose} tall ariaLabel={copy.chat.title}>
      {content}
    </Sheet>
  );
}
