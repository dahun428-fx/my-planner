import type { Todo } from "../api/types.gen";

export type Milestone = { id: number; title: string; date: string; area?: string; sensitive?: boolean };
export type Chapter = { id: number; title: string; start_month: string; end_month: string | null };

/** What the BE attaches next to a part's props: the current rows behind the ids (spec 6, R4c). */
export type PartData = { todos?: Todo[]; milestones?: Milestone[]; chapters?: Chapter[] };

export type PartContext = {
  where: "chat" | "today" | "checkin";
  /** Offline or blocked: buttons are disabled. */
  readOnly: boolean;
  /** The screen reads again after a write (parts never change state on their own). */
  onAfterAction(): void;
  /** `ui_choice`: the chosen label goes to the chat as a new user message. */
  onChoose?(label: string): void;
};

export type PartProps<P> = { props: P; data?: PartData; ctx: PartContext };
