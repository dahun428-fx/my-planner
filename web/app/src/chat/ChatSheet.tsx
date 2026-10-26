import "./zodJitless"; // first: before "@ai-sdk/react" and "ai" build their schemas
import { useChat } from "@ai-sdk/react";
import type { UIMessage } from "ai";
import { useRouter } from "next/router";
import { type FormEvent, type KeyboardEvent, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { failureText } from "../api/actions";
import { apiFetch, apiGet } from "../api/client";
import type { ConversationsClosed, Today } from "../api/types.gen";
import { BlockError } from "../components/BlockError";
import { Icon } from "../components/icons";
import { Sheet } from "../components/Sheet";
import { CHAT_ACTIVITY_MS, useToast } from "../components/Toast";
import { notifyDataChanged } from "../lib/push";
import { loadConn } from "../lib/connection";
import { useConnection } from "../lib/ConnectionProvider";
import { copy } from "../lib/copy";
import { newClientMsgId } from "../lib/ids";
import { formatKst } from "../lib/time";
import { screenHref } from "../ui/openScreen";
import type { OpenScreen } from "../ui/primitives/types";
import styles from "./ChatSheet.module.css";
import { chatActivityToast } from "./activityToast";
import { ConversationList } from "./ConversationList";
import { loadHistory, type Meta } from "./history";
import { saveParts } from "./localParts";
import { MessageView } from "./MessageView";
import { conversationIdOf, toViewParts, type ViewPart } from "./parts";
import { QuickChips, WRITING_ID } from "./QuickChips";
import { type Chip, isWriteKey, quickChips, type WireChip } from "./quickChips";
import { sheetState } from "./sheetContext";
import { stopOnBe } from "./stop";
import { type ChatCtx, InFlightError, makeTransport } from "./transport";

const GAP_MS = 10 * 60_000;
// The front chip depends on the time (a check-in window, an event within 3 hours): looked at again each minute.
const CHIP_TICK_MS = 60_000;
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
  const router = useRouter();
  const online = state?.kind === "online";
  const connRef = useRef(conn);
  connRef.current = conn;
  const onSentRef = useRef(onSent);
  onSentRef.current = onSent;
  const toast = useToast();
  const toastRef = useRef(toast);
  toastRef.current = toast;
  const ctx = useRef<ChatCtx>({ conversationId: null, checkinId: checkinId ?? null });
  ctx.current.checkinId = checkinId ?? null;
  // SP9 7.3: the conversation picked from the list goes with every message (never from the check-in screen's box).
  const embeddedRef = useRef(embedded);
  embeddedRef.current = embedded;
  const picked = () => (embeddedRef.current ? null : sheetState.pickedConversationId);

  const [phase, setPhase] = useState<"queued" | "thinking" | null>(null);
  const [failure, setFailure] = useState<"retry" | "notReceived" | null>(null);
  const [inFlight, setInFlight] = useState(false);
  const [restored, setRestored] = useState<Record<string, ViewPart[]>>({});
  const [elsewhere, setElsewhere] = useState<string[]>([]);
  const [historyCount, setHistoryCount] = useState(0);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [text, setText] = useState("");
  const [fieldRows, setFieldRows] = useState(1);
  // SP9 9.5: the list screen inside the sheet, /today for the quick chips, and the minute they were judged at.
  const [view, setView] = useState<"chat" | "list">("chat");
  const [today, setToday] = useState<Today | null>(null);
  const [now, setNow] = useState(() => Date.now());
  const [starting, setStarting] = useState(false);
  // SP9c 3: an add chip pressed: the input is a one-line write of that kind until it is sent or closed.
  const [writing, setWriting] = useState<Chip | null>(null);
  const field = useRef<HTMLTextAreaElement>(null);

  const sending = useRef(false);
  const autoRetried = useRef(false);
  const lastError = useRef<Error | null>(null);
  const regenerateRef = useRef<() => Promise<void>>(async () => {});
  // The stop button was pressed for the answer coming now: its abort is not a cut (no resend, no failure line).
  const stopping = useRef(false);
  const showStoppedRef = useRef<(m: UIMessage, all: UIMessage[]) => void>(() => {});
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
        () => ({ ...ctx.current, resumeConversationId: picked() }),
      ),
    [],
  );

  const settle = useCallback((f: "retry" | "notReceived" | null) => {
    sending.current = false;
    setInFlight(false);
    setFailure(f);
  }, []);

  const { messages, setMessages, sendMessage, regenerate, status, stop } = useChat({
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
    onFinish: ({ message, messages: all, isAbort, isError }) => {
      setPhase(null);
      const stopped = stopping.current;
      stopping.current = false;
      if (stopped && (isAbort || isError)) {
        lastError.current = null;
        settle(null);
        showStoppedRef.current(message, all);
        return;
      }
      if (isError || isAbort) {
        // Only the stop button aborts on purpose (above), so any other abort is a cut as well.
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
      readTodayRef.current(); // a check-in answered, an event made: the chips may change
      const conv = conversationIdOf(message);
      if (conv !== null) ctx.current.conversationId = conv;
      const parts = toViewParts(message);
      // SP9 9.6: the answer's changes get one toast with "되돌리기" for 6 s; the chat keeps one line.
      const changed = chatActivityToast(parts);
      // An answer that wrote something (an activity line or a card) has the screens behind read again now.
      if (parts.some((p) => p.kind !== "text")) notifyDataChanged();
      if (changed) toastRef.current.showFor(changed, CHAT_ACTIVITY_MS);
      void saveParts(message.id, parts, sentTo.current);
    },
  });
  regenerateRef.current = () => regenerate();
  // A stopped answer keeps what already came and ends with the stopped line (the BE stores the same,
  // so the history shows it again on reopening). Stopped before its start, it is that line alone.
  showStoppedRef.current = (message, all) => {
    const line = { type: "text" as const, text: copy.chat.stopped };
    const i = all.findIndex((m) => m.id === message.id);
    const shown: UIMessage =
      i === -1
        ? { id: message.id, role: "assistant", parts: [line], metadata: { ...metaOf(message), at: new Date().toISOString() } }
        : { ...all[i], parts: [...all[i].parts, line] };
    setMessages(i === -1 ? [...all, shown] : all.map((m, k) => (k === i ? shown : m)));
    void saveParts(shown.id, toViewParts(shown), sentTo.current);
  };

  // SP9 9.5: the chips are judged from /today (check-in and review state, today's events). Not on the
  // check-in screen's box, which has no chips. Without an answer only the fixed four show.
  const readToday = useCallback(() => {
    if (embeddedRef.current) return;
    void apiGet<Today>("/today", "Today").then((r) => {
      if (r.kind === "ok") setToday(r.data);
    });
    setNow(Date.now());
  }, []);
  const readTodayRef = useRef(readToday);
  readTodayRef.current = readToday;
  useEffect(() => {
    if (!open || embedded) return;
    readToday();
    const t = setInterval(() => setNow(Date.now()), CHIP_TICK_MS);
    return () => clearInterval(t);
  }, [open, embedded, readToday]);

  // Opening shows the conversation as the BE has it (unless an answer is still coming): the one picked
  // from the list when there is one, else the given one (or the latest).
  const seq = useRef(0);
  const load = useCallback(() => {
    const mine = ++seq.current;
    setLoading(true);
    setLoadError(null);
    const pick = picked();
    const notBefore = pick === null && conversationId === undefined && !embeddedRef.current ? sheetState.freshSince : null;
    void loadHistory(pick ?? conversationId, { notBefore }).then((r) => {
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

  // SP9 9.5: closing the sheet (or leaving it for another BE) forgets the pick and the list screen.
  useEffect(() => {
    if (embedded) return;
    if (!open) {
      sheetState.pickedConversationId = null;
      focusAfter.current = null;
      setView("chat");
      setWriting(null);
    }
  }, [open, embedded]);
  useEffect(
    () => () => {
      if (!embeddedRef.current) {
        sheetState.pickedConversationId = null;
        sheetState.freshSince = null;
      }
    },
    [],
  );

  // An empty chat: the next message is a new conversation (no id, no pick).
  const clearView = useCallback(() => {
    seq.current += 1; // a history still coming is not shown
    sheetState.pickedConversationId = null;
    ctx.current.conversationId = null;
    setLoading(false);
    setMessages([]);
    setHistoryCount(0);
    setRestored({});
    setElsewhere([]);
    setFailure(null);
    setLoadError(null);
  }, [setMessages]);

  // Also on the way back from the list screen: the log is a fresh element then (review round 1).
  useEffect(() => {
    const el = list.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages, phase, failure, elsewhere, view]);

  // The pressed row or "새 대화" goes away with the list screen: focus moves to the list button (a
  // conversation is loading, the input is still off) or to the input (an empty chat). Review round 1.
  const focusAfter = useRef<"list" | "input" | null>(null);
  const listButton = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (view !== "chat" || focusAfter.current === null) return;
    const target = focusAfter.current === "list" ? listButton.current : field.current;
    focusAfter.current = null;
    target?.focus();
  }, [view, loading]);

  const busy = inFlight || status === "submitted" || status === "streaming";
  const readOnly = !online;
  const canSend = !readOnly && !loading && !busy;

  // `checkinId`: the message goes to that run (the check-in chip, SP9 9.5), without the picked conversation.
  // `chip`: the quick chip it came from (SP9c 4.1), kept in the message's metadata for its label.
  const send = (raw: string, { checkinId, chip }: { checkinId?: number; chip?: WireChip } = {}): boolean => {
    const t = raw.trim();
    if (t === "" || sending.current || !canSend) return false;
    sending.current = true; // a second press before the answer starts is ignored
    autoRetried.current = false;
    stopping.current = false;
    lastError.current = null;
    setInFlight(true);
    setFailure(null);
    setPhase(null);
    if (!embedded) sheetState.freshSince = null; // said something: the latest conversation is this one again
    const metadata: Meta = { at: new Date().toISOString(), ...(checkinId === undefined ? {} : { checkin_id: checkinId }) };
    if (chip) metadata.chip = chip;
    void sendMessage({ text: t, metadata });
    return true;
  };
  // SP9c 3: an add chip opens a one-line write (nothing is sent); the others send their sentence at once.
  const pressChip = (chip: Chip) => {
    if (chip.mode === "send") return void send(chip.text, { checkinId: chip.checkinId, chip: chip.wire });
    setWriting(chip);
    field.current?.focus();
  };
  const closeWrite = () => {
    setWriting(null);
    field.current?.focus();
  };
  // The input's text goes as a line of the open write, if there is one; after it the chip row comes back.
  const sendInput = () => {
    if (!send(text, { chip: writing?.wire })) return;
    setText("");
    setWriting(null);
  };
  // A card's button is a plain message, also during a write (which then ends).
  const chooseLabel = (label: string) => {
    if (send(label)) setWriting(null);
  };
  const openList = () => {
    setWriting(null);
    setView("list");
  };

  // SP9 9.5 / 7.3: a row of the list is read with /messages; from then on every message carries it.
  const openPicked = (id: number) => {
    if (sending.current) return; // an answer still coming stays on screen
    clearView();
    sheetState.pickedConversationId = id;
    sheetState.freshSince = null;
    focusAfter.current = "list";
    setView("chat");
    load();
  };
  // "새 대화": POST /conversations/new closes the open app conversation, then an empty chat.
  const startNew = async () => {
    if (starting || busy || readOnly) return;
    setStarting(true);
    const r = await apiFetch<ConversationsClosed>("POST", "/conversations/new", { model: "ConversationsClosed" });
    setStarting(false);
    if (r.kind !== "ok") {
      toastRef.current.show({ text: failureText(r) });
      return;
    }
    clearView();
    setWriting(null);
    sheetState.freshSince = new Date().toISOString();
    if (view === "list") focusAfter.current = "input"; // from the head, its icon keeps the focus
    setView("chat");
  };
  // A deleted conversation that is on screen leaves an empty chat (the BE closed it first, 7.6).
  const onDeleted = (id: number) => {
    if (id === ctx.current.conversationId || id === sheetState.pickedConversationId) {
      clearView();
      sheetState.freshSince = new Date().toISOString();
    }
  };

  // The send button while an answer is coming: stop here at once, and ask the BE to stop too (stop.ts).
  // Offline or refused, the BE goes on, and its answer shows in the history later instead of the stopped line.
  const stopAnswer = () => {
    if (!busy || stopping.current) return;
    const clientMsgId = [...messages].reverse().find((m) => m.role === "user")?.id;
    stopping.current = true;
    if (clientMsgId) void stopOnBe(clientMsgId);
    void stop().then(() => {
      if (!stopping.current) return; // onFinish took it
      stopping.current = false; // nothing was in flight to abort (between a cut and its resend)
      setPhase(null);
      settle(null);
    });
  };

  const retry = () => {
    if (sending.current || readOnly) return;
    stopping.current = false;
    sending.current = true;
    setInFlight(true);
    setFailure(null);
    void regenerate();
  };

  // SP6 8 `open`: the app moves to that screen and the sheet closes (embedded in a check-in, it has none to close).
  const openScreen = (s: OpenScreen) => openPath(screenHref(s));
  // SP9 9.8: the same for an address the app made itself (a ui_events row: /schedule/?date=).
  const openPath = (path: string) => {
    void router.push(path);
    onClose();
  };

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    sendInput();
  };
  // Enter sends, as the keyboard's send key says; Shift+Enter is a new line, and an Enter that ends
  // a Korean syllable (IME composition) is not a send. keyCode 229 covers Safari, which can
  // report isComposing false on the Enter that ends a composition.
  // SP9c 3: Backspace in the empty input ends a one-line write.
  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if ((e.key === "Backspace" || e.keyCode === 8) && text === "" && writing) setWriting(null); // 8: some Android keyboards
    if (e.key !== "Enter" || e.shiftKey || e.nativeEvent.isComposing || e.keyCode === 229) return;
    e.preventDefault();
    sendInput();
  };
  // DESIGN.md: one row, two when the text breaks a line or no longer fits; past that it scrolls
  // inside. The rows attribute, never a style height (CSP).
  useLayoutEffect(() => {
    const el = field.current;
    if (!el) return;
    el.rows = 1;
    const next = text.includes("\n") || el.scrollHeight > el.clientHeight + 1 ? 2 : 1;
    el.rows = next;
    setFieldRows(next);
  }, [text]);
  const ready = canSend && text.trim() !== "";

  // Dividers (5.5.2): the time when the conversation changes or after a gap of more than 10 minutes.
  // Right after the history it was read for, not after what is said now.
  const elsewhereLines = elsewhere.map((line, k) => (
    <p key={`e-${k}`} className={styles.elsewhere}>
      {copy.chat.elsewhere(line)}
    </p>
  ));
  const rows: React.ReactNode[] = [];
  let prevConv: number | null = null;
  // A conversation already on screen is not "새 대화" when the talk goes back to it (a picked
  // conversation after a check-in chip's answer, review round 1).
  const shownConvs = new Set<number>();
  let prevAt: string | null = null;
  messages.forEach((m, i) => {
    const meta = metaOf(m);
    let conv = conversationIdOf(m);
    if (conv === null && m.role === "user") {
      const reply = messages.slice(i + 1).find((n) => n.role === "assistant");
      conv = reply ? conversationIdOf(reply) : null;
    }
    const newConv = conv !== null && prevConv !== null && conv !== prevConv && !shownConvs.has(conv);
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
    rows.push(<MessageView key={m.id} message={m} parts={parts} readOnly={readOnly || busy} onChoose={chooseLabel} onOpen={openScreen} onOpenPath={openPath} />);
    if (i === historyCount - 1) rows.push(elsewhereLines);
    if (conv !== null) {
      prevConv = conv;
      shownConvs.add(conv);
    }
    if (at !== null) prevAt = at;
  });

  const chips = quickChips(today, new Date(now));

  const last = messages[messages.length - 1];
  const answering = busy && last?.role === "assistant" && toViewParts(last).length > 0;
  const reason =
    state?.kind === "offline"
      ? copy.offline.chatLater
      : state?.kind === "unauthorized" || state?.kind === "rate_limited" || state?.kind === "safe_mode"
        ? copy.chat.launcherBlocked[state.kind]
        : null;

  const closeButton = (
    <button type="button" className={styles.close} onClick={onClose}>
      {copy.chat.close}
    </button>
  );
  // SP9 9.5: the list button at the left of the head; "새 대화" at the right, left of 닫기.
  const chatHead = (
    <header className={styles.header}>
      <button ref={listButton} type="button" className={styles.headIcon} aria-label={copy.chat.pastConversations} onClick={openList}>
        <Icon name="list" />
      </button>
      <div className={styles.heading}>
        <h2 className={styles.title}>{copy.chat.title}</h2>
        <p className={styles.subtitle}>{copy.chat.subtitle}</p>
      </div>
      <div className={styles.headEnd}>
        <button
          type="button"
          className={styles.headIcon}
          aria-label={copy.chat.newConversation}
          disabled={readOnly || busy || starting}
          onClick={() => void startNew()}
        >
          <Icon name="compose" />
        </button>
        {closeButton}
      </div>
    </header>
  );
  const listHead = (
    <header className={styles.header}>
      <button type="button" className={styles.back} onClick={() => setView("chat")}>
        {copy.chat.backToChat}
      </button>
      <h2 className={styles.title}>{copy.chat.pastConversations}</h2>
      <div className={styles.headEnd}>{closeButton}</div>
    </header>
  );

  if (!embedded && view === "list") {
    return (
      <Sheet open={open} onClose={onClose} tall ariaLabel={copy.chat.title}>
        <div className={styles.frame}>
          {listHead}
          <ConversationList readOnly={readOnly || busy || starting} onOpen={openPicked} onNew={() => void startNew()} onDeleted={onDeleted} />
        </div>
      </Sheet>
    );
  }

  const content = (
    <div className={embedded ? styles.embedded : styles.frame}>
      {!embedded && chatHead}
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
      {!embedded && <QuickChips chips={chips} disabled={!canSend} writing={writing} onPress={pressChip} onCloseWrite={closeWrite} />}
      <form className={styles.composer} onSubmit={onSubmit}>
        <textarea
          ref={field}
          className={styles.input}
          rows={fieldRows}
          aria-label={copy.chat.inputLabel}
          placeholder={writing && isWriteKey(writing.key) ? copy.chat.write[writing.key] : undefined}
          aria-describedby={writing ? WRITING_ID : undefined}
          value={text}
          disabled={readOnly || loading}
          enterKeyHint="send"
          autoComplete="off"
          data-ready={ready ? "" : undefined}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={onKeyDown}
        />
        {busy ? (
          // While an answer is coming the send button is the stop button (enabled with an empty field).
          <button type="button" className={`${styles.send} pressable`} aria-label={copy.chat.stop} onClick={stopAnswer}>
            <span className={styles.sendMark} aria-hidden="true">
              <Icon name="stop" />
            </span>
          </button>
        ) : (
          <button type="submit" className={`${styles.send} pressable`} aria-label={copy.chat.send} disabled={!ready}>
            <span className={styles.sendMark} aria-hidden="true">
              <Icon name="send" />
            </span>
          </button>
        )}
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
