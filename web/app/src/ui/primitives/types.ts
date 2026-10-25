import type { Todo } from "../../api/types.gen";

// The ten parts of SP6 spec 5 as the app reads them: the same names as the BE catalog models
// (`tools/ui.py`). The catalog's JSON Schema has already checked every one of them (lengths,
// counts, B2 and B3) before a component sees it, so nothing here is checked again.

export type AreaKey = Todo["areas"][number];

export type Delta = { text: string; trend: "up" | "down" | "same" };

export type HeadingEl = { type: "heading"; text: string };
export type TextEl = { type: "text"; md: string };
/** `delta` is `null` when the BE writes the default out. */
export type StatEl = { type: "stat"; label: string; value: string; delta?: Delta | null };
export type ProgressEl = { type: "progress"; label: string; value: number; max: number };
/** `checkable` defaults to true (gap 3). */
export type TodoRowsEl = { type: "todo_rows"; task_ids: number[]; checkable?: boolean };
export type Tag = { text: string } | { area: AreaKey };
export type TagsEl = { type: "tags"; items: Tag[] };
export type BulletsEl = { type: "bullets"; items: string[] };

export type OpenScreen = "today" | "todos_day" | "todos_week" | "todos_month" | "activity" | "settings";
/** Spec 8: the three things a `buttons` part may do. Undo and confirm live on finished cards only. */
export type ButtonDo = { kind: "send" } | { kind: "open"; screen: OpenScreen } | { kind: "complete"; task_id: number };
export type ButtonItem = { label: string; do: ButtonDo };
export type ButtonsEl = { type: "buttons"; items: ButtonItem[] };
export type DividerEl = { type: "divider" };

export type RowGroup = { type: "group"; layout: "row"; children: (StatEl | ProgressEl)[] };
/** Inside a `stack`: every part but `group` and `buttons` (B2, B3). */
export type InnerElement = HeadingEl | TextEl | StatEl | ProgressEl | TodoRowsEl | TagsEl | BulletsEl | DividerEl;
export type StackGroup = { type: "group"; layout: "stack"; children: InnerElement[] };

export type BlockElement = InnerElement | ButtonsEl | RowGroup | StackGroup;
