import "./zodJitless"; // first: before "@ai-sdk/react" and "ai" build their schemas
import { useChat } from "@ai-sdk/react";
import type { UIMessage } from "ai";
import { useRouter } from "next/router";
import { type ChangeEvent, type FormEvent, type KeyboardEvent, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { failureText } from "../api/actions";
import { type ApiResult, apiFetch, apiGet } from "../api/client";
import { dropLocalPhoto, keepLocalPhoto, uploadFailureText, uploadPhoto } from "../api/photos";
import type { ConversationsClosed, Today } from "../api/types.gen";
import { BlockError } from "../components/BlockError";
import { Icon } from "../components/icons";
import { PhotoViewer } from "../components/PhotoViewer";
import { Sheet } from "../components/Sheet";
import { CHAT_ACTIVITY_MS, useToast } from "../components/Toast";
import { notifyDataChanged } from "../lib/push";
import { loadConn } from "../lib/connection";
import { useConnection } from "../lib/ConnectionProvider";
import { copy } from "../lib/copy";
import { newClientMsgId } from "../lib/ids";
import { shrinkPhoto } from "../lib/shrinkPhoto";
import { formatKst } from "../lib/time";
import { screenHref } from "../ui/openScreen";
import type { OpenScreen } from "../ui/primitives/types";
import styles from "./ChatSheet.module.css";
import { chatActivityToast } from "./activityToast";
import { ConversationList } from "./ConversationList";
import { loadHistory, type Meta } from "./history";
import { saveParts } from "./localParts";
import { MessageView } from "./MessageView";
import { PhotoTray, type TrayPhoto, TRAY_MAX, trayPhoto } from "./PhotoTray";
import { conversationIdOf, toViewParts, type ViewPart } from "./parts";
import { QuickChips, WRITING_ID } from "./QuickChips";
import { type Chip, isWriteKey, quickChips, type WireChip } from "./quickChips";
import { sheetState } from "./sheetContext";
import { stopOnBe } from "./stop";
import { type ChatCtx, InFlightError, makeTransport } from "./transport";

const GAP_MS = 10 * 60_000;
// The front chip depends on the time (a check-in window, an event within 3 hours): looked at again each minute.
const CHIP_TICK_MS = 60_000;
// The stop button ignores a press this soon after a send or a retry: it is the send button's place.
export const STOP_GUARD_MS = 600;
const isObj = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null && !Array.isArray(v);

// --- retries ---

// A cut connection may have hidden an answer the BE did store: resend the same message once.
// An `error` chunk or a refused request (4xx/5xx) is an answer, and is not sent again. A 409 for a
// message still being answered is neither: "다시 받기" sends the same id later (not at once).
const isCut = (e: Error | null) => e instanceof TypeError || e?.name === "AbortError" || e?.name === "StreamCutError";
const isInFlight = (e: Error | null) => e instanceof InFlightError;

const metaOf = (m: UIMessage): Meta => (isObj(m.metadata) ? (m.metadata as Meta) : {});

// SP10 8장 응답→문구 (채팅 자리): the BE refused the message's photos before any answer. The
// transport's error message is the refusal's body (`{"error": {"code"}}`).
type Failure = "retry" | "notReceived" | "photo" | "photoLimit";
function photoRefusal(e: Error | null): Failure | null {
  if (!e) return null;
  let code: unknown;
  try {
    code = (JSON.parse(e.message) as { error?: { code?: unknown } } | null)?.error?.code;
  } catch {
    return null;
  }
  if (code === "photo_not_found") return "photo";
  if (code === "too_many_photos") return "photoLimit";
  return null;
}
const FAILURE_TEXT: Record<Failure, string> = {
  retry: copy.chat.notReceived,
  notReceived: copy.chat.notReceived,
  photo: copy.photos.uploadFailed,
  photoLimit: copy.photos.sendLimit,
};

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
  const [failure, setFailure] = useState<Failure | null>(null);
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
  const textRef = useRef(text);
  textRef.current = text;
  const writingRef = useRef(writing);
  writingRef.current = writing;

  // SP10 7.5: photos picked from the library wait here (at most 4) until send; the camera's photo
  // goes at once and lands here only when it could not be sent. `picking`: still being shrunk (they
  // count toward the 4). `pinned`: photos just uploaded, shown from their own bytes until the BE has
  // the message (it gives a photo out only once it is linked, 5.1). `lastSent`: the photos of the
  // message in flight, back to the tray should the BE refuse them.
  const [tray, setTrayState] = useState<TrayPhoto[]>([]);
  const trayRef = useRef(tray);
  const setTray = useCallback((next: (t: TrayPhoto[]) => TrayPhoto[]) => {
    trayRef.current = next(trayRef.current);
    setTrayState(trayRef.current);
  }, []);
  const picking = useRef(0);
  const [uploading, setUploading] = useState(false);
  const pinned = useRef(new Set<number>());
  const lastSent = useRef<TrayPhoto[]>([]);
  const [viewing, setViewing] = useState<{ ids: number[]; index: number } | null>(null);
  const pickerInput = useRef<HTMLInputElement>(null);
  const cameraInput = useRef<HTMLInputElement>(null);

  const sending = useRef(false);
  const autoRetried = useRef(false);
  const lastError = useRef<Error | null>(null);
  const regenerateRef = useRef<() => Promise<void>>(async () => {});
  // The stop button was pressed for the answer coming now: its abort is not a cut (no resend, no failure line).
  const stopping = useRef(false);
  // The client_msg_id actually sent (the user message's id, set before sendMessage), and when: a stop
  // right after a send must not name the previous message, and a double tap on send must not stop.
  const sentId = useRef<string | null>(null);
  const sentAt = useRef(-Infinity);
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

  // The message is answered (or refused, or given up on): its photos are the BE's to give out now.
  const unpinAll = useCallback((also: Set<number> = new Set()) => {
    const c = connRef.current ?? loadConn();
    if (c) for (const id of [...pinned.current, ...also]) dropLocalPhoto(c, id);
    pinned.current.clear();
    also.clear();
  }, []);
  // A refused message's photos are never linked, so the BE never gives them out: their own bytes stay
  // (its bubble can still show them big) until the sheet goes.
  const refusedPins = useRef(new Set<number>());
  // Room in the tray for photos coming back (a failed camera send, a refused message). The camera
  // keeps a place for its photo while it is sent (`reserved`), so one always fits.
  const backToTray = useCallback(
    (items: TrayPhoto[], reserved = 0) => {
      const room = TRAY_MAX - trayRef.current.length - (picking.current - reserved);
      const back = items.slice(0, Math.max(0, room)).map((p) => trayPhoto(p.image, p.thumb));
      if (back.length > 0) setTray((t) => [...t, ...back]);
    },
    [setTray],
  );
  const settle = useCallback(
    (f: Failure | null) => {
      sending.current = false;
      setInFlight(false);
      setFailure(f);
      if (f === "photo" || f === "photoLimit") {
        for (const id of pinned.current) refusedPins.current.add(id);
        pinned.current.clear();
        backToTray(lastSent.current);
      } else {
        unpinAll();
      }
      lastSent.current = [];
    },
    [unpinAll, backToTray],
  );

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
        // SP10 8장: the BE refused the photos (400 photo_not_found, 422 too_many_photos): they go back to the tray.
        const refused = isError ? photoRefusal(lastError.current) : null;
        if (refused) {
          lastError.current = null;
          settle(refused);
          return;
        }
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
    // Stopped before its start, the id is the app's own: no BE line will ever carry it, so nothing is kept.
    if (i !== -1) void saveParts(shown.id, toViewParts(shown), sentTo.current);
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
  // Read after the uploads (an await later): the render's own value may be old by then.
  const canSendRef = useRef(canSend);
  canSendRef.current = canSend;

  // `checkinId`: the message goes to that run (the check-in chip, SP9 9.5), without the picked conversation.
  // `chip`: the quick chip it came from (SP9c 4.1), kept in the message's metadata for its label.
  // `photoIds`: photos already uploaded (SP10 7.5), sent as data-photo parts after the text; with
  // photos the text may be empty.
  const send = (raw: string, { checkinId, chip, photoIds = [] }: { checkinId?: number; chip?: WireChip; photoIds?: number[] } = {}): boolean => {
    const t = raw.trim();
    if ((t === "" && photoIds.length === 0) || sending.current || !canSendRef.current) return false;
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
    const id = newClientMsgId();
    sentId.current = id;
    sentAt.current = performance.now();
    const parts: UIMessage["parts"] = [
      ...(t === "" ? [] : [{ type: "text" as const, text: t }]),
      ...photoIds.map((photo_id) => ({ type: "data-photo" as const, data: { photo_id } })),
    ];
    void sendMessage({ id, role: "user", parts, metadata });
    return true;
  };

  // SP10 7.5: each photo is uploaded (origin chat, a new client_msg_id each time), in the order
  // picked, then the message goes with the text written. One upload failing sends nothing. The
  // camera's photo (`fromCamera`) goes back to the tray then; the tray's stay where they are.
  const sendPhotos = async (items: TrayPhoto[], fromCamera: boolean) => {
    if (sending.current || !canSendRef.current) {
      if (fromCamera) backToTray(items, 1);
      return;
    }
    const raw = textRef.current;
    const chip = writingRef.current?.wire;
    sending.current = true; // a second press while the photos go up is ignored
    setUploading(true);
    const c = connRef.current ?? loadConn();
    const ids: number[] = [];
    let failed: ApiResult<unknown> | null = c ? null : { kind: "offline" };
    for (const p of items) {
      if (failed || !c) break;
      const up = await uploadPhoto(c, { image: p.image, thumb: p.thumb, origin: "chat", clientMsgId: newClientMsgId() });
      if (up.kind !== "ok") {
        failed = up;
        break;
      }
      // Shown in my bubble from these bytes: the BE gives it out once the message has it.
      keepLocalPhoto(c, up.data.id, p.image, p.thumb);
      ids.push(up.data.id);
    }
    sending.current = false;
    setUploading(false);
    if (failed || !c) {
      if (c) for (const id of ids) dropLocalPhoto(c, id);
      toastRef.current.show({ text: failed ? uploadFailureText(failed) : copy.photos.uploadFailed });
      if (fromCamera) backToTray(items, 1);
      return;
    }
    for (const id of ids) pinned.current.add(id);
    if (!send(raw, { chip, photoIds: ids })) {
      unpinAll();
      if (fromCamera) backToTray(items, 1);
      return;
    }
    lastSent.current = items;
    if (!fromCamera) {
      const sent = new Set(items.map((p) => p.key));
      for (const p of items) URL.revokeObjectURL(p.url);
      setTray((t) => t.filter((p) => !sent.has(p.key)));
    }
    setText((now) => (now === raw ? "" : now));
    setWriting(null);
  };

  // "사진": the library, many at once; what does not fit in the 4 is not taken.
  const pickPhotos = () => {
    if (trayRef.current.length + picking.current >= TRAY_MAX) {
      toastRef.current.show({ text: copy.photos.sendLimit });
      return;
    }
    pickerInput.current?.click();
  };
  const shrinkFile = async (file: File): Promise<TrayPhoto | null> => {
    try {
      const s = await shrinkPhoto(file);
      return trayPhoto(s.image, s.thumb);
    } catch {
      toastRef.current.show({ text: copy.photos.cannotOpen });
      return null;
    }
  };
  const onPicked = async (e: ChangeEvent<HTMLInputElement>) => {
    const files = [...(e.target.files ?? [])];
    e.target.value = "";
    if (files.length === 0) return;
    const room = Math.max(0, TRAY_MAX - trayRef.current.length - picking.current);
    if (files.length > room) toastRef.current.show({ text: copy.photos.sendLimit });
    const take = files.slice(0, room);
    picking.current += take.length;
    // One after another, so the tray (and the send) keeps the order they were picked in.
    for (const f of take) {
      const p = await shrinkFile(f);
      picking.current -= 1;
      if (p) setTray((t) => [...t, p]);
    }
  };
  const unpick = (key: string) => {
    const gone = trayRef.current.find((p) => p.key === key);
    if (gone) URL.revokeObjectURL(gone.url);
    setTray((t) => t.filter((p) => p.key !== key));
  };
  // "카메라": the phone's own camera; after "사진 사용" the photo goes at once (7.5). Off while a send
  // or an answer is going on, and with a full tray (a photo that fails must have a place to wait).
  const pressCamera = () => {
    if (trayRef.current.length + picking.current >= TRAY_MAX) {
      toastRef.current.show({ text: copy.photos.sendLimit });
      return;
    }
    cameraInput.current?.click();
  };
  const onCamera = async (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    // The tray filled while the camera was open: said so, nothing is lost unseen.
    if (trayRef.current.length + picking.current >= TRAY_MAX) {
      toastRef.current.show({ text: copy.photos.sendLimit });
      return;
    }
    picking.current += 1; // its place in the tray, kept until the send is over
    try {
      const p = await shrinkFile(file);
      if (!p) return;
      URL.revokeObjectURL(p.url); // not shown in the tray (should it come back there, it gets an address of its own)
      await sendPhotos([p], true);
    } finally {
      picking.current -= 1;
    }
  };
  // The tray's addresses go with the sheet, and so do the pins of photos still unanswered or refused.
  useEffect(
    () => () => {
      for (const p of trayRef.current) URL.revokeObjectURL(p.url);
      unpinAll(refusedPins.current);
    },
    [unpinAll],
  );
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
  // With photos waiting, they go up first and the text with them (SP10 7.5).
  const sendInput = () => {
    if (trayRef.current.length > 0) return void sendPhotos(trayRef.current, false);
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
    if (performance.now() - sentAt.current < STOP_GUARD_MS) return; // the second tap of a double tap on send
    stopping.current = true;
    if (sentId.current) void stopOnBe(sentId.current);
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
    sentId.current = [...messages].reverse().find((m) => m.role === "user")?.id ?? null; // regenerate sends it again
    sentAt.current = performance.now();
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
  const ready = canSend && !uploading && (text.trim() !== "" || tray.length > 0);
  // The × inside the field: empties it in one press (a one-line write stays open), the focus back in it.
  const clearable = text !== "" && !readOnly && !loading;
  const clearInput = () => {
    setText("");
    field.current?.focus();
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
    rows.push(
      <MessageView
        key={m.id}
        message={m}
        parts={parts}
        readOnly={readOnly || busy}
        onChoose={chooseLabel}
        onOpen={openScreen}
        onOpenPath={openPath}
        onOpenPhoto={(ids, index) => setViewing({ ids, index })}
      />,
    );
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
            <span>{FAILURE_TEXT[failure]}</span>
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
      {!embedded && <QuickChips chips={chips} disabled={!canSend || uploading} writing={writing} onPress={pressChip} onCloseWrite={closeWrite} />}
      {!embedded && <PhotoTray photos={tray} onRemove={unpick} disabled={uploading} />}
      <form className={styles.composer} onSubmit={onSubmit}>
        {!embedded && (
          // SP10 7.5: left of the field, in the chat sheet only. No camera screen of the app's own
          // (getUserMedia): the phone's camera opens through the file input.
          <div className={styles.attach}>
            <button
              type="button"
              className={`${styles.attachButton} pressable`}
              aria-label={copy.chat.camera}
              aria-disabled={tray.length >= TRAY_MAX ? true : undefined}
              disabled={readOnly || loading || busy || uploading}
              onClick={pressCamera}
            >
              <Icon name="camera" />
            </button>
            <button
              type="button"
              className={`${styles.attachButton} pressable`}
              aria-label={copy.photos.button}
              aria-disabled={tray.length >= TRAY_MAX ? true : undefined}
              disabled={readOnly || loading}
              onClick={pickPhotos}
            >
              <Icon name="photo" />
            </button>
            <input ref={cameraInput} type="file" accept="image/*" capture="environment" hidden tabIndex={-1} onChange={(e) => void onCamera(e)} />
            <input ref={pickerInput} type="file" accept="image/*" multiple hidden tabIndex={-1} onChange={(e) => void onPicked(e)} />
          </div>
        )}
        <div className={styles.field}>
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
          {clearable && (
            <button
              type="button"
              className={styles.clear}
              aria-label={copy.chat.clearInput}
              // The field keeps the focus, so a phone's keyboard stays up.
              onPointerDown={(e) => e.preventDefault()}
              onClick={clearInput}
            >
              <Icon name="clear" />
            </button>
          )}
        </div>
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
      <PhotoViewer
        photos={viewing?.ids.map((id) => ({ id })) ?? []}
        index={viewing?.index ?? null}
        onIndex={(index) => setViewing((v) => (v ? { ...v, index } : v))}
        onClose={() => setViewing(null)}
      />
    </div>
  );

  if (embedded) return content;
  return (
    <Sheet open={open} onClose={onClose} tall ariaLabel={copy.chat.title}>
      {content}
    </Sheet>
  );
}
