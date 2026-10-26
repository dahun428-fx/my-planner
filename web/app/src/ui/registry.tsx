import type { ComponentType } from "react";
import { useCatalog } from "./CatalogProvider";
import { AreaScores } from "./components/AreaScores";
import { ChapterDraft } from "./components/ChapterDraft";
import { Choice } from "./components/Choice";
import { ConditionPicker } from "./components/ConditionPicker";
import { Confirm } from "./components/Confirm";
import { HabitCheck } from "./components/HabitList";
import { LadderPicker } from "./components/LadderPicker";
import { MilestoneDraft } from "./components/MilestoneDraft";
import { SummaryCard } from "./components/SummaryCard";
import { TodoDraft } from "./components/TodoDraft";
import { TodoList } from "./components/TodoList";
import { UnknownPart } from "./components/UnknownPart";
import type { PartContext, PartData, PartProps } from "./types";

export type { PartContext, PartData };

// eslint-disable-next-line @typescript-eslint/no-explicit-any
const registry: Record<string, ComponentType<PartProps<any>>> = {
  ui_todo_list: TodoList,
  ui_choice: Choice,
  ui_summary_card: SummaryCard,
  ui_habit_check: HabitCheck,
  ui_todo_draft: TodoDraft,
  ui_condition_picker: ConditionPicker,
  ui_ladder_picker: LadderPicker,
  ui_area_scores: AreaScores,
  ui_milestone_draft: MilestoneDraft,
  ui_chapter_draft: ChapterDraft,
  ui_confirm: Confirm,
};

/**
 * SP6 11.2: the chat bundle adds its cards here when it loads (`registerChatParts`), so the first
 * screen's bundle carries none of them. `source` names who registered, for the duplicate error.
 */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export function registerParts(entries: Record<string, ComponentType<PartProps<any>>>, source = "registerParts"): void {
  for (const [name, part] of Object.entries(entries)) {
    if (Object.hasOwn(registry, name)) {
      if (process.env.NODE_ENV !== "production") throw new Error(`${source}: ${name} is already registered`);
      continue;
    }
    registry[name] = part;
  }
}

/** The names drawn now: the first screen's, plus the chat bundle's once it has loaded. */
export function registryNames(): string[] {
  return Object.keys(registry);
}

// Spec 6: a part is drawn only if its name is known here AND its props pass the catalog's schema.
// Nothing here depends on `ctx.where`: chat, Today and check-in draw the same thing.
export function UiPart({ name, props, data, ctx }: { name: string; props: unknown; data?: PartData; ctx: PartContext }) {
  const { check, settled } = useCatalog();
  if (!settled) return null; // the catalog is still being read
  const Part = Object.hasOwn(registry, name) ? registry[name] : undefined;
  if (!Part || !check(name, props)) return <UnknownPart props={props} />;
  return <Part props={props} data={data} ctx={ctx} />;
}
