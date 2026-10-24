import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { failureText, undoActivity, type UndoBlockReason } from "../api/actions";
import { type ApiResult, apiGet } from "../api/client";
import type { ActivityItem, ActivityResponse, CheckinList } from "../api/types.gen";
import { BlockError } from "../components/BlockError";
import { Group } from "../components/Group";
import { LargeTitle } from "../components/LargeTitle";
import { Row } from "../components/Row";
import { Skeleton } from "../components/Skeleton";
import { StatusDot } from "../components/StatusDot";
import { useToast } from "../components/Toast";
import { useConnection } from "../lib/ConnectionProvider";
import { copy } from "../lib/copy";
import { usePolling } from "../lib/polling";
import { addDays, formatKst } from "../lib/time";
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
    const r: ApiResult<ActivityResponse> = await apiGet<ActivityResponse>(`/activity?since=${encodeURIComponent(since)}&limit=${SINCE_PAGE}`, "ActivityResponse");
    if (r.kind !== "ok") return r;
    r.data.items.forEach((a) => all.set(a.id, a));
    const next: string | null = r.data.items.length === 0 || r.data.next_since === since ? null : r.data.next_since;
    since = next;
  }
  return { kind: "ok", data: { items: [...all.values()].sort(newestFirst), nextBefore: null } };
}

async function loadFirst(): Promise<ApiResult<FirstPage>> {
  const r = await apiGet<ActivityResponse>(`/activity?order=desc&limit=${PAGE}`, "ActivityResponse");
  if (r.kind === "error" && r.status === 400 && r.code === "invalid_request") return loadBySince();
  if (r.kind !== "ok") return r;
  if (looksOldestFirst(r.data)) return loadBySince();
  return { kind: "ok", data: { items: [...r.data.items].sort(newestFirst), nextBefore: r.data.next_before } };
}

function mergeById(first: ActivityItem[], older: ActivityItem[]): ActivityItem[] {
  const seen = new Set(first.map((a) => a.id));
  return [...first, ...older.filter((a) => !seen.has(a.id))].sort(newestFirst);
}

// Spec 5.5.6, F8: what the secretary and I changed, newest first, with undo.
export function Activity() {
  const { state, recheck } = useConnection();
  const toast = useToast();
  const { result, refresh } = usePolling<FirstPage>(loadFirst);
  const checkins = usePolling<CheckinList>(() => apiGet<CheckinList>("/checkins", "CheckinList"));

  const [older, setOlder] = useState<ActivityItem[]>([]);
  // undefined: no older page read yet (the cursor is the first page's); null: no more.
  const [olderCursor, setOlderCursor] = useState<string | null | undefined>(undefined);
  const [loadingMore, setLoadingMore] = useState(false);
  const moreLock = useRef(false);

  const [notes, setNotes] = useState<Readonly<Record<number, UndoBlockReason>>>({});
  const [busy, setBusy] = useState<ReadonlySet<number>>(new Set());
  const undoing = useRef(new Set<number>());

  const readAgain = useCallback(() => {
    setOlder([]);
    setOlderCursor(undefined);
    setNotes({});
    return refresh();
  }, [refresh]);
  useEffect(() => toast.onUndone(() => void readAgain()), [toast, readAgain]);

  const live = result?.kind === "ok";
  const pendingKey = checkins.result?.kind === "ok" ? checkins.result.data.items.filter((c) => c.state === "pending").map((c) => c.id).join(",") : "";
  const { confirms, reread } = useConfirms(live ? pendingKey : "");
  const afterPartAction = useCallback(() => {
    void readAgain();
    void checkins.refresh();
    reread();
  }, [readAgain, checkins, reread]);

  const first = result?.kind === "ok" ? result.data : null;
  const items = useMemo(() => (first ? mergeById(first.items, older) : []), [first, older]);
  const cursor = olderCursor === undefined ? (first?.nextBefore ?? null) : olderCursor;

  const loadMore = async () => {
    if (moreLock.current || cursor === null) return;
    moreLock.current = true;
    setLoadingMore(true);
    try {
      const r = await apiGet<ActivityResponse>(`/activity?order=desc&limit=${PAGE}&before=${encodeURIComponent(cursor)}`, "ActivityResponse");
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

  const undo = async (id: number) => {
    if (undoing.current.has(id)) return; // the answer to the first press has not come yet
    undoing.current.add(id);
    setBusy(new Set(undoing.current));
    try {
      const out = await undoActivity(id);
      if (out.kind === "undone") {
        toast.show({ text: out.confirmation });
        await readAgain();
      } else if (out.kind === "already_undone") {
        await readAgain();
      } else if (out.kind === "blocked") {
        setNotes((n) => ({ ...n, [id]: out.reason }));
      } else {
        const k = out.result.kind;
        const known = k === "offline" || k === "unauthorized" || k === "rate_limited" || k === "safe_mode";
        toast.show({ text: known ? failureText(out.result) : copy.actions.undoFailed });
      }
    } finally {
      undoing.current.delete(id);
      setBusy(new Set(undoing.current));
    }
  };

  // Day groups by the Seoul calendar day of each line.
  const today = formatKst(new Date().toISOString(), "date");
  const yesterday = addDays(today, -1);
  const groups: { day: string; head: string; rows: ActivityItem[] }[] = [];
  for (const a of items) {
    const day = formatKst(a.at, "date");
    let g = groups[groups.length - 1];
    if (!g || g.day !== day) {
      g = { day, head: day === today ? copy.activity.today : day === yesterday ? copy.activity.yesterday : formatKst(a.at, copy.dateStyle.monthDay), rows: [] };
      groups.push(g);
    }
    g.rows.push(a);
  }

  const renderRow = (a: ActivityItem) => {
    const hhmm = formatKst(a.at, "HH:mm");
    const meta = copy.activity.meta(hhmm, copy.actors[a.actor], copy.channels[a.channel]);
    const note = notes[a.id];
    let trailing: React.ReactNode;
    if (a.undone_at !== null) trailing = <span className={styles.note}>{copy.activity.undoneAt(formatKst(a.undone_at, "HH:mm"))}</span>;
    else if (note) trailing = <span className={styles.note}>{copy.activity.undoBlocked[note]}</span>;
    else if (a.undo_id !== null) {
      const id = a.undo_id;
      trailing = (
        <button type="button" className={styles.undo} disabled={busy.has(id)} onClick={() => void undo(id)}>
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
  if (result === null) {
    body = (
      <Group>
        {[0, 1, 2].map((i) => (
          <Skeleton key={i} size="row" />
        ))}
      </Group>
    );
  } else if (result.kind === "offline") {
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
      <Group>
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
                <UiPart name="ui_confirm" props={c.props} ctx={{ where: "today", readOnly: false, onAfterAction: afterPartAction }} />
              </div>
            ))}
          </section>
        )}
        {groups.length === 0 ? (
          <p className={styles.line}>{copy.activity.empty}</p>
        ) : (
          groups.map((g) => (
            <Group key={g.day} heading={g.head}>
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
      <LargeTitle title={copy.activity.title} meta={copy.activity.intro} trailing={state ? <StatusDot state={state} /> : undefined} />
      {body}
    </main>
  );
}
