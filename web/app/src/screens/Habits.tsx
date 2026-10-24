import Link from "next/link";
import { type ReactNode, useCallback, useEffect, useRef, useState } from "react";
import { type ActionOutcome, useAction } from "../api/actions";
import { apiGet } from "../api/client";
import type { Habit, HabitHistory, HabitsList } from "../api/types.gen";
import { BlockError } from "../components/BlockError";
import { ConfirmSheet } from "../components/ConfirmSheet";
import { Group } from "../components/Group";
import { Icon } from "../components/icons";
import { LargeTitle } from "../components/LargeTitle";
import { OfflineNotice } from "../components/OfflineNotice";
import { Row } from "../components/Row";
import { Sheet } from "../components/Sheet";
import { Skeleton } from "../components/Skeleton";
import { useToast } from "../components/Toast";
import { useConnection, useWritable } from "../lib/ConnectionProvider";
import { copy, habitMeta } from "../lib/copy";
import { usePolling } from "../lib/polling";
import page from "../styles/page.module.css";
import { HabitGrid, weekLines } from "./HabitGrid";
import { HabitSheet } from "./HabitSheet";
import styles from "./Habits.module.css";
import { useNotAllowed } from "./todoActions";

type Status = Habit["status"];

const cadence = (h: Pick<Habit, "kind" | "target_per_week">) =>
  h.kind === "weekly" && h.target_per_week !== null ? copy.habits.weeklyN(h.target_per_week) : copy.habits.daily;

interface PendingConfirm {
  id: number;
  token: string;
  summary: string;
}

// SP7 6.2: which habits am I keeping, and are they settling in? Off the tabs, "‹ 오늘" back.
// One read of every status (`status=all`) draws the three sections from the same moment.
export function Habits() {
  const { state, recheck } = useConnection();
  const { result, refresh } = usePolling<HabitsList>(() => apiGet<HabitsList>("/habits?status=all", "HabitsList"));
  const { run } = useAction();
  const toast = useToast();
  const notAllowed = useNotAllowed(refresh);

  // The last good answer stays, disabled, when the connection drops (F9).
  const [last, setLast] = useState<{ data: HabitsList; at: string } | null>(null);
  useEffect(() => {
    if (result?.kind === "ok") setLast({ data: result.data, at: new Date().toISOString() });
  }, [result]);
  const data = result?.kind === "ok" ? result.data : (last?.data ?? null);
  const offline = state?.kind === "offline" || result?.kind === "offline";
  const writable = useWritable(result?.kind === "ok");

  const [adding, setAdding] = useState(false);
  // The habit a sheet shows stays after it closes, so the sheet slides away with it.
  const [editing, setEditing] = useState<Habit | null>(null);
  const [editOpen, setEditOpen] = useState(false);
  const [detailId, setDetailId] = useState<number | null>(null);
  const [detailOpen, setDetailOpen] = useState(false);
  const [archivedOpen, setArchivedOpen] = useState(false);
  const [confirm, setConfirm] = useState<PendingConfirm | null>(null);
  const [confirmBusy, setConfirmBusy] = useState(false);
  const confirmLock = useRef(false);
  const [acting, setActing] = useState<ReadonlySet<number>>(new Set());
  const busy = useRef(new Set<number>());
  // Bumped after every write and undo, so an open detail sheet reads its grid again.
  const [reload, setReload] = useState(0);

  const changed = useCallback(() => {
    void refresh();
    setReload((n) => n + 1);
  }, [refresh]);
  useEffect(() => toast.onUndone(changed), [toast, changed]);

  const setStatus = async (id: number, status: Status) => {
    if (busy.current.has(id)) return; // the answer to the first press has not come yet
    busy.current.add(id);
    setActing(new Set(busy.current));
    try {
      const out: ActionOutcome | null = await run("set_habit_status", { id, status });
      if (out === null) return;
      if (out.kind === "applied") {
        setDetailOpen(false);
        changed();
      } else if (out.kind === "needs_confirm") {
        // 그만두기 from the app (SP7 5.5): the BE's question, then the same action with its token.
        setDetailOpen(false);
        setConfirm({ id, token: out.confirmToken, summary: out.summary });
      } else await notAllowed(out);
    } finally {
      busy.current.delete(id);
      setActing(new Set(busy.current));
    }
  };

  const confirmArchive = async () => {
    if (!confirm || confirmLock.current) return;
    confirmLock.current = true;
    setConfirmBusy(true);
    try {
      const out = await run("set_habit_status", { id: confirm.id, status: "archived" }, { confirmToken: confirm.token });
      if (out === null) return;
      if (out.kind === "needs_confirm") {
        setConfirm({ id: confirm.id, token: out.confirmToken, summary: out.summary });
        return;
      }
      if (out.kind === "conflict") toast.show({ text: copy.todos.confirmExpired });
      setConfirm(null);
      if (out.kind === "applied") changed();
    } finally {
      confirmLock.current = false;
      setConfirmBusy(false);
    }
  };

  const items = data?.items ?? [];
  const active = items.filter((h) => h.status === "active");
  const paused = items.filter((h) => h.status === "paused");
  const archived = items.filter((h) => h.status === "archived");
  const detail = detailId === null ? null : (items.find((h) => h.id === detailId) ?? null);

  const resumeRow = (h: Habit) => (
    <div key={h.id} className={styles.row}>
      <span className={styles.rowText}>
        <span className={styles.rowTitle}>{h.title}</span>
        <span className={styles.rowMeta}>{cadence(h)}</span>
      </span>
      <button type="button" className={styles.resume} aria-label={copy.habits.resumeLabel(h.title)} disabled={!writable || acting.has(h.id)} onClick={() => void setStatus(h.id, "active")}>
        {copy.habits.resume}
      </button>
    </div>
  );

  let body: ReactNode;
  if (data) {
    body = (
      <>
        {active.length === 0 ? (
          <p className={styles.empty}>{copy.habits.empty}</p>
        ) : (
          <Group heading={copy.habits.active}>
            {active.map((h) => (
              <Row key={h.id} title={h.title} meta={habitMeta(h)} onPress={() => {
                  setDetailId(h.id);
                  setDetailOpen(true);
                }} trailing={<Icon name="chevron" />} />
            ))}
          </Group>
        )}
        {paused.length > 0 && <Group heading={copy.habits.paused}>{paused.map(resumeRow)}</Group>}
        {archived.length > 0 && (
          <section className={styles.archived}>
            <button type="button" className={styles.fold} aria-expanded={archivedOpen} onClick={() => setArchivedOpen((o) => !o)}>
              <span>{copy.habits.archived}</span>
              <span className={`${styles.foldMark} ${archivedOpen ? styles.foldOpen : ""}`} aria-hidden="true">
                <Icon name="chevron" />
              </span>
            </button>
            {archivedOpen && <div className={styles.foldBody}>{archived.map(resumeRow)}</div>}
          </section>
        )}
      </>
    );
  } else if (result === null) {
    body = (
      <Group>
        <Skeleton size="row" />
        <Skeleton size="row" />
      </Group>
    );
  } else if (offline) {
    body = <p className={styles.empty}>{copy.offline.later}</p>;
  } else {
    body = (
      <Group>
        <BlockError code={result.kind === "error" ? result.code : result.kind} onRetry={() => void refresh()} />
      </Group>
    );
  }

  return (
    <main className={`${page.main} ${styles.main}`}>
      <nav className={styles.bar}>
        <Link href="/" className={styles.back}>
          {copy.habits.back}
        </Link>
      </nav>
      <LargeTitle
        title={copy.habits.heading}
        trailing={
          <button type="button" className={styles.add} aria-label={copy.habits.add} disabled={!writable} onClick={() => setAdding(true)}>
            <Icon name="plus" />
          </button>
        }
      />
      {offline && <OfflineNotice savedAt={last?.at ?? null} onRetry={() => void recheck()} />}
      {body}
      {detail && data && (
        <HabitDetail
          key={detail.id}
          open={detailOpen}
          habit={detail}
          readOnly={!writable}
          statusBusy={acting.has(detail.id)}
          reloadToken={reload}
          onClose={() => setDetailOpen(false)}
          onEdit={() => {
            setDetailOpen(false);
            setEditing(detail);
            setEditOpen(true);
          }}
          onStatus={(s) => void setStatus(detail.id, s)}
          onChecked={() => void refresh()}
        />
      )}
      <HabitSheet open={adding} onClose={() => setAdding(false)} onSaved={changed} />
      {editing && <HabitSheet open={editOpen} habit={editing} onClose={() => setEditOpen(false)} onSaved={changed} />}
      {confirm && <ConfirmSheet summary={confirm.summary} busy={confirmBusy} onKeep={() => setConfirm(null)} onChange={() => void confirmArchive()} />}
    </main>
  );
}

// The detail sheet (SP7 6.2): title, area and cadence, the last four weeks, and its three buttons.
function HabitDetail({
  open,
  habit,
  readOnly,
  statusBusy,
  reloadToken,
  onClose,
  onEdit,
  onStatus,
  onChecked,
}: {
  open: boolean;
  habit: Habit;
  readOnly: boolean;
  statusBusy: boolean;
  reloadToken: number;
  onClose(): void;
  onEdit(): void;
  onStatus(s: Status): void;
  onChecked(): void;
}) {
  const { run } = useAction();
  const notAllowed = useNotAllowed(async () => {});
  const [history, setHistory] = useState<HabitHistory | null>(null);
  const [failed, setFailed] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [pending, setPending] = useState<ReadonlySet<string>>(new Set());
  const inFlight = useRef(new Set<string>());
  const seq = useRef(0);

  const load = useCallback(async () => {
    const mine = ++seq.current;
    const r = await apiGet<HabitHistory>(`/habits/${habit.id}?weeks=4`, "HabitHistory");
    if (mine !== seq.current) return; // a newer read already went
    if (r.kind === "ok") {
      setHistory(r.data);
      setFailed(null);
    } else setFailed(r.kind === "error" ? r.code : r.kind);
  }, [habit.id]);

  useEffect(() => {
    if (!open) return; // a closed sheet reads nothing; it reads again when it opens
    void load();
    return () => {
      seq.current++; // an answer after the sheet closed changes nothing
    };
  }, [open, load, reloadToken, attempt]);

  const toggle = async (date: string) => {
    if (!history || inFlight.current.has(date)) return;
    inFlight.current.add(date);
    setPending(new Set(inFlight.current));
    try {
      const was = history.checked_dates.includes(date);
      const out = await run(was ? "uncheck_habit" : "check_habit", { id: habit.id, date });
      if (out === null) return;
      if (out.kind === "applied") {
        // Draw the answer at once, then read the weeks again (and the list's week count).
        setHistory((h) => h && { ...h, checked_dates: was ? h.checked_dates.filter((d) => d !== date) : [...h.checked_dates, date] });
        void load();
        onChecked();
      } else await notAllowed(out);
    } finally {
      inFlight.current.delete(date);
      setPending(new Set(inFlight.current));
    }
  };

  const shown = history?.habit ?? habit;
  const lines = history ? weekLines(history.weeks, history.to) : [];
  const isPaused = shown.status === "paused";

  return (
    <Sheet open={open} onClose={onClose} title={shown.title}>
      <div className={styles.detail}>
        <p className={styles.detailMeta}>{copy.habits.detailMeta(copy.areas[shown.area], cadence(shown))}</p>
        {history ? (
          <HabitGrid from={history.from} today={history.to} checkedDates={history.checked_dates} onToggle={readOnly ? undefined : (d) => void toggle(d)} busy={pending} />
        ) : failed ? (
          <BlockError code={failed} onRetry={() => setAttempt((n) => n + 1)} />
        ) : (
          <Skeleton size="row" />
        )}
        {lines.length > 0 && (
          <ul className={styles.weekLines}>
            {lines.map((l) => (
              <li key={l}>{l}</li>
            ))}
          </ul>
        )}
        <div className={styles.actions}>
          <button type="button" className={styles.action} disabled={readOnly} onClick={onEdit}>
            {copy.habits.edit}
          </button>
          <button type="button" className={styles.action} disabled={readOnly || statusBusy} onClick={() => onStatus(isPaused ? "active" : "paused")}>
            {isPaused ? copy.habits.resume : copy.habits.pause}
          </button>
          <button type="button" className={`${styles.action} ${styles.archive}`} disabled={readOnly || statusBusy} onClick={() => onStatus("archived")}>
            {copy.habits.archive}
          </button>
        </div>
      </div>
    </Sheet>
  );
}
