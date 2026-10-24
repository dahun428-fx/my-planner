import { useChat } from "@ai-sdk/react";
import type { UIMessage } from "ai";
import { type FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { apiFetch } from "../api/client";
import type { Conversations } from "../api/types.gen";
import { validateModel } from "../api/validate";
import { Sheet } from "../components/Sheet";
import { loadConn } from "../lib/connection";
import { useConnection } from "../lib/ConnectionProvider";
import { copy } from "../lib/copy";
import { newClientMsgId } from "../lib/ids";
import { formatKst } from "../lib/time";
import styles from "./ChatSheet.module.css";
import { loadParts, saveParts } from "./localParts";
import { MessageView } from "./MessageView";
import { conversationIdOf, toViewParts, type ViewPart } from "./parts";
import { type ChatCtx, makeTransport } from "./transport";

// --- history ---

const GAP_MS = 10 * 60_000;
const ELSEWHERE_MAX = 3;

type Meta = { conversation_id?: number | null; at?: string };
type Line = { id?: string; at: string; speaker: "user" | "secretary"; text: string };

interface History {
  conversationId: number | null;
  messages: UIMessage[];
  restored: Record<string, ViewPart[]>;
  elsewhere: string[];
}

const EMPTY: History = { conversationId: null, messages: [], restored: {}, elsewhere: [] };
const isObj = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null && !Array.isArray(v);

// Read leniently: a BE before R4d has no `id` on the lines (then they show as text only).
function readLines(data: unknown): Line[] | null {
  if (!isObj(data) || !Array.isArray(data.items)) return null;
  const out: Line[] = [];
  for (const m of data.items) {
    if (!isObj(m) || typeof m.at !== "string" || typeof m.text !== "string" || (m.speaker !== "user" && m.speaker !== "secretary")) return null;
    out.push({ id: typeof m.id === "string" && m.id !== "" ? m.id : undefined, at: m.at, speaker: m.speaker, text: m.text });
  }
  return out;
}

// Spec 5.5.2: what changed outside the app after this conversation's last line, one summary a line.
async function readElsewhere(since: string): Promise<string[]> {
  const r = await apiFetch<unknown>("GET", `/activity?since=${encodeURIComponent(since)}&limit=50`);
  if (r.kind !== "ok" || !isObj(r.data) || !Array.isArray(r.data.items)) return [];
  return r.data.items
    .filter((a): a is { channel: string; summary: string } => isObj(a) && typeof a.summary === "string" && typeof a.channel === "string" && a.channel !== "app")
    .map((a) => a.summary)
    .slice(-ELSEWHERE_MAX);
}

/** null: the history could not be read (keep what is on screen, F9). */
async function loadHistory(given: number | null | undefined): Promise<History | null> {
  let id: number | null = null;
  if (given !== undefined) {
    id = given;
  } else {
    const r = await apiFetch<Conversations>("GET", "/conversations?channel=app&limit=3", { model: "Conversations" });
    if (r.kind !== "ok" || !validateModel("Conversations", r.data)) return null;
    const latest = [...r.data.items].sort((a, b) => (a.last_message_at < b.last_message_at ? 1 : -1))[0];
    id = latest?.id ?? null;
  }
  if (id === null) return EMPTY;
  const r = await apiFetch<unknown>("GET", `/conversations/${id}/messages`);
  if (r.kind === "error" && r.status === 404) return EMPTY;
  if (r.kind !== "ok") return null;
  const lines = readLines(r.data);
  if (!lines) return null;
  const restored: Record<string, ViewPart[]> = {};
  const messages: UIMessage[] = [];
  for (let i = 0; i < lines.length; i++) {
    const l = lines[i];
    const mid = l.id ?? `h-${id}-${i}`;
    if (l.id && l.speaker === "secretary") {
      const parts = await loadParts(l.id);
      if (parts) restored[mid] = parts;
    }
    messages.push({
      id: mid,
      role: l.speaker === "user" ? "user" : "assistant",
      parts: [{ type: "text", text: l.text }],
      metadata: { conversation_id: id, at: l.at } satisfies Meta,
    });
  }
  const last = lines[lines.length - 1];
  const elsewhere = given === undefined && last ? await readElsewhere(last.at) : [];
  return { conversationId: id, messages, restored, elsewhere };
}

// --- retries ---

// A cut connection may have hidden an answer the BE did store: resend the same message once.
// An `error` chunk or a refused request (4xx/5xx) is an answer, and is not sent again.
const isCut = (e: Error | null) => e instanceof TypeError || e?.name === "AbortError" || e?.name === "StreamCutError";

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
}

// Spec 5.5.2, 4.6 대화, F4, F9.
export function ChatSheet({ open, onClose, checkinId, conversationId, embedded = false }: ChatSheetProps) {
  const { state, conn } = useConnection();
  const online = state?.kind === "online";
  const connRef = useRef(conn);
  connRef.current = conn;
  const ctx = useRef<ChatCtx>({ conversationId: null, checkinId: checkinId ?? null });
  ctx.current.checkinId = checkinId ?? null;

  const [phase, setPhase] = useState<"queued" | "thinking" | null>(null);
  const [failure, setFailure] = useState<"retry" | "notReceived" | null>(null);
  const [inFlight, setInFlight] = useState(false);
  const [restored, setRestored] = useState<Record<string, ViewPart[]>>({});
  const [elsewhere, setElsewhere] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [text, setText] = useState("");

  const sending = useRef(false);
  const autoRetried = useRef(false);
  const lastError = useRef<Error | null>(null);
  const regenerateRef = useRef<() => Promise<void>>(async () => {});
  const list = useRef<HTMLDivElement>(null);

  const transport = useMemo(
    () => makeTransport(() => connRef.current ?? loadConn() ?? { beUrl: "", token: "" }, () => ctx.current),
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
        lastError.current = null;
        if (cut && !autoRetried.current) {
          autoRetried.current = true;
          void Promise.resolve().then(() => regenerateRef.current());
          return;
        }
        settle(cut ? "retry" : "notReceived");
        return;
      }
      settle(null);
      const conv = conversationIdOf(message);
      if (conv !== null) ctx.current.conversationId = conv;
      void saveParts(message.id, toViewParts(message));
    },
  });
  regenerateRef.current = () => regenerate();

  // Opening shows the conversation as the BE has it (unless an answer is still coming).
  const seq = useRef(0);
  useEffect(() => {
    if (!open || sending.current) return;
    const mine = ++seq.current;
    setLoading(true);
    void loadHistory(conversationId).then((h) => {
      if (mine !== seq.current) return;
      setLoading(false);
      if (!h) return; // offline or unreadable: the last view stays, read-only (F9)
      ctx.current.conversationId = h.conversationId;
      setMessages(h.messages);
      setRestored(h.restored);
      setElsewhere(h.elsewhere);
      setFailure(null);
    });
  }, [open, conversationId, setMessages]);

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
          <div className={styles.heading}>
            <h2 className={styles.title}>{copy.chat.title}</h2>
            <p className={styles.subtitle}>{copy.chat.subtitle}</p>
          </div>
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
        {elsewhere.map((s, i) => (
          <p key={i} className={styles.elsewhere}>
            {copy.chat.elsewhere(s)}
          </p>
        ))}
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
