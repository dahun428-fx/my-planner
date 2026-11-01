import { useCallback, useEffect, useRef, useState } from "react";
import { failureText } from "../api/actions";
import { type ApiResult, apiFetch, apiGet } from "../api/client";
import type { ConversationItem, Conversations } from "../api/types.gen";
import { BlockError } from "../components/BlockError";
import { ConfirmSheet } from "../components/ConfirmSheet";
import { Group } from "../components/Group";
import { Icon } from "../components/icons";
import { Skeleton } from "../components/Skeleton";
import { SwipeRow } from "../components/SwipeRow";
import { useToast } from "../components/Toast";
import { copy } from "../lib/copy";
import { addDays, formatKst } from "../lib/time";
import type { Agent } from "./agent";
import styles from "./ConversationList.module.css";

const SEARCH_WAIT_MS = 300;
const PAGE = 30;

const listPath = (agent: Agent, q: string, before?: string) => {
  const p = new URLSearchParams({ channel: "app", limit: String(PAGE) });
  if (agent === "mate") p.set("agent", agent); // SP12: the secretary's request stays as it was
  if (q) p.set("q", q);
  if (before) p.set("before", before);
  return `/conversations?${p.toString()}`;
};

const mergeById = (a: ConversationItem[], b: ConversationItem[]) => {
  const seen = new Set(a.map((c) => c.id));
  return [...a, ...b.filter((c) => !seen.has(c.id))];
};

export interface ConversationGroup {
  label: string;
  /** 오늘·어제 줄은 시각, 그 앞은 날짜를 보인다. */
  recent: boolean;
  items: ConversationItem[];
}

/**
 * 날짜 묶음(9.5): "오늘", "어제", "이번 주"(월요일부터), 그 앞은 달("10월", 다른 해면 "2025년 10월").
 * 날짜는 마지막 말의 서울 달력 날짜다(메모 목록의 날짜와 같은 규칙, 논리적 날짜 아님). 순서는 BE가 준 그대로(최근 먼저).
 */
export function groupConversations(items: ConversationItem[], now: number): ConversationGroup[] {
  const today = formatKst(new Date(now).toISOString(), "date");
  const yesterday = addDays(today, -1);
  const [ty, tm, td] = today.split("-").map(Number);
  const monday = addDays(today, -((new Date(Date.UTC(ty, tm - 1, td)).getUTCDay() + 6) % 7));
  const out: ConversationGroup[] = [];
  for (const c of items) {
    const day = formatKst(c.last_message_at, "date");
    const [y, m] = day.split("-").map(Number);
    let label: string;
    if (day === today) label = copy.chat.groups.today;
    else if (day === yesterday) label = copy.chat.groups.yesterday;
    else if (day >= monday && day < today) label = copy.chat.groups.thisWeek;
    else label = y === ty ? copy.chat.groups.month(m) : copy.chat.groups.monthOfYear(y, m);
    const last = out[out.length - 1];
    if (last?.label === label) last.items.push(c);
    else out.push({ label, recent: day === today || day === yesterday, items: [c] });
  }
  return out;
}

const firstLine = (s: string | null | undefined) => (s ?? "").split("\n")[0].trim();
const titleOf = (c: ConversationItem) => c.title?.trim() || copy.chat.untitled;

export interface ConversationListProps {
  /** 오프라인·답 오는 중: 목록만 보인다(열기, 새 대화, 지우기 없음. 답이 오는 동안 다른 대화로 바꾸지 않는다). */
  readOnly: boolean;
  /** SP12 11.1: whose conversations (the list is per partner). Left out: the secretary. */
  agent?: Agent;
  onOpen(id: number): void;
  onNew(): void;
  /** 지운 뒤(화면의 대화였으면 시트가 비운다). */
  onDeleted(id: number): void;
  /** 날짜 묶음의 "지금"(시험용). */
  now?: number;
}

// SP9 9.5 대화 목록: 맨 위 "새 대화", 검색창(입력이 멈추고 300ms 뒤 `q`), 날짜 묶음, 줄 = 제목 + 요약 앞 한 줄 +
// 시각. 체크인 대화는 제목 앞에 "체크인". 줄을 밀면 "지우기"(확인 시트, 되돌릴 수 없음). 카드 없이 이어지는 종이 목록.
export function ConversationList({ readOnly, agent = "secretary", onOpen, onNew, onDeleted, now }: ConversationListProps) {
  const toast = useToast();
  const [typed, setTyped] = useState("");
  const [query, setQuery] = useState<string | null>(null);
  const [result, setResult] = useState<ApiResult<Conversations> | null>(null);
  const [older, setOlder] = useState<{ items: ConversationItem[]; next: string | null } | null>(null);
  const [gone, setGone] = useState<ReadonlySet<number>>(new Set());
  const [loadingMore, setLoadingMore] = useState(false);
  const [asking, setAsking] = useState<ConversationItem | null>(null);
  const [deleting, setDeleting] = useState(false);
  const seq = useRef(0);

  const load = useCallback((q: string) => {
    const mine = ++seq.current;
    setOlder(null);
    void apiGet<Conversations>(listPath(agent, q), "Conversations").then((r) => {
      if (mine === seq.current) setResult(r);
    });
  }, [agent]);

  // 첫 읽기는 바로, 검색어는 입력이 멈추고 300ms 뒤.
  useEffect(() => {
    if (query === null) {
      setQuery("");
      load("");
      return;
    }
    const t = setTimeout(() => {
      const q = typed.trim();
      if (q !== query) {
        setQuery(q);
        load(q);
      }
    }, SEARCH_WAIT_MS);
    return () => clearTimeout(t);
  }, [typed, query, load]);

  const data = result?.kind === "ok" ? result.data : null;
  const items = data ? mergeById(data.items, older?.items ?? []).filter((c) => !gone.has(c.id)) : [];
  const cursor = older ? older.next : (data?.next_before ?? null);

  const loadMore = async () => {
    if (loadingMore || cursor === null) return;
    setLoadingMore(true);
    const mine = seq.current;
    try {
      const r = await apiGet<Conversations>(listPath(agent, query ?? "", cursor), "Conversations");
      if (mine !== seq.current) return;
      if (r.kind !== "ok") {
        toast.show({ text: failureText(r) });
        return;
      }
      setOlder((o) => ({ items: mergeById(o?.items ?? [], r.data.items), next: r.data.next_before ?? null }));
    } finally {
      setLoadingMore(false);
    }
  };

  // 7.7: 되돌릴 수 없어서 확인 시트를 거친다. 지운 줄은 바로 빠진다.
  const remove = async (c: ConversationItem) => {
    if (deleting) return;
    setDeleting(true);
    const r = await apiFetch<null>("DELETE", `/conversations/${c.id}`);
    setDeleting(false);
    setAsking(null);
    if (r.kind === "ok" || (r.kind === "error" && r.status === 404)) {
      setGone((g) => new Set(g).add(c.id));
      onDeleted(c.id);
      return;
    }
    toast.show({ text: failureText(r) });
  };

  const at = now ?? Date.now();
  const row = (c: ConversationItem, recent: boolean) => {
    const title = titleOf(c);
    const summary = firstLine(c.summary);
    return (
      <SwipeRow
        key={c.id}
        disabled={readOnly}
        menuTitle={title}
        moreLabel={copy.today.moreActions(title)}
        actions={[{ label: copy.chat.delete, tone: "negative", onPress: () => setAsking(c) }]}
      >
        <button type="button" className={styles.row} disabled={readOnly} onClick={() => onOpen(c.id)}>
          <span className={styles.text}>
            <span className={styles.titleLine}>
              {c.kind === "run" && <span className={styles.tag}>{copy.chat.checkinTag}</span>}
              <span className={styles.title}>{title}</span>
            </span>
            <span className={styles.meta}>
              <span className="tnum">{recent ? formatKst(c.last_message_at, "HH:mm") : formatKst(c.last_message_at, copy.dateStyle.monthDay)}</span>
              {summary && <span className={styles.summary}>{summary}</span>}
            </span>
          </span>
        </button>
      </SwipeRow>
    );
  };

  let body: React.ReactNode;
  if (data) {
    if (items.length === 0) {
      body = <p className={styles.line}>{query ? copy.chat.noMatch : copy.chat.noConversations}</p>;
    } else {
      body = (
        <div className={styles.groups}>
          {groupConversations(items, at).map((g) => (
            <Group paper key={g.label} heading={g.label}>
              {g.items.map((c) => row(c, g.recent))}
            </Group>
          ))}
          {cursor !== null && (
            <div className={styles.moreWrap}>
              <button type="button" className={styles.more} disabled={loadingMore} onClick={() => void loadMore()}>
                {copy.chat.moreConversations}
              </button>
            </div>
          )}
        </div>
      );
    }
  } else if (result === null) {
    body = (
      <Group paper>
        {[0, 1, 2].map((i) => (
          <Skeleton key={i} size="row" />
        ))}
      </Group>
    );
  } else if (result.kind === "offline") {
    body = <p className={styles.line}>{copy.offline.later}</p>;
  } else {
    body = <BlockError code={result.kind === "error" ? result.code : result.kind} onRetry={() => load(query ?? "")} />;
  }

  return (
    <div className={styles.wrap}>
      <div className={styles.top}>
        <button type="button" className={`${styles.newChat} pressable`} disabled={readOnly} onClick={onNew}>
          <span className={styles.newMark} aria-hidden="true">
            <Icon name="compose" />
          </span>
          {copy.chat.newConversation}
        </button>
        <input
          type="search"
          className={styles.search}
          aria-label={copy.chat.search}
          placeholder={copy.chat.search}
          value={typed}
          onChange={(e) => setTyped(e.target.value)}
          enterKeyHint="search"
        />
      </div>
      {body}
      {asking && (
        <ConfirmSheet
          summary={copy.chat.deleteAsk}
          busy={deleting}
          keepLabel={copy.chat.keep}
          changeLabel={copy.chat.delete}
          onKeep={() => setAsking(null)}
          onChange={() => void remove(asking)}
        />
      )}
    </div>
  );
}
