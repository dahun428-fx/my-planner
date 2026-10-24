import { useState } from "react";
import { copy } from "../../lib/copy";
import type { PartProps } from "../types";
import { usePartAction } from "../usePartAction";
import { CheckRow } from "../primitives/CheckRow";
import { Part } from "./Part";
import styles from "./parts.module.css";

const FOLD_AT = 6;

// ui_todo_list: a title and up to 30 to-dos as CheckRows (SP6 6.1); checking one completes it.
export function TodoList({ props, data, ctx }: PartProps<{ title: string; task_ids: number[] }>) {
  const act = usePartAction();
  const [done, setDone] = useState<ReadonlySet<number>>(new Set());
  const [open, setOpen] = useState(false);
  const todos = data?.todos;

  if (!todos) {
    return (
      <Part title={props.title}>
        <p className={styles.text}>{copy.parts.todoCount(props.task_ids.length)}</p>
      </Part>
    );
  }

  const folded = todos.length > FOLD_AT && !open;
  const shown = folded ? todos.slice(0, FOLD_AT) : todos;
  const check = async (id: number) => {
    const out = await act("complete_task", { id });
    if (out?.kind === "applied") {
      setDone((d) => new Set(d).add(id));
      ctx.onAfterAction();
    }
  };
  return (
    <Part title={props.title} readOnly={ctx.readOnly} restored={ctx.restored}>
      <ul className={styles.rows}>
        {shown.map((t) => {
          const isDone = t.status === "done" || done.has(t.id);
          return <CheckRow key={t.id} title={t.title} checked={isDone} struck={isDone} disabled={ctx.readOnly || isDone} onToggle={() => void check(t.id)} />;
        })}
      </ul>
      {todos.length > FOLD_AT && (
        <button type="button" className={styles.more} aria-expanded={open} onClick={() => setOpen((o) => !o)}>
          {open ? copy.parts.less : copy.parts.more(todos.length - FOLD_AT)}
        </button>
      )}
    </Part>
  );
}
