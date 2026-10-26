import type { Habit, TodoRef } from "../api/types.gen";
import type { OpenScreen } from "./primitives/types";

export type Milestone = { id: number; title: string; date: string; area?: string; sensitive?: boolean };
export type Chapter = { id: number; title: string; start_month: string; end_month: string | null };

/** The fields of a BE TodoRef (6.3) the parts read. An older BE sends no dates (SP6 spec 10.2). */
export type PartTodo = Pick<TodoRef, "id" | "title" | "status"> & Partial<Pick<TodoRef, "planned_for" | "scheduled_at">>;

/** SP6 6.3: what the secretary did to one to-do in this answer. */
export type ResultChange = "added" | "moved" | "completed" | "reopened" | "dropped" | "updated" | "confirmed";
/** A to-do's fields before or after the change (6.3): a field the earliest activity did not keep is null. */
export type TodoSnap = { status: string | null; planned_for: string | null; scheduled_at: string | null; title: string | null };
export type ResultItem = { todo: PartTodo; change: ResultChange; before: TodoSnap | null; after: TodoSnap; activity_ids: number[]; undo_id: number | null };
/** One day of `ui_period_list` (6.4). */
export type DayTodos = { date: string; weekday: string; is_today: boolean; todos: PartTodo[] };
export type OutsideItem = { reason: "moved" | "dropped" | "no_date"; todo: PartTodo };

/**
 * What the BE attaches next to a part's props: the current rows behind the ids (spec 6, R4c), and
 * for the SP6 chat cards the logical today and what each card reads (SP6 10.2).
 */
export type PartData = {
  todos?: PartTodo[];
  milestones?: Milestone[];
  chapters?: Chapter[];
  habits?: Habit[];
  today?: string;
  /** ui_date_choice: null once the to-do is gone. */
  todo?: PartTodo | null;
  items?: ResultItem[];
  start?: string;
  end?: string;
  days?: DayTodos[];
  outside?: OutsideItem[];
};

export type PartContext = {
  where: "chat" | "today" | "checkin" | "activity";
  /** Offline or blocked: buttons are disabled. */
  readOnly: boolean;
  /** The screen reads again after a write (parts never change state on their own). */
  onAfterAction(): void;
  /** A copy kept on the device (4.6) after a reload: the rows behind it may have changed since. */
  restored?: boolean;
  /** `ui_choice`: the chosen label goes to the chat as a new user message. */
  onChoose?(label: string): void;
  /** SP6 8: open an app screen (the chat sheet moves there and closes). Without it no `open` button is drawn. */
  onOpen?(screen: OpenScreen): void;
  /** SP9 9.8 `ui_events`: open an app address the app made (`/schedule/?date=`); the chat sheet moves there and closes. */
  onOpenPath?(path: string): void;
};

export type PartProps<P> = { props: P; data?: PartData; ctx: PartContext };
