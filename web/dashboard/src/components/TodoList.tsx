import type { Todo } from "../api/types.gen";
import { formatDay, formatKst } from "../lib/time";

/**
 * Read-only to-do lines in the shapes of the Telegram `/today`, `/week` text (spec 13.3): no check box.
 * - `ranked`: "1. 제목" (priorities, in the API's order)
 * - `scheduled`: "14:00 제목"
 * - `open`: "제목", plus "(M/D)" when it was planned before `today` and is still open
 * - `day`: "14:00 제목" when it has a time, else "제목" (a day of the week)
 */
export type TodoListKind = "ranked" | "scheduled" | "open" | "day";

export function TodoList({ todos, kind, today }: { todos: Todo[]; kind: TodoListKind; today: string }) {
  const Tag = kind === "ranked" ? "ol" : "ul";
  return (
    <Tag className="todos" data-kind={kind}>
      {todos.map((t, i) => (
        <li key={t.id} className="todo" data-title={t.title}>
          {kind === "ranked" && <span className="todo-lead num">{i + 1}.</span>}
          {(kind === "scheduled" || kind === "day") && t.scheduled_at && (
            <span className="todo-lead num">{formatKst(t.scheduled_at, "HH:mm")}</span>
          )}
          <span className="todo-title">
            {t.title}
            {kind === "open" && t.planned_for !== null && t.planned_for < today && (
              <span className="todo-since num"> ({formatDay(t.planned_for)})</span>
            )}
          </span>
        </li>
      ))}
    </Tag>
  );
}
