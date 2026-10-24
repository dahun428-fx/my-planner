import type { Habit, TodoRef } from "../api/types.gen";

export type Milestone = { id: number; title: string; date: string; area?: string; sensitive?: boolean };
export type Chapter = { id: number; title: string; start_month: string; end_month: string | null };

/** The fields of a BE TodoRef (6.3) the parts read. An older BE sends no dates (SP6 spec 10.2). */
export type PartTodo = Pick<TodoRef, "id" | "title" | "status"> & Partial<Pick<TodoRef, "planned_for" | "scheduled_at">>;

/** What the BE attaches next to a part's props: the current rows behind the ids (spec 6, R4c). */
export type PartData = { todos?: PartTodo[]; milestones?: Milestone[]; chapters?: Chapter[]; habits?: Habit[] };

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
};

export type PartProps<P> = { props: P; data?: PartData; ctx: PartContext };
