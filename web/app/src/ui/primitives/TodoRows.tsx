import { copy } from "../../lib/copy";
import type { PartContext, PartTodo } from "../types";
import { CheckRow } from "./CheckRow";
import { rowMeta } from "./dates";
import styles from "./primitives.module.css";

/**
 * `todo_rows` (5.3.5): rows come only from what the BE attached (`todos`), in the order of `ids`.
 * Without `todos` (an older BE) it is one "할 일 n개" line; with none left (all soft-deleted),
 * "보여 줄 할 일이 없어요". An open row checks; a done one is struck and filled; a dropped one is
 * struck with no mark. `completed` holds the ids the card has completed since it was drawn. A
 * restored or read-only card checks nothing.
 */
export function TodoRows({
  ids,
  todos,
  today,
  checkable,
  completed,
  ctx,
  onComplete,
}: {
  ids: number[];
  todos?: PartTodo[];
  today?: string;
  checkable: boolean;
  completed?: ReadonlySet<number>;
  ctx: PartContext;
  onComplete(id: number): void;
}) {
  if (!todos) return <p className={styles.text}>{copy.parts.todoCount(ids.length)}</p>;
  const byId = new Map(todos.map((t) => [t.id, t]));
  const rows = ids.flatMap((id) => byId.get(id) ?? []);
  if (rows.length === 0) return <p className={styles.text}>{copy.parts.noTodos}</p>;
  const off = ctx.readOnly || ctx.restored === true;
  return (
    <ul className={styles.checkRows} data-read-only={off ? "" : undefined}>
      {rows.map((t) => {
        const done = t.status === "done" || completed?.has(t.id) === true;
        const dropped = t.status === "dropped";
        return (
          <CheckRow
            key={t.id}
            title={t.title}
            meta={rowMeta(t, today)}
            checked={done}
            struck={done || dropped}
            disabled={off || done}
            mark={dropped ? "none" : !checkable && !done ? "dot" : "circle"}
            onToggle={() => onComplete(t.id)}
          />
        );
      })}
    </ul>
  );
}
