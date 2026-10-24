import type { Todo } from "../api/types.gen";
import { copy } from "../lib/copy";
import { formatKst } from "../lib/time";
import { SwipeRow } from "./SwipeRow";
import styles from "./TodoRow.module.css";

export interface TodoRowProps {
  todo: Todo;
  /** Offline or blocked: the check box becomes a drawn empty circle and the row cannot be swiped. */
  readOnly: boolean;
  onToggle(): void;
  onTomorrow(): void;
  onDrop(): void;
  onLongPress?(): void;
}

// One to-do on the Today screen (spec 5.5.1 block 6). A done row is grey with a strike-through and
// the time it was done, never a count. The optimistic flip is the caller's: it passes a todo that
// already looks done and takes it back if the write fails.
export function TodoRow({ todo, readOnly, onToggle, onTomorrow, onDrop, onLongPress }: TodoRowProps) {
  const done = todo.status === "done";
  const meta: string[] = [];
  if (todo.priority) meta.push(copy.today.priority);
  if (done && todo.completed_at) meta.push(copy.today.completedAt(formatKst(todo.completed_at, "HH:mm")));
  const actions = done
    ? []
    : [
        { label: copy.todos.tomorrow, tone: "neutral" as const, onPress: onTomorrow },
        { label: copy.todos.drop, tone: "negative" as const, onPress: onDrop },
      ];
  return (
    <SwipeRow actions={actions} disabled={readOnly} menuTitle={todo.title} onLongPress={onLongPress} moreLabel={copy.today.moreActions(todo.title)}>
      <div className={styles.row}>
        {readOnly ? (
          <span className={styles.check} aria-hidden="true">
            <span className={`${styles.circle} ${done ? styles.filled : ""}`} />
          </span>
        ) : (
          <button
            type="button"
            role="checkbox"
            aria-checked={done}
            aria-label={done ? copy.today.doneLabel(todo.title) : copy.today.checkLabel(todo.title)}
            className={styles.check}
            onClick={onToggle}
          >
            <span className={`${styles.circle} ${done ? styles.filled : ""}`} />
          </button>
        )}
        <span className={styles.text}>
          <span className={`${styles.title} ${done ? styles.done : ""}`}>{todo.title}</span>
          {meta.length > 0 && <span className={styles.meta}>{meta.join(" · ")}</span>}
        </span>
      </div>
    </SwipeRow>
  );
}
