import type { BlockElement, InnerElement } from "../primitives/types";

// SP6 spec 7.2: the ui_block rules the catalog's JSON Schema cannot say (B1, B4~B8). The props
// have already passed that schema (B2, B3, lengths), so only shapes it allows are seen here. B9
// (8KB) is the BE's alone: a part it sent is already within it.

const MAX_PARTS = 12;
const MAX_TODO_ROWS = 2;
const CONTENT = new Set(["text", "stat", "progress", "todo_rows", "tags", "bullets"]);

const inner = (el: BlockElement): InnerElement[] => (el.type === "group" ? (el.children as InnerElement[]) : []);

/** B6: no divider first, last, or next to another one. */
function dividersOk(list: readonly { type: string }[]): boolean {
  return list.every((el, i) => el.type !== "divider" || (i > 0 && i < list.length - 1 && list[i - 1].type !== "divider"));
}

export function checkBlock(props: unknown): boolean {
  const top = (props as { children?: unknown } | null)?.children;
  if (!Array.isArray(top)) return false;
  const children = top as BlockElement[];
  const all: { type: string }[] = children.flatMap((el) => [el, ...inner(el)]);

  if (all.length > MAX_PARTS) return false; // B1: a group counts 1 + its children
  const buttons = children.filter((el) => el.type === "buttons");
  if (all.filter((el) => el.type === "buttons").length > 1) return false; // B4: one…
  if (buttons.length === 1 && children[children.length - 1] !== buttons[0]) return false; // …and last
  const rows = all.filter((el): el is Extract<InnerElement, { type: "todo_rows" }> => el.type === "todo_rows");
  if (rows.length > MAX_TODO_ROWS) return false; // B5
  if (!dividersOk(children) || !children.every((el) => dividersOk(inner(el)))) return false; // B6
  if (!all.some((el) => CONTENT.has(el.type))) return false; // B7

  const ids = new Set(rows.flatMap((el) => el.task_ids));
  return buttons.every((b) => b.type !== "buttons" || b.items.every((item) => item.do.kind !== "complete" || ids.has(item.do.task_id))); // B8
}
