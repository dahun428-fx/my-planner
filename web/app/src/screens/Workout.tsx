import Link from "next/link";
import { type ReactNode, useEffect, useRef, useState } from "react";
import { useAction } from "../api/actions";
import type { BodyNoteOut, Workout as WorkoutData, WorkoutLogItemOut, WorkoutLogOut, WorkoutPlanItem, WorkoutPlanSession } from "../api/types.gen";
import { useChatSheet } from "../chat/sheetContext";
import { BlockError } from "../components/BlockError";
import { ConfirmSheet } from "../components/ConfirmSheet";
import { Group } from "../components/Group";
import { Icon } from "../components/icons";
import { LargeTitle } from "../components/LargeTitle";
import { OfflineNotice } from "../components/OfflineNotice";
import { Skeleton } from "../components/Skeleton";
import { SwipeRow } from "../components/SwipeRow";
import { useToast } from "../components/Toast";
import { useConnection, useWritable } from "../lib/ConnectionProvider";
import { copy } from "../lib/copy";
import { useSnapshotted } from "../lib/snapshot";
import page from "../styles/page.module.css";
import { useNotAllowed } from "./todoActions";
import styles from "./Workout.module.css";

/** "10-30" out of "2026-10-30" (the confirm question's own form, spec 8장). */
const monthDay = (date: string) => date.slice(5);

const planLine = (i: WorkoutPlanItem) =>
  [
    i.sets !== null && i.reps !== null ? `${i.sets}×${i.reps}` : i.sets !== null ? copy.workout.sets(i.sets) : i.reps,
    i.weight_kg !== null ? copy.workout.kg(i.weight_kg) : null,
    i.minutes !== null ? copy.workout.minutes(i.minutes) : null,
    i.note,
  ]
    .filter((p): p is string => !!p)
    .join(" · ");

const logLine = (i: WorkoutLogItemOut) =>
  [
    i.sets !== null && i.reps !== null ? `${i.sets}×${i.reps}` : i.sets !== null ? copy.workout.sets(i.sets) : i.reps !== null ? String(i.reps) : null,
    i.weight_kg !== null ? copy.workout.kg(i.weight_kg) : null,
    i.minutes !== null ? copy.workout.minutes(i.minutes) : null,
    i.distance_km !== null ? copy.workout.km(i.distance_km) : null,
  ]
    .filter((p): p is string => !!p)
    .join(" · ");

interface PendingConfirm {
  id: number;
  token: string;
  summary: string;
}

// SP12 11.2: the plan, the last 28 days of records and the body notes the mate keeps. A list, never a
// calendar or a count of days (ADR 0006). Off the tabs, "‹ 더보기" back. Offline the last answer shows,
// read-only (ADR 0009).
export function Workout() {
  const { recheck } = useConnection();
  const { view, refresh } = useSnapshotted<WorkoutData>("workout", "/workout", "Workout");
  const { run } = useAction();
  const toast = useToast();
  const chat = useChatSheet();
  const notAllowed = useNotAllowed(refresh);

  useEffect(() => toast.onUndone(() => void refresh()), [toast, refresh]);
  // The mate may have changed the plan, a record or a note while the sheet was open.
  useEffect(() => chat.onClosed(() => void refresh()), [chat, refresh]);

  const data = view.kind === "live" || view.kind === "snapshot" ? view.data : null;
  const writable = useWritable(view.kind === "live");
  const canChat = useWritable(view.kind === "live", { strict: true });
  const offline = view.kind === "snapshot" || view.kind === "none";

  const [open, setOpen] = useState<ReadonlySet<string>>(new Set());
  const toggle = (key: string) =>
    setOpen((s) => {
      const next = new Set(s);
      if (!next.delete(key)) next.add(key);
      return next;
    });

  const [confirm, setConfirm] = useState<PendingConfirm | null>(null);
  const [confirmBusy, setConfirmBusy] = useState(false);
  const confirmLock = useRef(false);

  const deleteLog = async (id: number) => {
    const out = await run("delete_workout_log", { id });
    if (out?.kind === "applied") await refresh();
    else if (out?.kind === "needs_confirm") setConfirm({ id, token: out.confirmToken, summary: out.summary });
    else await notAllowed(out);
  };

  const confirmDelete = async () => {
    if (!confirm || confirmLock.current) return;
    confirmLock.current = true;
    setConfirmBusy(true);
    try {
      const out = await run("delete_workout_log", { id: confirm.id }, { confirmToken: confirm.token });
      if (out === null) return;
      if (out.kind === "needs_confirm") {
        setConfirm({ id: confirm.id, token: out.confirmToken, summary: out.summary });
        return;
      }
      if (out.kind === "conflict") toast.show({ text: copy.todos.confirmExpired });
      setConfirm(null);
      if (out.kind === "applied") await refresh();
    } finally {
      confirmLock.current = false;
      setConfirmBusy(false);
    }
  };

  const dropNote = async (id: number) => {
    const out = await run("drop_body_note", { id });
    if (out?.kind === "applied") await refresh();
    else await notAllowed(out);
  };

  const expandRow = (key: string, label: string, title: string, meta: string, lines: ReactNode) => {
    const isOpen = open.has(key);
    return (
      <>
        <button type="button" className={styles.row} aria-expanded={isOpen} aria-label={copy.workout.expandLabel(label)} onClick={() => toggle(key)}>
          <span className={styles.text}>
            <span className={styles.title}>{title}</span>
            {meta && <span className={styles.meta}>{meta}</span>}
          </span>
          <span className={`${styles.mark} ${isOpen ? styles.markOpen : ""}`} aria-hidden="true">
            <Icon name="chevron" />
          </span>
        </button>
        {isOpen && lines}
      </>
    );
  };

  const sessionRow = (s: WorkoutPlanSession) => {
    const meta = [s.weekdays && s.weekdays.length > 0 ? s.weekdays.map((d) => copy.workout.weekdays[d]).join("·") : "", copy.workout.sessionItems(s.items.length)].filter(Boolean).join(" · ");
    return (
      <div key={s.id}>
        {expandRow(
          `s${s.id}`,
          s.label,
          s.label,
          meta,
          <ul className={styles.lines}>
            {s.items.map((i, n) => (
              <li key={n} className={styles.line}>
                <span>{i.name}</span>
                {planLine(i) && <span className={styles.lineMeta}>{planLine(i)}</span>}
              </li>
            ))}
          </ul>,
        )}
      </div>
    );
  };

  const logRow = (l: WorkoutLogOut) => (
    <SwipeRow
      key={l.id}
      disabled={!writable}
      menuTitle={l.title}
      moreLabel={copy.today.moreActions(l.title)}
      actions={[{ label: copy.workout.delete, tone: "negative", onPress: () => void deleteLog(l.id) }]}
    >
      {expandRow(
        `l${l.id}`,
        `${l.title} ${monthDay(l.date)}`,
        l.title,
        `${monthDay(l.date)} · ${copy.workout.sessionItems(l.items.length)}`,
        <ul className={styles.lines}>
          {l.items.map((i, n) => (
            <li key={n} className={styles.line}>
              <span>{i.name}</span>
              {logLine(i) && <span className={styles.lineMeta}>{logLine(i)}</span>}
            </li>
          ))}
          {l.note && <li className={styles.line}>{l.note}</li>}
        </ul>,
      )}
    </SwipeRow>
  );

  const noteRow = (n: BodyNoteOut) => (
    <SwipeRow
      key={n.id}
      disabled={!writable}
      menuTitle={n.text}
      moreLabel={copy.today.moreActions(n.text)}
      actions={[{ label: copy.workout.delete, tone: "negative", onPress: () => void dropNote(n.id) }]}
    >
      <div className={styles.note}>
        <span className={styles.meta}>{copy.workout.noteKinds[n.kind]}</span>
        <span className={styles.title}>{n.text}</span>
      </div>
    </SwipeRow>
  );

  let body: ReactNode;
  if (data) {
    body = (
      <>
        {data.plan ? (
          <Group paper heading={copy.workout.planHeading}>
            <p className={styles.planTitle}>{data.plan.title}</p>
            {data.plan.sessions.map(sessionRow)}
          </Group>
        ) : (
          <>
            <Group paper heading={copy.workout.planHeading}>
              <p className={styles.empty}>{copy.workout.planEmpty}</p>
            </Group>
            <button type="button" className={styles.talk} disabled={!canChat} onClick={() => chat.open({ agent: "mate" })}>
              {copy.workout.talk}
            </button>
          </>
        )}
        <Group paper heading={copy.workout.logsHeading}>
          {data.logs.length === 0 ? <p className={styles.empty}>{copy.workout.logsEmpty}</p> : data.logs.map(logRow)}
        </Group>
        {data.notes.length > 0 && (
          <Group paper heading={copy.workout.notesHeading}>
            <p className={styles.hint}>{copy.workout.notesHint}</p>
            {data.notes.map(noteRow)}
          </Group>
        )}
      </>
    );
  } else if (view.kind === "loading") {
    body = (
      <Group paper>
        {[0, 1, 2].map((i) => (
          <Skeleton key={i} size="row" />
        ))}
      </Group>
    );
  } else if (view.kind === "blocked") {
    body = (
      <Group paper>
        <BlockError code={view.result.kind === "error" ? view.result.code : view.result.kind} onRetry={() => void refresh()} />
      </Group>
    );
  } else {
    body = null; // offline with nothing saved: the notice says so
  }

  return (
    <main className={`${page.main} ${styles.main}`}>
      <nav className={styles.bar}>
        <Link href="/more/" className={styles.back}>
          {copy.workout.back}
        </Link>
      </nav>
      <LargeTitle title={copy.workout.title} />
      {offline && <OfflineNotice savedAt={view.kind === "snapshot" ? view.savedAt : null} onRetry={() => void recheck()} />}
      {body}
      {confirm && (
        <ConfirmSheet
          summary={confirm.summary}
          busy={confirmBusy}
          keepLabel={copy.workout.keep}
          changeLabel={copy.workout.delete}
          onKeep={() => setConfirm(null)}
          onChange={() => void confirmDelete()}
        />
      )}
    </main>
  );
}
