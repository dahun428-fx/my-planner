import { useState } from "react";
import { copy } from "../../lib/copy";
import type { PartProps } from "../types";
import { usePartAction } from "../usePartAction";
import { CheckRow, Part } from "./Part";
import styles from "./parts.module.css";

// ui_todo_draft: drafts are checked by default; "N개 확정" confirms the checked ones, "고른 것 빼기"
// drops them one by one.
export function TodoDraft({ props, data, ctx }: PartProps<{ task_ids: number[] }>) {
  const act = usePartAction();
  const [checked, setChecked] = useState<ReadonlySet<number>>(new Set(props.task_ids));
  const [finished, setFinished] = useState(false);
  const todos = data?.todos;
  const ids = (todos ? todos.map((t) => t.id) : props.task_ids).filter((id) => checked.has(id));
  const off = ctx.readOnly || finished;

  const toggle = (id: number) =>
    setChecked((c) => {
      const next = new Set(c);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const confirm = async () => {
    const out = await act("confirm_tasks", { ids });
    if (out?.kind === "applied") {
      setFinished(true);
      ctx.onAfterAction();
    }
  };
  const drop = async () => {
    let all = true;
    for (const id of ids) {
      const out = await act("drop_task", { id });
      if (out?.kind !== "applied") {
        all = false;
        break;
      }
    }
    if (all) setFinished(true);
    ctx.onAfterAction();
  };

  return (
    <Part title={copy.parts.draftHeading} variant="outlined" readOnly={ctx.readOnly}>
      <p className={styles.hint}>{copy.parts.draftHint}</p>
      {todos ? (
        <ul className={styles.rows}>
          {todos.map((t) => (
            <CheckRow key={t.id} title={t.title} checked={checked.has(t.id)} disabled={off} onToggle={() => toggle(t.id)} />
          ))}
        </ul>
      ) : (
        <p className={styles.text}>{copy.parts.todoCount(props.task_ids.length)}</p>
      )}
      {todos && (
        <div className={styles.buttons}>
          <button type="button" className={styles.button} disabled={off || ids.length === 0} onClick={() => void drop()}>
            {copy.parts.dropChecked}
          </button>
          <button type="button" className={`${styles.button} ${styles.primary}`} disabled={off || ids.length === 0} onClick={() => void confirm()}>
            {copy.parts.confirmCount(ids.length)}
          </button>
        </div>
      )}
    </Part>
  );
}
