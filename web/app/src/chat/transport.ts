import "./zodJitless"; // first: before "ai" builds its schemas
import { DefaultChatTransport, type UIMessage, type UIMessageChunk } from "ai";
import type { Conn } from "../lib/connection";
import type { WireChip } from "./quickChips";

/**
 * What the next POST /chat carries besides the message (SP3-4 6.4.1). `resumeConversationId`: the
 * conversation picked from the list (SP9 7.3 rule 0), sent with every message while it is shown.
 */
export type ChatCtx = { conversationId: number | null; checkinId: number | null; resumeConversationId?: number | null };

export interface ChatBody {
  client_msg_id: string;
  conversation_id: number | null;
  checkin_id: number | null;
  resume_conversation_id?: number;
  /** SP9c 4.1: the quick chip the message came from (`metadata.chip`). */
  chip?: WireChip;
  message: UIMessage;
}

// A message can name its own run (the check-in chip, SP9 9.5): `metadata.checkin_id`.
function ownCheckinId(message: UIMessage): number | null {
  const meta = message.metadata as { checkin_id?: unknown } | undefined;
  return typeof meta?.checkin_id === "number" ? meta.checkin_id : null;
}
const ownChip = (message: UIMessage) => (message.metadata as { chip?: WireChip } | undefined)?.chip;

/** The body ended before `finish` (or the connection broke while it was read): the answer may still be on the BE. */
export class StreamCutError extends Error {
  override name = "StreamCutError";
}

/** 409: the BE is still answering this very message (it was sent before and could not be joined). The same id may be sent again later. */
export class InFlightError extends Error {
  override name = "InFlightError";
}

// SP9c 4.1: a BE from before the chips refuses the unknown `chip` key (400 invalid_request). The body
// without it, for one more try under the same client_msg_id; null when it is not that case.
async function withoutChip(res: Response, body: RequestInit["body"]): Promise<string | null> {
  if (res.status !== 400 || typeof body !== "string") return null;
  const sent = JSON.parse(body) as Record<string, unknown>;
  if (!("chip" in sent)) return null; // a message without a chip is never sent again
  const err = (await res.clone().json().catch(() => null)) as { error?: { code?: unknown } } | null;
  if (err?.error?.code !== "invalid_request") return null;
  delete sent.chip;
  return JSON.stringify(sent);
}

// A 409 from POST /chat is the in-flight answer (the other 409, an id used by /actions, cannot
// happen: every message has a fresh id). It becomes InFlightError instead of a refusal.
async function chatFetch(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  let res = await fetch(input, init);
  const plain = await withoutChip(res, init?.body);
  if (plain !== null) {
    void res.body?.cancel().catch(() => {});
    res = await fetch(input, { ...init, body: plain });
  }
  if (res.status !== 409) return res;
  void res.body?.cancel().catch(() => {});
  throw new InFlightError("answer still in flight");
}

// Spec 4.6 / F4: only the last user message goes, and its id is the client_msg_id, so a resend of
// the same message (regenerate) gets the stored answer instead of a second one.
// SP9 Review Focus 5: a message that goes to a run (`checkin_id`: the check-in chip, or the check-in
// screen's box) never carries `resume_conversation_id`, so the app never sends the two together.
export function buildChatBody(messages: UIMessage[], ctx: ChatCtx): ChatBody {
  const message = [...messages].reverse().find((m) => m.role === "user");
  if (!message) throw new Error("no user message to send");
  const checkinId = ownCheckinId(message) ?? ctx.checkinId;
  const body: ChatBody = { client_msg_id: message.id, conversation_id: ctx.conversationId, checkin_id: checkinId, message };
  if (checkinId === null && ctx.resumeConversationId != null) body.resume_conversation_id = ctx.resumeConversationId;
  const chip = ownChip(message);
  if (chip !== undefined) body.chip = chip;
  return body;
}

// Read errors on the raw body become StreamCutError (a cut, not a protocol error).
function guardBytes(body: ReadableStream<Uint8Array>): ReadableStream<Uint8Array> {
  const reader = body.getReader();
  return new ReadableStream<Uint8Array>({
    async pull(controller) {
      try {
        const { done, value } = await reader.read();
        if (done) controller.close();
        else controller.enqueue(value);
      } catch {
        controller.error(new StreamCutError("stream cut"));
      }
    },
    cancel(reason) {
      return reader.cancel(reason);
    },
  });
}

// A stream that closes without `finish` (or `error`/`abort`) was cut short.
function requireEnd(): TransformStream<UIMessageChunk, UIMessageChunk> {
  let ended = false;
  return new TransformStream({
    transform(chunk, controller) {
      if (chunk.type === "finish" || chunk.type === "error" || chunk.type === "abort") ended = true;
      controller.enqueue(chunk);
    },
    flush(controller) {
      if (!ended) controller.error(new StreamCutError("stream ended before finish"));
    },
  });
}

class GuardedTransport extends DefaultChatTransport<UIMessage> {
  protected override processResponseStream(stream: ReadableStream<Uint8Array<ArrayBufferLike>>): ReadableStream<UIMessageChunk> {
    return super.processResponseStream(guardBytes(stream)).pipeThrough(requireEnd());
  }
}

// The address and token are read at send time, so a reconnect to another BE needs no new transport.
export function makeTransport(getConn: () => Conn, getCtx: () => ChatCtx): DefaultChatTransport<UIMessage> {
  return new GuardedTransport({
    fetch: chatFetch,
    headers: () => ({ Authorization: `Bearer ${getConn().token}` }),
    prepareSendMessagesRequest: ({ messages }) => ({
      api: `${getConn().beUrl}/api/v1/chat`,
      body: buildChatBody(messages, getCtx()),
    }),
  });
}
