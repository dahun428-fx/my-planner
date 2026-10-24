import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { failureText, type UndoBlockReason, useUndo } from "../api/actions";
import { type ApiResult, apiFetch, apiGet } from "../api/client";
import type { ActivityItem, ActivityResponse, CheckinList, Today } from "../api/types.gen";
import { validateModel } from "../api/validate";
import { useChatSheet } from "../chat/sheetContext";
import { BlockError } from "../components/BlockError";
import { ChatLauncher, launcherReason } from "../components/ChatLauncher";
import { Group } from "../components/Group";
import { LargeTitle } from "../components/LargeTitle";
import { Row } from "../components/Row";
import { Skeleton } from "../components/Skeleton";
import { StatusDot } from "../components/StatusDot";
import { useToast } from "../components/Toast";
import { useConnection, useWritable } from "../lib/ConnectionProvider";
import { copy } from "../lib/copy";
import { usePolling } from "../lib/polling";
import { addDays, formatKst, logicalDateOf } from "../lib/time";
import page from "../styles/page.module.css";
import { UiPart } from "../ui/registry";
import styles from "./Activity.module.css";
import { useConfirms } from "./useConfirms";

const PAGE = 50;
const SINCE_PAGE = 200;
const SINCE_PAGES_MAX = 20; // 7 days at 200 a page; a guard against a BE that never ends the loop
const WEEK_MS = 7 * 24 * 60 * 60 * 1000;

interface FirstPage {
  items: ActivityItem[];
  nextBefore: string | null;
}

const newestFirst = (a: ActivityItem, b: ActivityItem) => (a.at === b.at ? b.id - a.id : a.at < b.at ? 1 : -1);
const isoSeconds = (ms: number) => new Date(ms).toISOString().replace(".000Z", "Z");

// The BE before R4a leaves `next_before` (and maybe `next_since`) out; read that as null instead of a shape error.
async function readPage(path: string): Promise<ApiResult<ActivityResponse>> {
  const r = await apiFetch<unknown>("GET", path);
  if (r.kind !== "ok") return r;
  const raw = r.data;
  if (typeof raw !== "object" || raw === null || Array.isArray(raw)) return { kind: "error", status: 200, code: "shape" };
  const body = { next_before: null, next_since: null, ...raw };
  return validateModel("ActivityResponse", body) ? { kind: "ok", data: body as ActivityResponse } : { kind: "error", status: 200, code: "shape" };
}

// Before R4a the BE has no order/before: it answers 400, or 200 with the oldest first and no next_before.
function looksOldestFirst(r: ActivityResponse): boolean {
  if (r.next_before !== null || r.items.length < 2) return false;
  return newestFirst(r.items[0], r.items[r.items.length - 1]) > 0;
}

// F8 fallback: the last 7 days by `since` pages until next_since runs out, then turned around.
async function loadBySince(): Promise<ApiResult<FirstPage>> {
  const all = new Map<number, ActivityItem>();
  let since: string | null = isoSeconds(Date.now() - WEEK_MS);
  for (let i = 0; i < SINCE_PAGES_MAX && since !== null; i++) {
    const r: ApiResult<ActivityResponse> = await readPage(`/activity?since=${encodeURIComponent(since)}&limit=${SINCE_PAGE}`);
    if (r.kind !== "ok") return r;
    r.data.items.forEach((a) => all.set(a.id, a));
    const next: string | null = r.data.items.length === 0 || r.data.next_since === since ? null : r.data.next_since;
    since = next;
  }
  return { kind: "ok", data: { items: [...all.values()].sort(newestFirst), nextBefore: null } };
}

async function loadFirst(): Promise<ApiResult<FirstPage>> {
  const r = await readPage(`/activity?order=desc&limit=${PAGE}`);
  if (r.kind === "error" && r.status === 400 && r.code === "invalid_request") return loadBySince();
  if (r.kind !== "ok") return r;
  if (looksOldestFirst(r.data)) return loadBySince();
  return { kind: "ok", data: { items: [...r.data.items].sort(newestFirst), nextBefore: r.data.next_before } };
}

/** A line undone in this session shows as undone at once (older pages are not read again). */
function applyUndone(items: ActivityItem[], undone: Readonly<Record<number, string>>): ActivityItem[] {
  return items.map((a) => (undone[a.id] !== undefined && a.undone_at === null ? { ...a, undone_at: undone[a.id], undo_id: null } : a));
}

function mergeById(first: ActivityItem[], older: ActivityItem[]): ActivityItem[] {
  const seen = new Set(first.map((a) => a.id));
  return [...first, ...older.filter((a) => !seen.has(a.id))].sort(newestFirst);
}

// Spec 5.5.6, F8: what the secretary and I changed, newest first, with undo.
export function Activity() {
  const { state, recheck } = useConnection();
  const canChat = useWritable(true, { strict: true });
  const toast = useToast();
  const { result, refresh } = usePolling<FirstPage>(loadFirst);
  const checkins = usePolling<CheckinList>(() => apiGet<CheckinList>("/checkins", "CheckinList"));
  const todayPoll = usePolling<Today>(() => apiGet<Today>("/today", "Today"));

  const [older, setOlder] = useState<ActivityItem[]>([]);
  // undefined: no older page read yet (the cursor is the first page's); null: no more.
  const [olderCursor, setOlderCursor] = useState<string | null | undefined>(undefined);
  const [loadingMore, setLoadingMore] = useState(false);
  const moreLock = useRef(false);

  const [notes, setNotes] = useState<Readonly<Record<number, UndoBlockReason>>>({});
  const [undone, setUndone] = useState<Readonly<Record<number, string>>>({});
  const { undo: send, busy } = useUndo();

  // Only the first page is read again; the older pages stay as they are.
  const readAgain = useCallback(() => refresh(), [refresh]);
  useEffect(() => toast.onUndone(() => void readAgain()), [toast, readAgain]);

  const offline = state?.kind === "offline" || result?.kind === "offline";
  const live = result?.kind === "ok" && !offline;
  const pendingKey = checkins.result?.kind === "ok" ? checkins.result.data.items.filter((c) => c.state === "pending").map((c) => c.id).join(",") : "";
  const { confirms, reread } = useConfirms(live ? pendingKey : "");
  const afterPartAction = useCallback(() => {
    void readAgain();
    void checkins.refresh();
    reread();
  }, [readAgain, checkins, reread]);
  const chat = useChatSheet();
  // The secretary may have written something while the sheet was open: read again when it closes.
  const afterRef = useRef(afterPartAction);
  afterRef.current = afterPartAction;
  useEffect(() => chat.onClosed(() => afterRef.current()), [chat]);

  const first = result?.kind === "ok" ? result.data : null;
  const items = useMemo(() => (first ? applyUndone(mergeById(first.items, older), undone) : []), [first, older, undone]);
  const cursor = olderCursor === undefined ? (first?.nextBefore ?? null) : olderCursor;

  const loadMore = async () => {
    if (moreLock.current || cursor === null) return;
    moreLock.current = true;
    setLoadingMore(true);
    try {
      const r = await readPage(`/activity?order=desc&limit=${PAGE}&before=${encodeURIComponent(cursor)}`);
      if (r.kind !== "ok") {
        toast.show({ text: failureText(r) });
        return;
      }
      setOlder((o) => mergeById(o, r.data.items));
      setOlderCursor(r.data.next_before);
    } finally {
      moreLock.current = false;
      setLoadingMore(false);
    }
  };

  const undo = async (rowId: number, undoId: number) => {
    const out = await send(undoId);
    if (out?.kind === "undone" || out?.kind === "already_undone") {
      setUndone((u) => ({ ...u, [rowId]: new Date().toISOString() }));
      await readAgain();
    } else if (out?.kind === "blocked") {
      setNotes((n) => ({ ...n, [rowId]: out.reason }));
    }
  };

  // Day groups by the BE's logical day (hours before 04:00 Seoul belong to the day before); "today" is /today.date.
  const boundary = todayPoll.result?.kind === "ok" ? todayPoll.result.data.day_boundary : undefined;
  const today = todayPoll.result?.kind === "ok" ? todayPoll.result.data.date : logicalDateOf(new Date().toISOString(), boundary);
  const yesterday = addDays(today, -1);
  const groups: { day: string; head: string; rows: ActivityItem[] }[] = [];
  for (const a of items) {
    const day = logicalDateOf(a.at, boundary);
    let g = groups[groups.length - 1];
    if (!g || g.day !== day) {
      g = { day, head: day === today ? copy.activity.today : day === yesterday ? copy.activity.yesterday : copy.dateParts.monthDay(Number(day.slice(5, 7)), Number(day.slice(8, 10))), rows: [] };
      groups.push(g);
    }
    g.rows.push(a);
  }

  const renderRow = (a: ActivityItem) => {
    const hhmm = formatKst(a.at, "HH:mm");
    const meta = copy.activity.meta(hhmm, copy.actors[a.actor], copy.channels[a.channel]);
    const note = notes[a.id];
    const undoId = a.undo_id;
    let trailing: React.ReactNode;
    if (a.undone_at !== null) trailing = <span className={styles.note}>{copy.activity.undoneAt(formatKst(a.undone_at, "HH:mm"))}</span>;
    else if (note) trailing = <span className={styles.note}>{copy.activity.undoBlocked[note]}</span>;
    else if (undoId !== null) {
      trailing = (
        <button type="button" className={styles.undo} disabled={busy.has(undoId)} onClick={() => void undo(a.id, undoId)}>
          {copy.activity.undo}
        </button>
      );
    }
    return (
      <Row
        key={a.id}
        leading={
          a.actor === "secretary" ? (
            <>
              <span className={styles.dot} aria-hidden="true" />
              <span className={styles.hidden}>{copy.activity.bySecretary}</span>
            </>
          ) : undefined
        }
        title={a.undone_at !== null ? <s className={styles.undone}>{a.summary}</s> : a.summary}
        meta={meta}
        trailing={trailing}
      />
    );
  };

  let body: React.ReactNode;
  if (offline) {
    body = (
      <section className={styles.notice} role="status">
        <p className={styles.noticeText}>
          <strong className={styles.lead}>{copy.offline.lead}</strong> {copy.offline.later}
        </p>
        <div className={styles.noticeActions}>
          <button type="button" className={styles.noticeAction} onClick={() => void recheck()}>
            {copy.offline.reconnect}
          </button>
          <Link href="/settings/" className={styles.noticeAction}>
            {copy.offline.check}
          </Link>
        </div>
      </section>
    );
  } else if (result === null) {
    body = (
      <Group paper>
        {[0, 1, 2].map((i) => (
          <Skeleton key={i} size="row" />
        ))}
      </Group>
    );
  } else if (result.kind === "unauthorized") {
    body = (
      <section className={styles.notice} role="status">
        <p className={styles.noticeText}>{copy.status.unauthorized}</p>
        <Link href="/settings/" className={styles.noticeAction}>
          {copy.errors.goSettings}
        </Link>
      </section>
    );
  } else if (result.kind === "rate_limited") {
    body = <p className={styles.line}>{copy.status.tooMany}</p>;
  } else if (result.kind === "safe_mode") {
    body = <p className={styles.line}>{copy.status.safeMode}</p>;
  } else if (result.kind === "error") {
    body = (
      <Group paper>
        <BlockError code={result.code} onRetry={() => void refresh()} />
      </Group>
    );
  } else {
    body = (
      <>
        {confirms.length > 0 && (
          <section className={styles.block}>
            <h2 className={styles.blockHeading}>{copy.activity.needsConfirm}</h2>
            {confirms.map((c) => (
              <div key={c.key} className={styles.blockItem}>
                <UiPart name="ui_confirm" props={c.props} ctx={{ where: "activity", readOnly: false, onAfterAction: afterPartAction }} />
              </div>
            ))}
          </section>
        )}
        {groups.length === 0 ? (
          <p className={styles.line}>{copy.activity.empty}</p>
        ) : (
          groups.map((g) => (
            <Group paper key={g.day} heading={g.head}>
              {g.rows.map(renderRow)}
            </Group>
          ))
        )}
        {cursor !== null && (
          <div className={styles.moreWrap}>
            <button type="button" className={styles.more} disabled={loadingMore} onClick={() => void loadMore()}>
              {copy.activity.more}
            </button>
          </div>
        )}
      </>
    );
  }

  return (
    <main className={`${page.main} ${styles.main}`}>
      <LargeTitle title={copy.activity.title} sub={copy.activity.intro} trailing={state ? <StatusDot state={state} /> : undefined} />
      {body}
      <ChatLauncher disabled={!canChat} offline={state?.kind === "offline"} reason={launcherReason(state?.kind)} onOpen={chat.open} />
    </main>
  );
}
