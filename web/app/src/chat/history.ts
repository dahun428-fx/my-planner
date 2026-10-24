import type { UIMessage } from "ai";
import { apiFetch } from "../api/client";
import type { Conversations } from "../api/types.gen";
import { validateModel } from "../api/validate";
import { loadParts } from "./localParts";
import type { ViewPart } from "./parts";

const ELSEWHERE_MAX = 3;

export type Meta = { conversation_id?: number | null; at?: string };
type Line = { id?: string; at: string; speaker: "user" | "secretary"; text: string };

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
    if (!isObj(m) || typeof m.at !== "string" || typeof m.text !== "string" || (m.speaker !== "user" && m.speaker !== "secretary")) return null;
    out.push({ id: typeof m.id === "string" && m.id !== "" ? m.id : undefined, at: m.at, speaker: m.speaker, text: m.text });
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

export async function loadHistory(given: number | null | undefined): Promise<HistoryResult> {
  let id: number | null = null;
  if (given !== undefined) {
    id = given;
  } else {
    const r = await apiFetch<Conversations>("GET", "/conversations?channel=app&limit=3", { model: "Conversations" });
    if (r.kind !== "ok") return failure(r);
    if (!validateModel("Conversations", r.data)) return { kind: "failed", code: "shape" };
    const latest = [...r.data.items].sort((a, b) => (a.last_message_at < b.last_message_at ? 1 : -1))[0];
    id = latest?.id ?? null;
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
    if (l.id && l.speaker === "secretary") {
      const parts = await loadParts(l.id);
      if (parts) restored[mid] = parts.map((p) => (p.kind === "ui" ? { ...p, restored: true } : p));
    }
    messages.push({
      id: mid,
      role: l.speaker === "user" ? "user" : "assistant",
      parts: [{ type: "text", text: l.text }],
      metadata: { conversation_id: id, at: l.at } satisfies Meta,
    });
  }
  const last = lines[lines.length - 1];
  const elsewhere = given === undefined && last ? await readElsewhere(last.at) : [];
  return { kind: "ok", history: { conversationId: id, messages, restored, elsewhere } };
}
