import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import type { Today as TodayData } from "../api/types.gen";
import { useAction } from "../api/actions";
import { useChatSheet } from "../chat/sheetContext";
import { BlockError } from "../components/BlockError";
import { ChatLauncher, launcherReason } from "../components/ChatLauncher";
import { DoneFold } from "../components/DoneFold";
import { Group } from "../components/Group";
import { Icon } from "../components/icons";
import { LargeTitle } from "../components/LargeTitle";
import { MoreButton } from "../components/MoreButton";
import { AgentNoteLines } from "../components/AgentNoteLines";
import { Markdown } from "../components/Markdown";
import { OfflineNotice } from "../components/OfflineNotice";
import { Row } from "../components/Row";
import { Skeleton } from "../components/Skeleton";
import { StatusDot } from "../components/StatusDot";
import { TodoRow } from "../components/TodoRow";
import { useToast } from "../components/Toast";
import { useConnection, useWritable } from "../lib/ConnectionProvider";
import { splitAgentNotes } from "../lib/agentNotes";
import { copy } from "../lib/copy";
import { onTodayRefresh } from "../lib/push";
import { useSnapshotted } from "../lib/snapshot";
import { addDays, formatKst } from "../lib/time";
import page from "../styles/page.module.css";
import { HabitList } from "../ui/components/HabitList";
import { UiPart } from "../ui/registry";
import type { PartData } from "../ui/types";
import { PinnedCard } from "./PinnedCard";
import styles from "./Today.module.css";
import { useConfirms } from "./useConfirms";
import { useConfirmedAction, useNotAllowed, useOptimisticCheck } from "./todoActions";

const SCORES = [1, 2, 3, 4, 5];
// SP9 9.3: today's events show at most five rows, the rest behind "스케줄에서 {n}개 더 보기".
const EVENT_ROWS = 5;
// An event's start (UTC) as Seoul "HH:MM"; all-day has none.
const clock = (start: string | null) => (start === null ? copy.schedule.allDay : formatKst(start, "HH:mm"));
const FOLD_LINES = 3;
const FOLD_CHARS = 140;

function dateLine(data: TodayData): string {
  const [, m, d] = data.date.split("-").map(Number);
  return copy.today.dateLine(m, d, data.weekday);
}

// Spec 5.5.1 blocks 1-7 (and SP7 6.1 habits after the condition), 5.5.4 offline, F3, F9.
export function Today() {
  const { state, recheck } = useConnection();
  const { view, refresh } = useSnapshotted<TodayData>("today", "/today", "Today");
  const { run } = useAction();
  const toast = useToast();

  const [briefOpen, setBriefOpen] = useState(false);
  const [changing, setChanging] = useState(false);

  const chat = useChatSheet();

  useEffect(() => toast.onUndone(() => void refresh()), [toast, refresh]);
  // What was said in the sheet may have changed today (F4): read again when it closes.
  useEffect(() => chat.onClosed(() => void refresh()), [chat, refresh]);
  // A push came while the app is open (F7), or a chat answer finished: read again now.
  useEffect(() => onTodayRefresh(() => void refresh()), [refresh]);

  const data = view.kind === "live" || view.kind === "snapshot" ? view.data : null;
  const writable = useWritable(view.kind === "live");
  const canChat = useWritable(view.kind === "live", { strict: true });

  // Block 3: the ui_confirm cards of every pending check-in (read again after any write on them).
  const pendingKey = view.kind === "live" ? view.data.checkins.filter((c) => c.state === "pending").map((c) => c.id).join(",") : "";
  const { confirms, reread } = useConfirms(pendingKey);
  const afterPartAction = useCallback(() => {
    void refresh();
    reread();
  }, [refresh, reread]);

  const afterHabit = useCallback(() => void refresh(), [refresh]);

  const offline = view.kind === "snapshot" || view.kind === "none";
  const date = data?.date ?? "";

  const liveTodos = useMemo(() => (view.kind === "live" ? view.data.todos.map((t) => t.todo) : null), [view]);
  const { show, toggle } = useOptimisticCheck(liveTodos, refresh);
  // Dropping, and moving a to-do that has a time (SP6 8), may ask first.
  const { run: confirmed, sheet: confirmSheet } = useConfirmedAction(refresh);
  const drop = (id: number) => confirmed("drop_task", { id });
  const notAllowed = useNotAllowed(refresh);

  // The BE's logical day, not the device calendar (it differs between 00:00 and 04:00).
  const tomorrow = (id: number) => confirmed("move_task", { id, planned_for: addDays(date, 1) });

  const unpin = async (id: number) => {
    const out = await run("unpin_card", { id });
    if (out?.kind === "applied") await refresh();
    else await notAllowed(out);
  };

  const move = async (ids: number[], at: number, by: -1 | 1) => {
    const next = [...ids];
    [next[at], next[at + by]] = [next[at + by], next[at]];
    const out = await run("reorder_cards", { ids: next });
    if (out?.kind === "applied") await refresh();
    else await notAllowed(out);
  };

  // SP9 9.3: closing a missed-reminder line has no activity and no undo; the line goes on the next read.
  const dismiss = async (event_id: number, day: string) => {
    if (await run("dismiss_missed_reminder", { event_id, date: day })) await refresh();
  };

  const record = async (score: number) => {
    const out = await run("record_condition", { date, score });
    if (out?.kind === "applied") {
      setChanging(false);
      await refresh();
    } else await notAllowed(out);
  };

  let body: React.ReactNode;
  if (view.kind === "loading") {
    body = (
      <>
        <Group paper>
          <Row title={<Skeleton size="line" />} />
        </Group>
        <Group paper>
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
        <Group paper>
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
    // SP14 10장: the partners' observation lines are drawn under the Markdown with their pictograms; the fold counts the body only.
    const briefParts = brief !== null ? splitAgentNotes(brief.text) : null;
    const briefBody = briefParts?.body ?? "";
    const longBrief = brief !== null && (briefBody.split("\n").length > FOLD_LINES || briefBody.length > FOLD_CHARS);
    const folded = longBrief && !briefOpen;
    const score = t.condition?.score ?? null;
    const showPills = score === null || changing;
    const list = t.todos.map((item) => ({ ...item, todo: show(item.todo) }));
    // Open rows keep the BE's order; rows that are done go to the end of the list (spec 5.5.1).
    const display = [...list.filter((i) => i.todo.status !== "done"), ...list.filter((i) => i.todo.status === "done")];
    const openRows = display.filter((i) => i.todo.status !== "done");
    const doneRows = display.filter((i) => i.todo.status === "done"); // folded until pressed
    const openCount = openRows.length;
    const todoRow = (item: (typeof display)[number]) => (
      <TodoRow
        key={item.todo.id}
        todo={item.todo}
        readOnly={readOnly}
        onToggle={() => void toggle(item.todo)}
        onTomorrow={() => void tomorrow(item.todo.id)}
        onDrop={() => void drop(item.todo.id)}
      />
    );
    const readOnly = !writable;
    const pinned = [...t.cards].sort((a, b) => a.order - b.order);
    const pinnedIds = pinned.map((c) => c.id);
    const habits = t.habits ?? [];
    // A BE (or a snapshot) from before the schedule has neither field: no block (SP9 14장).
    const events = t.events ?? [];
    const missed = t.missed_reminders ?? [];

    body = (
      <>
        {pending.length > 0 && (
          <Group paper>
            {pending.map((c) => (
              <Row key={c.id} href={`/checkin/?id=${c.id}`} title={copy.today.checkinLine(copy.loops[c.loop])} />
            ))}
          </Group>
        )}
        {confirms.length > 0 && (
          <section className={styles.block}>
            <h2 className={styles.blockHeading}>{copy.today.needsConfirm}</h2>
            {confirms.map((c) => (
              <div key={c.key} className={styles.blockItem}>
                <UiPart name="ui_confirm" props={c.props} ctx={{ where: "today", readOnly, onAfterAction: afterPartAction }} />
              </div>
            ))}
          </section>
        )}
        {brief ? (
          <Group paper
            heading={
              <>
                {copy.loops[brief.loop]}
                {brief.sent_at && " "}
                {brief.sent_at && <span className={styles.briefAt}>{formatKst(brief.sent_at, "HH:mm")}</span>}
              </>
            }
          >
            <div className={styles.brief}>
              {briefBody !== "" && <Markdown text={briefBody} className={`${styles.briefText} ${folded ? styles.folded : ""}`} />}
              {longBrief && (
                <button type="button" className={styles.more} aria-expanded={briefOpen} onClick={() => setBriefOpen((o) => !o)}>
                  {briefOpen ? copy.today.lessPlain : copy.today.morePlain}
                </button>
              )}
              {briefParts !== null && briefParts.notes.length > 0 && (
                <div className={styles.briefNotes}>
                  <AgentNoteLines notes={briefParts.notes} />
                </div>
              )}
            </div>
          </Group>
        ) : (
          offline && <p className={styles.line}>{copy.offline.catchUp}</p>
        )}
        <Group paper heading={copy.today.condition}>
          <div className={styles.condition}>
            {showPills ? (
              <>
                <div className={styles.pills}>
                  {SCORES.map((n) => (
                    <button
                      key={n}
                      type="button"
                      className={`${styles.pill} ${score === n ? styles.picked : ""} pressable`}
                      aria-label={copy.today.conditionScore(n)}
                      aria-pressed={score === n}
                      disabled={readOnly}
                      onClick={() => void record(n)}
                    >
                      {n}
                    </button>
                  ))}
                </div>
                {/* What the ends of the scale mean: without them 5 could be good or bad. */}
                <div className={styles.ends}>
                  <span>{copy.parts.scoreLow}</span>
                  <span>{copy.parts.scoreHigh}</span>
                </div>
              </>
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
        {/* SP9 9.3: one line per missed reminder (facts only, no count), then today's events. */}
        {missed.length > 0 && (
          <ul className={styles.missed}>
            {missed.map((r) => (
              <li key={`${r.event_id}:${r.date}`} className={styles.missedLine}>
                <span className={styles.missedText}>{(r.outcome === "missed" ? copy.today.missed : copy.today.unsent)(clock(r.start), r.title)}</span>
                <button type="button" className={styles.dismiss} aria-label={copy.today.dismissMissed(r.title)} disabled={readOnly} onClick={() => void dismiss(r.event_id, r.date)}>
                  <Icon name="close" />
                </button>
              </li>
            ))}
          </ul>
        )}
        {events.length > 0 && (
          <Group paper
            heading={copy.today.events}
            footer={
              events.length > EVENT_ROWS ? (
                <Link href={`/schedule/?date=${t.date}`} className={styles.seeAll}>
                  {copy.today.moreEvents(events.length - EVENT_ROWS)}
                </Link>
              ) : undefined
            }
          >
            {events.slice(0, EVENT_ROWS).map((e) => (
              <Link key={`${e.event_id}:${e.date}`} href={`/schedule/?date=${e.date}`} className={styles.event}>
                <span className={`${styles.eventAt} tnum`}>{clock(e.start)}</span>
                <span className={styles.eventTitle}>{e.title}</span>
                {e.area && (
                  <span className="area-dot" data-area={e.area}>
                    <span className="visually-hidden">{copy.areas[e.area]}</span>
                  </span>
                )}
              </Link>
            ))}
          </Group>
        )}
        {/* SP7 6.1: between the condition and the to-dos. A snapshot from before habits has no field. */}
        {habits.length > 0 ? (
          <Group paper
            heading={copy.habits.heading}
            action={
              <Link href="/habits/" className={styles.manage}>
                {copy.habits.manage}
              </Link>
            }
          >
            <div className={styles.habits}>
              <HabitList habits={habits} date={t.date} readOnly={readOnly} onChanged={afterHabit} />
            </div>
          </Group>
        ) : (
          <div className={styles.habitsEmpty}>
            <HabitList habits={habits} date={t.date} readOnly={readOnly} onChanged={afterHabit} />
          </div>
        )}
        <Group paper
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
            <>
              {openRows.map(todoRow)}
              <DoneFold count={doneRows.length}>{doneRows.map(todoRow)}</DoneFold>
            </>
          )}
        </Group>
        {pinned.map((card, i) => (
          <PinnedCard
            key={card.id}
            card={card}
            readOnly={readOnly}
            canMoveUp={i > 0}
            canMoveDown={i < pinned.length - 1}
            onUnpin={() => void unpin(card.id)}
            onMove={(by) => void move(pinnedIds, i, by)}
          >
            <UiPart name={card.component} props={card.props} data={(card.data ?? undefined) as PartData | undefined} ctx={{ where: "today", readOnly, onAfterAction: afterPartAction }} />
          </PinnedCard>
        ))}
      </>
    );
  }

  return (
    <main className={`${page.main} ${styles.main}`}>
      <LargeTitle
        title={copy.today.title}
        meta={data ? dateLine(data) : <Skeleton size="short" />}
        trailing={
          <>
            {state && <StatusDot state={state} />}
            <MoreButton />
          </>
        }
      />
      {state?.kind === "online" && state.degraded && <p className={styles.line}>{state.degraded}</p>}
      {offline && <OfflineNotice savedAt={view.kind === "snapshot" ? view.savedAt : null} onRetry={() => void recheck()} />}
      {body}
      {confirmSheet}
      <ChatLauncher disabled={!canChat} offline={offline} reason={launcherReason(view.kind === "blocked" ? view.result.kind : state?.kind)} onOpen={chat.open} />
    </main>
  );
}
