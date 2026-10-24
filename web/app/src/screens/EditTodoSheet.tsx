import { useId, useRef, useState } from "react";
import { type ActionOutcome, useAction } from "../api/actions";
import type { Todo } from "../api/types.gen";
import { Sheet } from "../components/Sheet";
import { copy } from "../lib/copy";
import styles from "./Todos.module.css";

export type Edit = { kind: "date" | "title"; todo: Todo };

// "날짜 바꾸기" (`move_task`) and "제목 고치기" (`update_task`) from the row menu (spec 5.5.5, accessibility).
export function EditTodoSheet({
  edit,
  onClose,
  onDone,
  guard,
}: {
  edit: Edit | null;
  onClose(): void;
  onDone(): Promise<void>;
  guard: (out: ActionOutcome | null) => Promise<void>;
}) {
  // The last edit stays drawn while the sheet slides out, so it does not leave empty.
  const last = useRef<Edit | null>(edit);
  if (edit) last.current = edit;
  const shown = edit ?? last.current;
  return (
    <Sheet open={edit !== null} onClose={onClose} title={shown ? (shown.kind === "date" ? copy.todos.changeDate : copy.todos.editTitle) : undefined}>
      {shown && <EditForm key={`${shown.kind}:${shown.todo.id}`} edit={shown} onClose={onClose} onDone={onDone} guard={guard} />}
    </Sheet>
  );
}

function EditForm({ edit, onClose, onDone, guard }: { edit: Edit; onClose(): void; onDone(): Promise<void>; guard: (out: ActionOutcome | null) => Promise<void> }) {
  const { run } = useAction();
  const id = useId();
  const isDate = edit.kind === "date";
  const initial = isDate ? (edit.todo.planned_for ?? "") : edit.todo.title;
  const [value, setValue] = useState(initial);
  const [busy, setBusy] = useState(false);
  const lock = useRef(false);
  const clean = isDate ? value : value.trim();
  const ok = clean !== "" && clean !== initial;

  const save = async () => {
    if (!ok || lock.current) return;
    lock.current = true;
    setBusy(true);
    try {
      const out = isDate ? await run("move_task", { id: edit.todo.id, planned_for: clean }) : await run("update_task", { id: edit.todo.id, title: clean });
      if (out === null) return;
      if (out.kind === "applied") await onDone();
      else if (out.kind === "conflict" || out.kind === "needs_confirm") await guard(out);
      else return; // rejected / failed: useAction said why, the sheet stays for another try
      onClose();
    } finally {
      lock.current = false;
      setBusy(false);
    }
  };

  return (
    <form
      className={styles.editForm}
      onSubmit={(e) => {
        e.preventDefault();
        void save();
      }}
    >
      <label className={styles.label} htmlFor={id}>
        {isDate ? copy.todos.dateLabel : copy.todos.titleLabel}
      </label>
      <input id={id} className={styles.input} type={isDate ? "date" : "text"} value={value} onChange={(e) => setValue(e.target.value)} autoComplete="off" />
      <div className={styles.buttons}>
        <button type="button" className={styles.cancel} onClick={onClose}>
          {copy.todos.close}
        </button>
        <button type="submit" className={styles.save} disabled={!ok || busy}>
          {copy.todos.save}
        </button>
      </div>
    </form>
  );
}
