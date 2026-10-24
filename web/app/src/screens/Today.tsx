import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import type { Today as TodayData, TodayTodo } from "../api/types.gen";
import { useAction } from "../api/actions";
import { BlockError } from "../components/BlockError";
import { ChatLauncher } from "../components/ChatLauncher";
import { ConfirmSheet } from "../components/ConfirmSheet";
import { Group } from "../components/Group";
import { LargeTitle } from "../components/LargeTitle";
import { OfflineNotice } from "../components/OfflineNotice";
import { Row } from "../components/Row";
import { Skeleton } from "../components/Skeleton";
import { StatusDot } from "../components/StatusDot";
import { TodoRow } from "../components/TodoRow";
import { useToast } from "../components/Toast";
import { useConnection } from "../lib/ConnectionProvider";
import { copy } from "../lib/copy";
import { useSnapshotted } from "../lib/snapshot";
import { addDays } from "../lib/time";
import page from "../styles/page.module.css";
import styles from "./Today.module.css";

const SCORES = [1, 2, 3, 4, 5];
const FOLD_LINES = 3;
const FOLD_CHARS = 140;

interface PendingConfirm {
  id: number;
  token: string;
  summary: string;
}

function dateLine(data: TodayData): string {
  const [, m, d] = data.date.split("-").map(Number);
  return copy.today.dateLine(m, d, data.weekday);
}

// Spec 5.5.1 blocks 1, 2, 4, 5, 6 (3 and 7 come with A04), 5.5.4 offline, F3, F9.
export function Today() {
  const { state, recheck } = useConnection();
  const { view, refresh } = useSnapshotted<TodayData>("today", "/today", "Today");
  const { run } = useAction();
  const toast = useToast();

  // Optimistic check (spec 4.6): todo id -> the done state the person asked for, until the answer is in.
  const [flip, setFlip] = useState<Readonly<Record<number, boolean>>>({});
  const busy = useRef(new Set<number>());
  const [confirm, setConfirm] = useState<PendingConfirm | null>(null);
  const [confirmBusy, setConfirmBusy] = useState(false);
  const [briefOpen, setBriefOpen] = useState(false);
  const [changing, setChanging] = useState(false);

  useEffect(() => toast.onUndone(() => void refresh()), [toast, refresh]);

  const unflip = useCallback((id: number) => {
    setFlip((f) => {
      const { [id]: _gone, ...rest } = f;
      return rest;
    });
  }, []);

  const data = view.kind === "live" || view.kind === "snapshot" ? view.data : null;
  const live = view.kind === "live";
  const offline = view.kind === "snapshot" || view.kind === "none";
  const date = data?.date ?? "";

  const toggle = async (item: TodayTodo) => {
    const id = item.todo.id;
    if (busy.current.has(id)) return; // the answer to the first press has not come yet
    busy.current.add(id);
    const wasDone = (flip[id] ?? item.todo.status === "done");
    setFlip((f) => ({ ...f, [id]: !wasDone }));
    try {
      const out = await run(wasDone ? "reopen_task" : "complete_task", { id });
      if (out?.kind === "applied") await refresh();
      else if (out?.kind === "conflict") toast.show({ text: copy.actions.failed });
    } finally {
      busy.current.delete(id);
      unflip(id);
    }
  };

  const tomorrow = async (id: number) => {
    // The BE's logical day, not the device calendar (it differs between 00:00 and 04:00).
    const out = await run("move_task", { id, planned_for: addDays(date, 1) });
    if (out?.kind === "applied") await refresh();
  };

  const drop = async (id: number) => {
    const out = await run("drop_task", { id });
    if (out?.kind === "applied") await refresh();
    else if (out?.kind === "needs_confirm") setConfirm({ id, token: out.confirmToken, summary: out.summary });
  };

  const confirmDrop = async () => {
    if (!confirm || confirmBusy) return;
    setConfirmBusy(true);
    try {
      const out = await run("drop_task", { id: confirm.id }, { confirmToken: confirm.token });
      if (out === null) return;
      if (out.kind === "needs_confirm") {
        setConfirm({ id: confirm.id, token: out.confirmToken, summary: out.summary });
        return;
      }
      if (out.kind === "conflict") toast.show({ text: copy.todos.confirmExpired });
      setConfirm(null);
      if (out.kind === "applied") await refresh();
    } finally {
      setConfirmBusy(false);
    }
  };

  const record = async (score: number) => {
    const out = await run("record_condition", { date, score });
    if (out?.kind === "applied") {
      setChanging(false);
      await refresh();
    }
  };

  let body: React.ReactNode;
  if (view.kind === "loading") {
    body = (
      <>
        <Group>
          <Row title={<Skeleton size="line" />} />
        </Group>
        <Group>
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} size="row" />
          ))}
        </Group>
      </>
    );
  } else if (view.kind === "blocked") {
    const r = view.result;
    if (r.kind === "unauthorized") {
      body = (
        <section className={styles.notice} role="status">
          <p className={styles.noticeText}>{copy.status.unauthorized}</p>
          <Link href="/settings/" className={styles.noticeLink}>
            {copy.errors.goSettings}
          </Link>
        </section>
      );
    } else if (r.kind === "rate_limited") {
      body = <p className={styles.line}>{copy.status.tooMany}</p>;
    } else if (r.kind === "safe_mode") {
      body = <p className={styles.line}>{copy.status.safeMode}</p>;
    } else {
      body = (
        <Group>
          <BlockError code={r.kind === "error" ? r.code : r.kind} onRetry={() => void refresh()} />
        </Group>
      );
    }
  } else if (view.kind === "none") {
    body = null; // the notice above says there is nothing saved yet
  } else {
    const t = view.data;
    const pending = t.checkins.filter((c) => c.state === "pending");
    const brief = t.brief;
    const longBrief = brief !== null && (brief.text.split("\n").length > FOLD_LINES || brief.text.length > FOLD_CHARS);
    const folded = longBrief && !briefOpen;
    const score = t.condition?.score ?? null;
    const showPills = score === null || changing;
    const list = t.todos.map((item) => {
      const want = flip[item.todo.id];
      if (want === undefined || want === (item.todo.status === "done")) return item;
      return {
        ...item,
        todo: { ...item.todo, status: want ? ("done" as const) : ("open" as const), completed_at: want ? new Date().toISOString() : null },
      };
    });
    // Open rows keep the BE's order; rows that are done go to the end of the list (spec 5.5.1).
    const display = [...list.filter((i) => i.todo.status !== "done"), ...list.filter((i) => i.todo.status === "done")];
    const openCount = display.filter((i) => i.todo.status !== "done").length;
    const readOnly = !live;

    body = (
      <>
        {pending.length > 0 && (
          <Group>
            {pending.map((c) => (
              <Row key={c.id} href={`/checkin/?id=${c.id}`} title={copy.today.checkinLine(copy.loops[c.loop])} />
            ))}
          </Group>
        )}
        {/* A04: "확인이 필요해요" (ui_confirm bundle) goes here. */}
        {brief ? (
          <Group>
            <div className={styles.brief}>
              <p className={`${styles.briefText} ${folded ? styles.folded : ""}`}>{brief.text}</p>
              {longBrief && (
                <button type="button" className={styles.more} aria-expanded={briefOpen} onClick={() => setBriefOpen((o) => !o)}>
                  {briefOpen ? copy.today.lessPlain : copy.today.morePlain}
                </button>
              )}
            </div>
          </Group>
        ) : (
          offline && <p className={styles.line}>{copy.offline.catchUp}</p>
        )}
        <Group heading={copy.today.condition}>
          <div className={styles.condition}>
            {showPills ? (
              <div className={styles.pills}>
                {SCORES.map((n) => (
                  <button
                    key={n}
                    type="button"
                    className={`${styles.pill} ${score === n ? styles.picked : ""}`}
                    aria-label={copy.today.conditionScore(n)}
                    aria-pressed={score === n}
                    disabled={readOnly}
                    onClick={() => void record(n)}
                  >
                    {n}
                  </button>
                ))}
              </div>
            ) : (
              <div className={styles.current}>
                <span className={styles.value}>{copy.today.conditionScore(score)}</span>
                <button type="button" className={styles.change} disabled={readOnly} onClick={() => setChanging(true)}>
                  {copy.today.change}
                </button>
              </div>
            )}
            {readOnly && <p className={styles.reason}>{copy.offline.writeLater}</p>}
          </div>
        </Group>
        <Group
          heading={copy.today.todosHeading(openCount)}
          footer={
            <Link href="/todos/" className={styles.seeAll}>
              {copy.today.seeAll}
            </Link>
          }
        >
          {display.length === 0 ? (
            <Row title={copy.today.noTodos} />
          ) : (
            display.map((item) => (
              <TodoRow
                key={item.todo.id}
                todo={item.todo}
                readOnly={readOnly}
                onToggle={() => void toggle(item)}
                onTomorrow={() => void tomorrow(item.todo.id)}
                onDrop={() => void drop(item.todo.id)}
              />
            ))
          )}
        </Group>
        {/* A04: pinned cards (/today.cards) go here. */}
      </>
    );
  }

  return (
    <main className={`${page.main} ${styles.main}`}>
      <LargeTitle title={copy.today.title} meta={data ? dateLine(data) : <Skeleton size="short" />} trailing={state ? <StatusDot state={state} /> : undefined} />
      {state?.kind === "online" && state.degraded && <p className={styles.line}>{state.degraded}</p>}
      {offline && <OfflineNotice savedAt={view.kind === "snapshot" ? view.savedAt : null} onRetry={() => void recheck()} />}
      {body}
      {confirm && <ConfirmSheet summary={confirm.summary} busy={confirmBusy} onKeep={() => setConfirm(null)} onChange={() => void confirmDrop()} />}
      <ChatLauncher disabled={!live} offline={offline} onOpen={() => {}} />
    </main>
  );
}
