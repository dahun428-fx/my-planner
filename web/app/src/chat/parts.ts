import type { UIMessage } from "ai";
import type { PartData } from "../ui/types";

/** What a message shows, in order (spec F4). */
export type ViewPart =
  | { kind: "text"; text: string }
  | { kind: "ui"; toolCallId: string; name: string; props: unknown; data?: PartData }
  | { kind: "activity"; confirmation: string | null; undoIds: number[] };

type AnyPart = UIMessage["parts"][number];
type ToolLike = { toolCallId: string; state: string; input?: unknown; output?: unknown };

// A part has its whole input from `input-available` on (the later states keep it).
const READY = new Set(["input-available", "output-available", "output-error"]);

const isObj = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null && !Array.isArray(v);

function uiPart(name: string, p: ToolLike): ViewPart | null {
  if (!name.startsWith("ui_") || !READY.has(p.state)) return null;
  const out: ViewPart = { kind: "ui", toolCallId: p.toolCallId, name, props: p.input };
  // R4c: the BE puts the rows behind the ids next to the props as {ok: true, data}.
  if (p.state === "output-available" && isObj(p.output) && p.output.ok === true && isObj(p.output.data)) {
    out.data = p.output.data as PartData;
  }
  return out;
}

function activityPart(data: unknown): ViewPart {
  const d = isObj(data) ? data : {};
  const undoIds = Array.isArray(d.undo_ids) ? d.undo_ids.filter((n): n is number => typeof n === "number") : [];
  // Before R4b there is no confirmation: undo still works.
  return { kind: "activity", confirmation: typeof d.confirmation === "string" && d.confirmation !== "" ? d.confirmation : null, undoIds };
}

// text -> text, ui_* tools -> parts, other tools -> nothing (the confirmation stands for them),
// data-activity -> the grey box. data-status is transient and never lands in `parts`.
export function toViewParts(m: UIMessage): ViewPart[] {
  const out: ViewPart[] = [];
  for (const part of m.parts as AnyPart[]) {
    if (part.type === "text") {
      if (part.text !== "") out.push({ kind: "text", text: part.text });
    } else if (part.type === "dynamic-tool") {
      const ui = uiPart(part.toolName, part as unknown as ToolLike);
      if (ui) out.push(ui);
    } else if (part.type.startsWith("tool-")) {
      const ui = uiPart(part.type.slice("tool-".length), part as unknown as ToolLike);
      if (ui) out.push(ui);
    } else if (part.type === "data-activity") {
      out.push(activityPart((part as { data?: unknown }).data));
    }
  }
  return out;
}

/** The conversation id the BE reported for this answer (`start`/`finish` metadata), if any. */
export function conversationIdOf(m: UIMessage): number | null {
  const id = isObj(m.metadata) ? m.metadata.conversation_id : null;
  return typeof id === "number" ? id : null;
}
