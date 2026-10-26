import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { type ActionName, failureText, useAction } from "../api/actions";
import { type ApiResult, apiGet } from "../api/client";
import type { MemoItem, MemoList } from "../api/types.gen";
import { useChatSheet } from "../chat/sheetContext";
import { BlockError } from "../components/BlockError";
import { ChatLauncher, launcherReason } from "../components/ChatLauncher";
import { Group } from "../components/Group";
import { Icon } from "../components/icons";
import { LargeTitle } from "../components/LargeTitle";
import { MoreButton } from "../components/MoreButton";
import { OfflineNotice } from "../components/OfflineNotice";
import { PhotoImage } from "../components/PhotoImage";
import photoStyles from "../components/PhotoStrip.module.css";
import { Skeleton } from "../components/Skeleton";
import { StatusDot } from "../components/StatusDot";
import { SwipeRow } from "../components/SwipeRow";
import { useToast } from "../components/Toast";
import { onTodayRefresh } from "../lib/push";
import { useConnection, useWritable } from "../lib/ConnectionProvider";
import { copy } from "../lib/copy";
import { memoDay } from "../lib/memoText";
import { usePolling } from "../lib/polling";
import page from "../styles/page.module.css";
import styles from "./Memos.module.css";

const SEARCH_WAIT_MS = 300;

const listPath = (q: string, before?: string) => {
  const p = new URLSearchParams();
  if (q) p.set("q", q);
  if (before) p.set("before", before);
  const s = p.toString();
  return s ? `/memos?${s}` : "/memos";
};

const mergeById = (a: MemoItem[], b: MemoItem[]) => {
  const seen = new Set(a.map((m) => m.id));
  return [...a, ...b.filter((m) => !seen.has(m.id))];
};

/** The view/write screen of one memo (`/memos/view/?id=`). */
export const memoHref = (id: number) => `/memos/view/?id=${id}`;

// SP9 9.4: large title "메모" with "+" and more at the right, a search box (300ms after the typing
// stops), the pinned group ("고정됨") first, then the rest ("메모"). A row swiped left offers pin or
// unpin and delete; both toast with undo. Offline the last list stays, read-only.
export function Memos() {
  const { state, recheck } = useConnection();
  const toast = useToast();
  const { run } = useAction();
  const [typed, setTyped] = useState("");
  const [query, setQuery] = useState("");
  const queryRef = useRef(query);
  queryRef.current = query;
  const { result, refresh } = usePolling<MemoList>(() => apiGet<MemoList>(listPath(queryRef.current), "MemoList"));

  // Older pages (next_before). A new search or a write drops them; a poll keeps them (merged by id).
  const [older, setOlder] = useState<{ items: MemoItem[]; next: string | null } | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const moreLock = useRef(false);
  const [last, setLast] = useState<{ data: MemoList; at: string; q: string } | null>(null);
  useEffect(() => {
    if (result?.kind !== "ok") return;
    setLast({ data: result.data, at: new Date().toISOString(), q: queryRef.current });
  }, [result]);

  useEffect(() => {
    const t = setTimeout(() => setQuery(typed.trim()), SEARCH_WAIT_MS);
    return () => clearTimeout(t);
  }, [typed]);
  const firstQuery = useRef(true);
  useEffect(() => {
    if (firstQuery.current) {
      firstQuery.current = false; // the first page is usePolling's own first read
      return;
    }
    setOlder(null);
    void refresh();
  }, [query, refresh]);

  useEffect(() => toast.onUndone(() => void refresh()), [toast, refresh]);
  const chat = useChatSheet();
  // The secretary may have made a memo while the sheet was open (create_memo, 6.3).
  useEffect(() => chat.onClosed(() => void refresh()), [chat, refresh]);
  useEffect(() => onTodayRefresh(() => void refresh()), [refresh]);

  const offline = state?.kind === "offline" || result?.kind === "offline";
  const data = result?.kind === "ok" ? result.data : (last?.data ?? null);
  const live = result?.kind === "ok" && !offline;
  const writable = useWritable(live);
  const canAdd = useWritable(!offline);
  const canChat = useWritable(!offline, { strict: true });

  const items = data ? mergeById(data.items, older?.items ?? []) : [];
  const cursor = older ? older.next : (data?.next_before ?? null);

  const loadMore = async () => {
    if (moreLock.current || cursor === null) return;
    moreLock.current = true;
    setLoadingMore(true);
    try {
      const r: ApiResult<MemoList> = await apiGet<MemoList>(listPath(queryRef.current, cursor), "MemoList");
      if (r.kind !== "ok") {
        toast.show({ text: failureText(r) });
        return;
      }
      setOlder((o) => ({ items: mergeById(o?.items ?? [], r.data.items), next: r.data.next_before }));
    } finally {
      moreLock.current = false;
      setLoadingMore(false);
    }
  };

  const act = async (action: ActionName, id: number) => {
    const out = await run(action, { id });
    // Applied: the list changes (pinned group, gone). Anything else: read again, the row may be stale.
    if (!out) return;
    setOlder(null);
    await refresh();
  };

  const row = (m: MemoItem) => (
    <SwipeRow
      key={m.id}
      disabled={!writable}
      menuTitle={m.title}
      moreLabel={copy.today.moreActions(m.title)}
      actions={[
        m.pinned
          ? { label: copy.memos.unpin, tone: "neutral", onPress: () => void act("unpin_memo", m.id) }
          : { label: copy.memos.pin, tone: "neutral", onPress: () => void act("pin_memo", m.id) },
        { label: copy.memos.delete, tone: "negative", onPress: () => void act("delete_memo", m.id) },
      ]}
    >
      <Link href={memoHref(m.id)} className={styles.row}>
        <span className={styles.text}>
          <span className={styles.titleLine}>
            <span className={styles.title}>{m.title}</span>
            {m.origin === "chat" && <span className={styles.secretary}>{copy.memos.bySecretary}</span>}
          </span>
          <span className={styles.meta}>
            <span className="tnum">{memoDay(m.updated_at)}</span>
            {m.preview && <span className={styles.preview}>{m.preview}</span>}
          </span>
        </span>
        {m.area && (
          <span className="area-dot" data-area={m.area}>
            <span className="visually-hidden">{copy.areas[m.area]}</span>
          </span>
        )}
        {/* SP10 7.1: a memo with photos shows its first one small (40px) at the row's right. */}
        {m.photos?.[0] && <PhotoImage id={m.photos[0].id} size="thumb" className={photoStyles.listThumb} />}
      </Link>
    </SwipeRow>
  );

  let body: React.ReactNode;
  if (data) {
    const pinned = items.filter((m) => m.pinned);
    const rest = items.filter((m) => !m.pinned);
    const q = result?.kind === "ok" ? queryRef.current : (last?.q ?? "");
    if (items.length === 0) {
      body = <p className={styles.line}>{q ? copy.memos.noMatch : copy.memos.empty}</p>;
    } else {
      body = (
        <div className={styles.lists}>
          {pinned.length > 0 && (
            <Group paper heading={copy.memos.pinnedHeading}>
              {pinned.map(row)}
            </Group>
          )}
          {rest.length > 0 && (
            <Group paper heading={pinned.length > 0 ? copy.memos.listHeading : undefined}>
              {rest.map(row)}
            </Group>
          )}
          {cursor !== null && !offline && (
            <div className={styles.moreWrap}>
              <button type="button" className={styles.more} disabled={loadingMore} onClick={() => void loadMore()}>
                {copy.memos.more}
              </button>
            </div>
          )}
        </div>
      );
    }
  } else if (result === null || result.kind === "offline") {
    body = offline ? null : (
      <Group paper>
        {[0, 1, 2].map((i) => (
          <Skeleton key={i} size="row" />
        ))}
      </Group>
    );
  } else {
    body = (
      <Group paper>
        <BlockError code={result.kind === "error" ? result.code : result.kind} onRetry={() => void refresh()} />
      </Group>
    );
  }

  return (
    <main className={`${page.main} ${styles.main}`}>
      <LargeTitle
        title={copy.memos.title}
        trailing={
          <span className={styles.trailing}>
            {state && <StatusDot state={state} />}
            {canAdd ? (
              <Link href="/memos/view/?new=1" className={`${styles.add} pressable`} aria-label={copy.memos.add}>
                <Icon name="plus" />
              </Link>
            ) : (
              <button type="button" className={styles.add} aria-label={copy.memos.add} disabled>
                <Icon name="plus" />
              </button>
            )}
            <MoreButton />
          </span>
        }
      />
      <div className={styles.searchWrap}>
        <input
          type="search"
          className={styles.search}
          aria-label={copy.memos.search}
          placeholder={copy.memos.search}
          value={typed}
          onChange={(e) => setTyped(e.target.value)}
          enterKeyHint="search"
        />
      </div>
      {offline && <OfflineNotice savedAt={last?.at ?? null} onRetry={() => void recheck()} />}
      {body}
      <ChatLauncher disabled={!canChat} offline={state?.kind === "offline"} reason={launcherReason(state?.kind)} onOpen={chat.open} />
    </main>
  );
}
