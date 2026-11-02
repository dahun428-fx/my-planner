import Link from "next/link";
import { useRouter } from "next/router";
import { Component as ReactComponent, type ComponentType, type ReactNode, useCallback, useEffect, useRef, useState } from "react";
import { useAction } from "../api/actions";
import { apiGet } from "../api/client";
import type { CheckinDetail, Today } from "../api/types.gen";
import type { ChatSheetProps } from "../chat/ChatSheet";
import { chatSheetChunk } from "../chat/loadChatSheet";
import { BlockError } from "../components/BlockError";
import { Group } from "../components/Group";
import { LargeTitle } from "../components/LargeTitle";
import { AgentNoteLines } from "../components/AgentNoteLines";
import { Markdown } from "../components/Markdown";
import { OfflineNotice } from "../components/OfflineNotice";
import { Skeleton } from "../components/Skeleton";
import { useConnection } from "../lib/ConnectionProvider";
import { splitAgentNotes } from "../lib/agentNotes";
import { copy } from "../lib/copy";
import { usePolling } from "../lib/polling";
import { addDays, formatKst } from "../lib/time";
import page from "../styles/page.module.css";
import { UiPart } from "../ui/registry";
import type { PartData } from "../ui/types";
import styles from "./Checkin.module.css";
import { useConfirmedAction, useNotAllowed } from "./todoActions";

const POLL_MS = 15_000;
const MAX_TIMER_MS = 2 ** 31 - 1;

type Shown = "pending" | "answered" | "missed";

// A crash inside the reply box takes down only the box (same rule as the chat sheet in _app).
class ReplyBoundary extends ReactComponent<{ onError(): void; children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  componentDidCatch() {
    this.props.onError();
  }
  render() {
    return this.state.failed ? null : this.props.children;
  }
}

// The reply box is the chat sheet drawn inside the screen. Its chunk (the AI SDK with it) loads
// when the box is first needed; a failure says so with a retry, never a blank screen.
function Reply({ checkinId, conversationId, onSent }: { checkinId: number; conversationId: number | null; onSent(): void }) {
  const [Sheet, setSheet] = useState<ComponentType<ChatSheetProps> | null>(null);
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let alive = true;
    setFailed(false);
    chatSheetChunk
      .load()
      .then((m) => {
        if (alive) setSheet(() => m.ChatSheet);
      })
      .catch(() => {
        if (alive) setFailed(true);
      });
    return () => {
      alive = false;
    };
  }, [attempt]);

  const fail = useCallback(() => {
    setSheet(null);
    setFailed(true);
  }, []);

  if (failed) {
    return (
      <div className={styles.reply}>
        <p className={styles.replyFailed} role="status">
          <span>{copy.checkin.replyFailed}</span>
          <span aria-hidden="true"> · </span>
          <button type="button" className={styles.retry} onClick={() => setAttempt((n) => n + 1)}>
            {copy.errors.retry}
          </button>
        </p>
      </div>
    );
  }
  if (!Sheet) {
    return (
      <div className={styles.reply}>
        <Skeleton size="row" />
      </div>
    );
  }
  return (
    <div className={styles.reply}>
      <ReplyBoundary onError={fail}>
        <Sheet open onClose={() => {}} embedded checkinId={checkinId} conversationId={conversationId} onSent={onSent} />
      </ReplyBoundary>
    </div>
  );
}

// Spec 5.5.3: the open to-dos of the day, only on an evening check-in.
function Remaining({ readOnly: parentReadOnly, reloadToken }: { readOnly: boolean; reloadToken: number }) {
  const { result, refresh } = usePolling<Today>(() => apiGet<Today>("/today", "Today"));
  const { run } = useAction();
  const readOnly = parentReadOnly || result?.kind === "offline";
  const notAllowed = useNotAllowed(refresh);
  // "내일로" on a to-do that has a time asks first (SP6 8, BE-2).
  const { run: confirmed, sheet: confirmSheet } = useConfirmedAction(refresh);
  const [acting, setActing] = useState<ReadonlySet<number>>(new Set());
  const busy = useRef(new Set<number>());

  const first = useRef(true);
  useEffect(() => {
    if (first.current) {
      first.current = false;
      return;
    }
    void refresh();
  }, [reloadToken, refresh]);

  // The last good answer stays, disabled, when the connection drops (F9).
  const [lastToday, setLastToday] = useState<Today | null>(null);
  useEffect(() => {
    if (result?.kind === "ok") setLastToday(result.data);
  }, [result]);
  const shownToday = result?.kind === "ok" ? result.data : lastToday;
  const date = shownToday?.date ?? "";

  const act = async (id: number, action: "move_task" | "complete_task") => {
    if (busy.current.has(id)) return; // the answer to the first press has not come yet
    busy.current.add(id);
    setActing(new Set(busy.current));
    try {
      if (action === "move_task") {
        // The BE's logical day, not the device calendar (it differs between 00:00 and 04:00).
        await confirmed("move_task", { id, planned_for: addDays(date, 1) });
        return;
      }
      const out = await run(action, { id });
      if (out === null) return;
      if (out.kind === "applied") await refresh();
      else await notAllowed(out);
    } finally {
      busy.current.delete(id);
      setActing(new Set(busy.current));
    }
  };

  let body: ReactNode;
  if (result === null) {
    body = <Skeleton size="row" />;
  } else if (shownToday !== null) {
    const todos = shownToday.todos.map((t) => t.todo).filter((t) => t.status === "open" || t.status === "done");
    const list = [...todos.filter((t) => t.status === "open"), ...todos.filter((t) => t.status === "done")];
    body =
      list.length === 0 ? (
        <p className={styles.empty}>{copy.checkin.noTodos}</p>
      ) : (
        <ul className={styles.todos}>
          {list.map((t) =>
            t.status === "done" ? (
              <li key={t.id} className={styles.todo}>
                <span className={`${styles.todoTitle} ${styles.finished}`}>{t.title}</span>
                <span className={styles.finishedNote}>{copy.checkin.done}</span>
              </li>
            ) : (
              <li key={t.id} className={styles.todo}>
                <span className={styles.todoTitle}>{t.title}</span>
                <button
                  type="button"
                  className={styles.act}
                  aria-label={copy.checkin.tomorrowLabel(t.title)}
                  disabled={readOnly || acting.has(t.id)}
                  onClick={() => void act(t.id, "move_task")}
                >
                  {copy.todos.tomorrow}
                </button>
                <button
                  type="button"
                  className={styles.act}
                  aria-label={copy.checkin.completeLabel(t.title)}
                  disabled={readOnly || acting.has(t.id)}
                  onClick={() => void act(t.id, "complete_task")}
                >
                  {copy.checkin.complete}
                </button>
              </li>
            ),
          )}
        </ul>
      );
  } else if (result.kind === "offline") {
    body = <p className={styles.empty}>{copy.offline.later}</p>;
  } else {
    body = <BlockError code={result.kind === "error" ? result.code : result.kind} onRetry={() => void refresh()} />;
  }
  return (
    <Group heading={copy.checkin.todosHeading}>
      {body}
      {confirmSheet}
    </Group>
  );
}

function deliveredLine(c: CheckinDetail): string | null {
  const app = c.delivered_via.includes("app");
  const tg = c.delivered_via.includes("telegram");
  const via = app && tg ? copy.checkin.receivedBoth : app ? copy.checkin.receivedApp : tg ? copy.checkin.receivedTelegram : null;
  if (c.sent_at === null) return null;
  const at = copy.checkin.sentAt(formatKst(c.sent_at, "HH:mm"));
  return via === null ? at : `${at} · ${via}`;
}

function CheckinBody({ id }: { id: number }) {
  const { state, recheck } = useConnection();
  const { result, refresh } = usePolling<CheckinDetail>(() => apiGet<CheckinDetail>(`/checkins/${id}`, "CheckinDetail"), POLL_MS);

  // The last good answer stays on screen when a later read fails or the connection drops.
  const [last, setLast] = useState<{ data: CheckinDetail; at: string } | null>(null);
  useEffect(() => {
    if (result?.kind === "ok") setLast({ data: result.data, at: new Date().toISOString() });
  }, [result]);
  const data = result?.kind === "ok" ? result.data : last?.data ?? null;

  // The reply box keeps the conversation it first opened with, so a read that shows the one the
  // BE forked while talking does not reload it under the person's hands.
  const [conv, setConv] = useState<{ id: number | null } | null>(null);
  useEffect(() => {
    if (conv === null && data) setConv({ id: data.conversation_ids.app });
  }, [conv, data]);

  // `reply_until` is used only to show "지나감" once the window has ended. The word is worked out
  // at render time, so a new read changes nothing by itself; the timer only forces that render.
  const [, tick] = useState(0);
  useEffect(() => {
    if (!data || data.state !== "pending") return;
    const wait = Date.parse(data.reply_until) - Date.now();
    if (wait <= 0 || wait >= MAX_TIMER_MS) return;
    const timer = setTimeout(() => tick((n) => n + 1), wait + 1);
    return () => clearTimeout(timer);
  }, [data]);
  const lapsed = data !== null && data.state === "pending" && Date.now() > Date.parse(data.reply_until);

  const [reload, setReload] = useState(0);
  const afterPartAction = useCallback(() => {
    void refresh();
    setReload((n) => n + 1);
  }, [refresh]);

  const offline = state?.kind === "offline" || result?.kind === "offline";
  const readOnly = offline;
  const shown: Shown | null = data ? (data.state === "pending" && lapsed ? "missed" : data.state) : null;
  const status =
    data && shown
      ? shown === "pending"
        ? copy.checkin.canReply
        : shown === "answered"
          ? data.answered_via
            ? copy.checkin.answeredVia(copy.channels[data.answered_via])
            : copy.checkin.answered
          : copy.checkin.passed
      : null;

  let body: ReactNode = null;
  if (data) {
    const cards = data.cards;
    // SP14 10장: the observation lines under the Markdown, only in the morning brief (the one place they come).
    const parts = data.loop === "morning_brief" ? splitAgentNotes(data.text) : { body: data.text, notes: [] };
    body = (
      <>
        <Group>
          {parts.body !== "" && <Markdown text={parts.body} className={styles.text} />}
          {parts.notes.length > 0 && (
            <div className={styles.notes}>
              <AgentNoteLines notes={parts.notes} />
            </div>
          )}
        </Group>
        {cards.map((card) => (
          <section key={card.toolCallId} className={styles.card}>
            <UiPart name={card.component} props={card.props} data={(card.data ?? undefined) as PartData | undefined} ctx={{ where: "checkin", readOnly, onAfterAction: afterPartAction }} />
          </section>
        ))}
        {data.loop === "evening_checkin" && <Remaining readOnly={readOnly} reloadToken={reload} />}
        {conv !== null && <Reply checkinId={id} conversationId={conv.id} onSent={afterPartAction} />}
      </>
    );
  } else if (result === null && !offline) {
    body = (
      <Group>
        <Skeleton size="row" />
        <Skeleton size="row" />
      </Group>
    );
  } else if (result !== null && !offline) {
    if (result.kind === "unauthorized") {
      body = (
        <section className={styles.notice} role="status">
          <p>{copy.status.unauthorized}</p>
          <Link href="/settings/" className={styles.noticeLink}>
            {copy.errors.goSettings}
          </Link>
        </section>
      );
    } else if (result.kind === "rate_limited") {
      body = <p className={styles.line}>{copy.status.tooMany}</p>;
    } else if (result.kind === "safe_mode") {
      body = <p className={styles.line}>{copy.status.safeMode}</p>;
    } else {
      body = (
        <Group>
          <BlockError code={result.kind === "error" ? result.code : result.kind} onRetry={() => void refresh()} />
        </Group>
      );
    }
  }

  return (
    <main className={`${page.main} ${styles.main}`}>
      <nav className={styles.bar}>
        <Link href="/" className={styles.back}>
          {copy.checkin.back}
        </Link>
        {status !== null && <span className={styles.status} role="status">{status}</span>}
      </nav>
      <LargeTitle title={data ? copy.loops[data.loop] : copy.checkin.title} sub={data ? deliveredLine(data) ?? undefined : undefined} />
      {offline && <OfflineNotice savedAt={last?.at ?? null} onRetry={() => void recheck()} />}
      {body}
    </main>
  );
}

// Spec 5.5.3, F5. A `?id=` that is not a number goes back to Today.
export function Checkin({ id }: { id: number }) {
  const router = useRouter();
  const ok = Number.isInteger(id) && id > 0;
  useEffect(() => {
    if (!ok) void router.replace("/");
  }, [ok, router]);
  if (!ok) return null;
  return <CheckinBody key={id} id={id} />;
}
