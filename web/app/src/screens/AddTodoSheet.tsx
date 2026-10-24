import { useId, useRef, useState } from "react";
import { useAction } from "../api/actions";
import type { Todo } from "../api/types.gen";
import { Segmented } from "../components/Segmented";
import { Sheet } from "../components/Sheet";
import { useToast } from "../components/Toast";
import { copy } from "../lib/copy";
import { addDays, scheduledAtOf } from "../lib/time";
import styles from "./AddTodoSheet.module.css";

type Area = Todo["areas"][number];
// Same order as the BE's enum (types.gen.ts), so what is sent does not depend on the order of the taps.
const AREAS = Object.keys(copy.areas) as Area[];
type DateMode = "today" | "tomorrow" | "pick" | "none";

export interface AddTodoSheetProps {
  open: boolean;
  onClose(): void;
  /** The BE's logical today (/today.date): "오늘" is this day, "내일" the next. */
  defaultDate: string;
  /** `/today.day_boundary`: a time before it belongs to the next calendar day of the chosen date. */
  dayBoundary?: string;
  /** Called after the to-do was added, so the screen can read again. */
  onAdded?(): void;
}

// Spec 5.5.5 add sheet. Priorities are the secretary's job in v1 (set_priorities), so there is no field for them.
export function AddTodoSheet({ open, onClose, defaultDate, dayBoundary, onAdded }: AddTodoSheetProps) {
  return (
    <Sheet open={open} onClose={onClose} title={copy.todos.addTitle}>
      <AddForm onClose={onClose} defaultDate={defaultDate} dayBoundary={dayBoundary} onAdded={onAdded} />
    </Sheet>
  );
}

function AddForm({ onClose, defaultDate, dayBoundary, onAdded }: Omit<AddTodoSheetProps, "open">) {
  const { run } = useAction();
  const toast = useToast();
  const ids = { title: useId(), time: useId(), note: useId(), date: useId() };
  const [title, setTitle] = useState("");
  const [areas, setAreas] = useState<ReadonlySet<Area>>(new Set());
  const [mode, setMode] = useState<DateMode>("today");
  const [picked, setPicked] = useState(defaultDate);
  const [time, setTime] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const lock = useRef(false);

  const planned = mode === "today" ? defaultDate : mode === "tomorrow" ? addDays(defaultDate, 1) : mode === "pick" ? picked || null : null;
  const trimmed = title.trim();

  const toggleArea = (a: Area) =>
    setAreas((s) => {
      const next = new Set(s);
      if (!next.delete(a)) next.add(a);
      return next;
    });

  const submit = async () => {
    if (trimmed === "" || lock.current) return;
    lock.current = true;
    setBusy(true);
    try {
      const args: Record<string, unknown> = { title: trimmed, areas: AREAS.filter((a) => areas.has(a)) };
      if (planned) {
        args.planned_for = planned;
        if (time) args.scheduled_at = scheduledAtOf(planned, time, dayBoundary);
      }
      if (note.trim()) args.note = note.trim();
      const out = await run("add_task", args);
      if (out === null) return;
      if (out.kind === "applied") {
        onAdded?.();
        onClose();
      } else if (out.kind === "conflict" || out.kind === "needs_confirm") {
        toast.show({ text: copy.actions.failed });
      }
    } finally {
      lock.current = false;
      setBusy(false);
    }
  };

  return (
    <form
      className={styles.form}
      onSubmit={(e) => {
        e.preventDefault();
        void submit();
      }}
    >
      <div className={styles.field}>
        <label className={styles.label} htmlFor={ids.title}>
          {copy.todos.titleLabel}
        </label>
        <input id={ids.title} className={styles.input} type="text" value={title} onChange={(e) => setTitle(e.target.value)} autoComplete="off" />
      </div>
      <div className={styles.field}>
        <span className={styles.label}>{copy.todos.areasLabel}</span>
        <div className={styles.pills}>
          {AREAS.map((a) => (
            <button
              key={a}
              type="button"
              className={`${styles.pill} ${areas.has(a) ? styles.picked : ""}`}
              aria-pressed={areas.has(a)}
              onClick={() => toggleArea(a)}
            >
              {copy.areas[a]}
            </button>
          ))}
        </div>
      </div>
      <div className={styles.field}>
        <Segmented<DateMode>
          ariaLabel={copy.todos.dateGroup}
          value={mode}
          onChange={setMode}
          options={[
            { value: "today", label: copy.todos.dateToday },
            { value: "tomorrow", label: copy.todos.dateTomorrow },
            { value: "pick", label: copy.todos.datePick },
            { value: "none", label: copy.todos.dateNone },
          ]}
        />
        {mode === "pick" && (
          <>
            <label className={styles.label} htmlFor={ids.date}>
              {copy.todos.dateLabel}
            </label>
            <input id={ids.date} className={styles.input} type="date" value={picked} onChange={(e) => setPicked(e.target.value)} />
          </>
        )}
      </div>
      <div className={styles.field}>
        <label className={styles.label} htmlFor={ids.time}>
          {copy.todos.timeLabel}
        </label>
        <input id={ids.time} className={styles.input} type="time" value={time} disabled={!planned} onChange={(e) => setTime(e.target.value)} />
      </div>
      <div className={styles.field}>
        <label className={styles.label} htmlFor={ids.note}>
          {copy.todos.noteLabel}
        </label>
        <textarea id={ids.note} className={`${styles.input} ${styles.note}`} value={note} onChange={(e) => setNote(e.target.value)} />
      </div>
      <div className={styles.buttons}>
        <button type="button" className={styles.cancel} onClick={onClose}>
          {copy.todos.close}
        </button>
        <button type="submit" className={styles.submit} disabled={trimmed === "" || busy}>
          {copy.todos.addSubmit}
        </button>
      </div>
    </form>
  );
}
