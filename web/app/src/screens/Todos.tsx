import { useRouter } from "next/router";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { type ActionOutcome, useAction } from "../api/actions";
import { type ApiResult, apiGet } from "../api/client";
import type { Drafts, DraftItem, Priorities, Today as TodayData, Todo, Week } from "../api/types.gen";
import { useChatSheet } from "../chat/sheetContext";
import { BlockError } from "../components/BlockError";
import { ChatLauncher, launcherReason } from "../components/ChatLauncher";
import { Group } from "../components/Group";
import { Icon } from "../components/icons";
import { LargeTitle } from "../components/LargeTitle";
import { MoreButton } from "../components/MoreButton";
import { OfflineNotice } from "../components/OfflineNotice";
import { Row } from "../components/Row";
import { Segmented } from "../components/Segmented";
import { Skeleton } from "../components/Skeleton";
import { StatusDot } from "../components/StatusDot";
import { TodoRow } from "../components/TodoRow";
import { useToast } from "../components/Toast";
import { useConnection, useWritable } from "../lib/ConnectionProvider";
import { copy } from "../lib/copy";
import { useSnapshotted } from "../lib/snapshot";
import { addDays } from "../lib/time";
import page from "../styles/page.module.css";
import { AddTodoSheet } from "./AddTodoSheet";
import { type Edit, EditTodoSheet } from "./EditTodoSheet";
import styles from "./Todos.module.css";
import { useConfirmedAction, useNotAllowed, useOptimisticCheck } from "./todoActions";

export type TodosTab = "day" | "week" | "month" | "quarter" | "year";
const TABS: TodosTab[] = ["day", "week", "month", "quarter", "year"];
type RangeTab = "month" | "quarter" | "year";
const isRange = (t: TodosTab): t is RangeTab => t === "month" || t === "quarter" || t === "year";
const LABEL: Record<TodosTab, string> = {
  day: copy.todos.periods.today,
  week: copy.todos.periods.week,
  month: copy.todos.periods.month,
  quarter: copy.todos.periods.quarter,
  year: copy.todos.periods.year,
};

const is404 = (r: { kind: string; status?: number }) => r.kind === "error" && r.status === 404;
// Open rows first, done rows after them (spec 5.5.1), each keeping the BE's order.
const openFirst = (todos: Todo[]) => [...todos.filter((t) => t.status !== "done"), ...todos.filter((t) => t.status === "done")];

// Spec 5.5.5, F6.
export function Todos({ tab: requested = "week" }: { tab?: TodosTab }) {
  const router = useRouter();
  const { state, conn, recheck } = useConnection();
  const { run } = useAction();

  const { view: todayView, refresh: refreshToday } = useSnapshotted<TodayData>("today", "/today", "Today");
  const { view: weekView, refresh: refreshWeek } = useSnapshotted<Week>("week", "/week", "Week");
  const offlineConn = state?.kind === "offline";

  // /priorities (R1) and /drafts (R2) may not exist yet: a 404 hides the tabs or the bundle.
  const [rangesHidden, setRangesHidden] = useState(false);
  const [prio, setPrio] = useState<Priorities | null>(null);
  const [prioErr, setPrioErr] = useState<ApiResult<unknown> | null>(null);
  const [drafts, setDrafts] = useState<DraftItem[] | null>(null);
  const [draftsHidden, setDraftsHidden] = useState(false);
  const [draftsErr, setDraftsErr] = useState<ApiResult<unknown> | null>(null);
  const [version, setVersion] = useState(0);
  const [adding, setAdding] = useState(false);
  const [edit, setEdit] = useState<Edit | null>(null);

  const tab: TodosTab = rangesHidden && isRange(requested) ? "week" : requested;
  const online = state?.kind === "online";
  const fellBack = tab !== requested;
  useEffect(() => {
    if (fellBack) void router.replace("/todos/?tab=week");
  }, [fellBack, router]);

  const loadDrafts = useCallback(async () => {
    const r = await apiGet<Drafts>("/drafts", "Drafts");
    if (r.kind === "ok") {
      setDrafts(r.data.items);
      setDraftsErr(null);
    } else if (is404(r)) setDraftsHidden(true);
    else if (r.kind !== "offline") setDraftsErr(r);
  }, []);

  useEffect(() => {
    if (!online || draftsHidden) return;
    void loadDrafts();
  }, [online, draftsHidden, loadDrafts, version]);

  // Without this the month tab would only vanish after someone taps it.
  const probed = useRef<string | null>(null);
  useEffect(() => {
    if (!online || !conn || probed.current === conn.beUrl) return;
    probed.current = conn.beUrl; // once per connection, not on every tab change
    void apiGet<Priorities>("/priorities?cadence=month", "Priorities").then((r) => {
      if (is404(r)) setRangesHidden(true);
    });
  }, [online, conn]);

  useEffect(() => {
    setPrioErr(null);
    if (!online || !isRange(tab)) return;
    let alive = true;
    void apiGet<Priorities>(`/priorities?cadence=${tab}`, "Priorities").then((r) => {
      if (!alive) return;
      if (r.kind === "ok") {
        setPrio(r.data);
      } else if (is404(r)) {
        setRangesHidden(true);
      } else if (r.kind !== "offline") {
        setPrioErr(r);
      }
    });
    return () => {
      alive = false;
    };
  }, [online, tab, version]);

  const refreshAll = useCallback(async () => {
    await Promise.all([refreshToday(), refreshWeek()]);
    setVersion((v) => v + 1);
  }, [refreshToday, refreshWeek]);
  const guard = useNotAllowed(refreshAll);
  const chat = useChatSheet();
  // What was said in the sheet may have changed the lists: read again when it closes.
  useEffect(() => chat.onClosed(() => void refreshAll()), [chat, refreshAll]);

  // The BE's logical day, not the device calendar (it differs between 00:00 and 04:00).
  const todayDate = todayView.kind === "live" ? todayView.data.date : weekView.kind === "live" ? (weekView.data.days.find((d) => d.is_today)?.date ?? null) : null;

  const shownPrio = prio && isRange(tab) && prio.cadence === tab ? prio : null;
  const liveTodos = useMemo(() => {
    if (tab === "day" && todayView.kind === "live") return todayView.data.todos.map((t) => t.todo);
    if (tab === "week" && weekView.kind === "live") return [...weekView.data.priorities, ...weekView.data.days.flatMap((d) => d.todos)];
    if (shownPrio) return shownPrio.items;
    return null;
  }, [tab, todayView, weekView, shownPrio]);
  const { show, toggle } = useOptimisticCheck(liveTodos, refreshAll);
  // Dropping, and moving a to-do that has a time (SP6 8), may ask first.
  const { run: confirmed, sheet: confirmSheet } = useConfirmedAction(refreshAll);
  const drop = (id: number) => confirmed("drop_task", { id });

  const tomorrow = async (id: number) => {
    if (!todayDate) return;
    await confirmed("move_task", { id, planned_for: addDays(todayDate, 1) });
  };

  // One draft write at a time: "모두 확정" and a single "확정" must not both go out for the same drafts.
  const draftLock = useRef(false);
  const [draftBusy, setDraftBusy] = useState(false);
  const confirmDrafts = async (ids: number[]) => {
    if (ids.length === 0 || draftLock.current) return;
    draftLock.current = true;
    setDraftBusy(true);
    try {
      const out = await run("confirm_tasks", { ids });
      if (out?.kind === "applied") await refreshAll();
      else await guard(out);
    } finally {
      draftLock.current = false;
      setDraftBusy(false);
    }
  };
  const dropDraft = async (id: number) => {
    if (draftLock.current) return;
    draftLock.current = true;
    setDraftBusy(true);
    try {
      await drop(id);
    } finally {
      draftLock.current = false;
      setDraftBusy(false);
    }
  };

  const row = (todo: Todo, readOnly: boolean) => (
    <TodoRow
      key={todo.id}
      todo={show(todo)}
      readOnly={readOnly}
      onToggle={() => void toggle(todo)}
      onTomorrow={() => void tomorrow(todo.id)}
      onDrop={() => void drop(todo.id)}
      onChangeDate={() => setEdit({ kind: "date", todo })}
      onEditTitle={() => setEdit({ kind: "title", todo })}
    />
  );
  const rows = (todos: Todo[], readOnly: boolean) => todos.map((t) => row(t, readOnly));

  const weekOffline = weekView.kind === "snapshot" || weekView.kind === "none";
  const offline = offlineConn || (tab === "week" && weekOffline);
  const live = !offline;
  const writable = useWritable(live);
  const canChat = useWritable(live, { strict: true });

  let body: React.ReactNode = null;
  if (offline && tab !== "week") {
    body = (
      <section className={styles.notice} role="status">
        <strong className={styles.lead}>{copy.offline.lead}</strong> <span>{copy.offline.later}</span>
        <div>
          <button type="button" className={styles.retry} onClick={() => void recheck()}>
            {copy.offline.reconnect}
          </button>
        </div>
      </section>
    );
  } else if (tab === "week") {
    if (weekView.kind === "loading") {
      body = (
        <Group paper>
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} size="row" />
          ))}
        </Group>
      );
    } else if (weekView.kind === "blocked") {
      const r = weekView.result;
      body = (
        <Group paper>
          <BlockError code={r.kind === "error" ? r.code : r.kind} onRetry={() => void refreshWeek()} />
        </Group>
      );
    } else if (weekView.kind === "none") {
      body = null;
    } else {
      const w = weekView.data;
      const readOnly = weekView.kind !== "live" || !writable;
      body = (
        <>
          {w.priorities.length > 0 && <Group paper heading={copy.todos.weekPriorities}>{rows(w.priorities, readOnly)}</Group>}
          {w.days.map((d) => {
            const [, m, day] = d.date.split("-").map(Number);
            if (d.todos.length === 0) {
              return (
                <p key={d.date} className={styles.emptyDay}>
                  {copy.todos.emptyDay(d.weekday)}
                </p>
              );
            }
            return (
              <Group paper key={d.date} heading={copy.todos.dayHeading(d.weekday, m, day, d.is_today)}>
                {rows(openFirst(d.todos.map(show)), readOnly)}
              </Group>
            );
          })}
        </>
      );
    }
  } else if (tab === "day") {
    if (todayView.kind === "live") {
      const list = openFirst(todayView.data.todos.map((t) => show(t.todo)));
      body = <Group paper heading={copy.todos.periods.today}>{list.length === 0 ? <Row title={copy.today.noTodos} /> : rows(list, !writable)}</Group>;
    } else if (todayView.kind === "blocked") {
      body = (
        <Group paper>
          <BlockError code={todayView.result.kind === "error" ? todayView.result.code : todayView.result.kind} onRetry={() => void refreshToday()} />
        </Group>
      );
    } else {
      body = (
        <Group paper>
          <Skeleton size="row" />
        </Group>
      );
    }
  } else if (shownPrio) {
    body = (
      <Group paper heading={copy.todos.periodPriorities(LABEL[tab])}>
        {shownPrio.items.length === 0 ? <Row title={copy.todos.noPriorities} /> : rows(shownPrio.items, !writable)}
      </Group>
    );
  } else if (prioErr) {
    body = (
      <Group paper>
        <BlockError code={prioErr.kind === "error" ? prioErr.code : prioErr.kind} onRetry={() => setVersion((v) => v + 1)} />
      </Group>
    );
  } else {
    body = (
      <Group paper>
        <Skeleton size="row" />
      </Group>
    );
  }

  const draftList = live && !draftsHidden && !draftsErr && drafts && drafts.length > 0 ? drafts : null;
  const options = TABS.filter((t) => !(rangesHidden && isRange(t))).map((t) => ({ value: t, label: LABEL[t] }));

  return (
    <main className={`${page.main} ${styles.main}`}>
      <LargeTitle
        title={copy.todos.title}
        trailing={
          <span className={styles.trailing}>
            {state && <StatusDot state={state} />}
            <button type="button" className={`${styles.add} pressable`} aria-label={copy.todos.add} disabled={!writable || !todayDate} onClick={() => setAdding(true)}>
              <Icon name="plus" />
            </button>
            <MoreButton />
          </span>
        }
      />
      <div className={styles.tabs}>
        <Segmented<TodosTab>
          ariaLabel={copy.todos.periodsLabel}
          options={options}
          value={tab}
          onChange={(v) => void router.replace(`/todos/?tab=${v}`)}
        />
      </div>
      {tab === "week" && weekOffline && <OfflineNotice savedAt={weekView.kind === "snapshot" ? weekView.savedAt : null} onRetry={() => void recheck()} />}
      {body}
      {draftList && (
        <Group paper
          heading={copy.todos.drafts(draftList.length)}
          action={
            draftList.length >= 2 ? (
              <button
                type="button"
                className={styles.bulk}
                disabled={draftBusy || !writable}
                onClick={() => void confirmDrafts(draftList.map((d) => d.todo.id))}
              >
                {copy.todos.confirmAll}
              </button>
            ) : undefined
          }
        >
          <p className={styles.hint}>{copy.todos.draftsHint}</p>
          {draftList.map(({ todo }) => (
            <div key={todo.id} className={styles.draftRow}>
              <span className={styles.draftTitle}>{todo.title}</span>
              <button type="button" className={styles.draftButton} aria-label={copy.todos.dropLabel(todo.title)} disabled={draftBusy || !writable} onClick={() => void dropDraft(todo.id)}>
                {copy.todos.drop}
              </button>
              <button
                type="button"
                className={`${styles.draftButton} ${styles.confirm}`}
                aria-label={copy.todos.confirmLabel(todo.title)}
                disabled={draftBusy || !writable}
                onClick={() => void confirmDrafts([todo.id])}
              >
                {copy.todos.confirm}
              </button>
            </div>
          ))}
        </Group>
      )}
      {live && !draftsHidden && draftsErr && (
        <Group paper>
          <BlockError code={draftsErr.kind === "error" ? draftsErr.code : draftsErr.kind} onRetry={() => void loadDrafts()} />
        </Group>
      )}
      {confirmSheet}
      {todayDate && (
        <AddTodoSheet
          open={adding}
          onClose={() => setAdding(false)}
          defaultDate={todayDate}
          onAdded={() => void refreshAll()}
        />
      )}
      <EditTodoSheet edit={edit} onClose={() => setEdit(null)} onDone={refreshAll} guard={guard} />
      <ChatLauncher disabled={!canChat} offline={offlineConn} reason={launcherReason(state?.kind)} onOpen={chat.open} />
    </main>
  );
}
