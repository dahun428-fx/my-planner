import type { UIMessage } from "ai";
import { apiFetch } from "../api/client";
import type { Conversations } from "../api/types.gen";
import { apiGetLate } from "../api/validateLate";
import { loadParts } from "./localParts";
import type { Agent } from "./agent";
import { type ExpertNote, readExpertNotes, type ViewPart } from "./parts";
import type { WireChip } from "./quickChips";

const ELSEWHERE_MAX = 3;
const SPEAKERS = new Set(["user", "secretary", "mate", "manager"]);

/**
 * `checkin_id`: a message sent to a run from the check-in chip (SP9 9.5); the transport sends it as the request's.
 * `chip`: the quick chip a message was sent from on this device (SP9c 3); the BE's lines never have one.
 */
export type Meta = { conversation_id?: number | null; at?: string; checkin_id?: number; chip?: WireChip };
/** `photos`: SP10 5.3, the ids of an app user line's photos in send order (its text has the marks already taken off by the BE). */
/** `notes`: SP15 1장 2, a life manager answer's expert notes (`expert_notes`, the redacted text). */
type Line = { id?: string; at: string; speaker: "user" | Agent; text: string; photos: number[]; notes: ExpertNote[] };

// A BE before SP10 has no `photos`: none. Read leniently, like the ids.
const photoIdsOf = (v: unknown): number[] =>
  Array.isArray(v) ? v.map((p) => (isObj(p) && typeof p.id === "number" ? p.id : null)).filter((id): id is number => id !== null) : [];

export interface History {
  conversationId: number | null;
  messages: UIMessage[];
  /** Restored `ui` parts per message id. They go after the line's text: /messages gives one text per line, so their place inside it is not known. */
  restored: Record<string, ViewPart[]>;
  elsewhere: string[];
}

/** `offline`: keep what is on screen (F9). `failed`: say so with a retry (5.4). */
export type HistoryResult = { kind: "ok"; history: History } | { kind: "offline" } | { kind: "failed"; code: string };

const EMPTY: History = { conversationId: null, messages: [], restored: {}, elsewhere: [] };
const isObj = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null && !Array.isArray(v);

// Read leniently: a BE before R4d has no `id` on the lines (then they show as text only).
export function readLines(data: unknown): Line[] | null {
  if (!isObj(data) || !Array.isArray(data.items)) return null;
  const out: Line[] = [];
  for (const m of data.items) {
    if (!isObj(m) || typeof m.at !== "string" || typeof m.text !== "string" || !SPEAKERS.has(m.speaker as string)) return null;
    out.push({
      id: typeof m.id === "string" && m.id !== "" ? m.id : undefined,
      at: m.at,
      speaker: m.speaker as Line["speaker"],
      text: m.text,
      photos: m.speaker === "user" ? photoIdsOf(m.photos) : [],
      notes: m.speaker === "manager" ? readExpertNotes(m.expert_notes) : [],
    });
  }
  return out;
}

// Spec 5.5.2: what changed outside the app after this conversation's last line, the newest three,
// shown oldest first. One summary a line.
export async function readElsewhere(since: string): Promise<string[]> {
  const r = await apiFetch<unknown>("GET", `/activity?order=desc&since=${encodeURIComponent(since)}&limit=50`);
  if (r.kind !== "ok" || !isObj(r.data) || !Array.isArray(r.data.items)) return [];
  return r.data.items
    .filter((a): a is { channel: string; summary: string } => isObj(a) && typeof a.summary === "string" && typeof a.channel === "string" && a.channel !== "app")
    .slice(0, ELSEWHERE_MAX)
    .map((a) => a.summary)
    .reverse();
}

const failure = (r: { kind: string; code?: string }): HistoryResult => (r.kind === "offline" ? { kind: "offline" } : { kind: "failed", code: r.code ?? r.kind });

/** `notBefore` (SP9 9.5, after "새 대화"): the latest conversation counts only when its last line is after it. */
export async function loadHistory(given: number | null | undefined, opts: { notBefore?: string | null; agent?: Agent } = {}): Promise<HistoryResult> {
  let id: number | null = null;
  if (given !== undefined) {
    id = given;
  } else {
    // The secretary's request stays as it was (no `agent`); the mate's and the life manager's name theirs.
    const agentQuery = opts.agent && opts.agent !== "secretary" ? `&agent=${opts.agent}` : "";
    const r = await apiGetLate<Conversations>(`/conversations?channel=app&limit=3${agentQuery}`, "Conversations");
    if (r.kind !== "ok") return failure(r);
    const latest = [...r.data.items].sort((a, b) => (a.last_message_at < b.last_message_at ? 1 : -1))[0];
    id = latest?.id ?? null;
    if (latest && opts.notBefore && Date.parse(latest.last_message_at) < Date.parse(opts.notBefore)) id = null;
  }
  if (id === null) return { kind: "ok", history: EMPTY };
  const r = await apiFetch<unknown>("GET", `/conversations/${id}/messages`);
  if (r.kind === "error" && r.status === 404) return { kind: "ok", history: EMPTY };
  if (r.kind !== "ok") return failure(r);
  const lines = readLines(r.data);
  if (!lines) return { kind: "failed", code: "shape" };
  const restored: Record<string, ViewPart[]> = {};
  const messages: UIMessage[] = [];
  for (let i = 0; i < lines.length; i++) {
    const l = lines[i];
    const mid = l.id ?? `h-${id}-${i}`;
    if (l.id && l.speaker !== "user") {
      const parts = await loadParts(l.id);
      if (parts) restored[mid] = parts.map((p) => (p.kind === "ui" ? { ...p, restored: true } : p));
    }
    messages.push({
      id: mid,
      role: l.speaker === "user" ? "user" : "assistant",
      // SP10 7.5: my photos come back as the data-photo parts they were sent as (a photo-only line has no text).
      // SP15: a life manager answer's notes come back as the stream's data-expert-notes part.
      parts: [
        ...(l.text === "" && l.photos.length > 0 ? [] : [{ type: "text" as const, text: l.text }]),
        ...l.photos.map((photo_id) => ({ type: "data-photo" as const, data: { photo_id } })),
        ...(l.notes.length > 0 ? [{ type: "data-expert-notes" as const, data: { notes: l.notes } }] : []),
      ],
      metadata: { conversation_id: id, at: l.at } satisfies Meta,
    });
  }
  const last = lines[lines.length - 1];
  // SP12: "elsewhere" lines (telegram, scheduler) are the secretary's world; the mate's and the life manager's views have none.
  const elsewhere = given === undefined && last && (opts.agent ?? "secretary") === "secretary" ? await readElsewhere(last.at) : [];
  return { kind: "ok", history: { conversationId: id, messages, restored, elsewhere } };
}
