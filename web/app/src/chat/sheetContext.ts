import { createContext, useContext } from "react";
import type { Agent } from "./agent";

// The chat sheet's door, held by _app (spec 5.3: the launcher on Today, Todos and Activity opens
// it). Kept apart from ChatSheet so screens do not pull the AI SDK into the first load.
export interface ChatSheetApi {
  /** `agent`: open on that partner (SP12 11.2, the workout screen's "운동메이트와 이야기하기"). Left out: the one kept on the device. */
  open(opts?: { agent?: Agent }): void;
  /** Called after the sheet closes (a screen reads again). Returns an unsubscribe function. */
  onClosed(cb: () => void): () => void;
}

export const ChatSheetContext = createContext<ChatSheetApi>({ open: () => {}, onClosed: () => () => {} });
export const useChatSheet = (): ChatSheetApi => useContext(ChatSheetContext);

/**
 * SP9 9.5 / 7.3: the sheet's state that outlives a render. `pickedConversationId` is the conversation
 * opened from the list: set when a row is opened, cleared by "새 대화" and when the sheet closes.
 * While it is set every POST /chat carries `resume_conversation_id` (a check-in chip's message does
 * not: it carries only `checkin_id`, Review Focus 5). The check-in screen's own reply box never reads it.
 */
export interface AgentSheetState {
  pickedConversationId: number | null;
  freshSince: string | null;
}
// SP12 11.1: one per partner, so a conversation picked for the secretary is not carried to the mate.
export const sheetState: Record<Agent, AgentSheetState> = {
  secretary: { pickedConversationId: null, freshSince: null },
  mate: { pickedConversationId: null, freshSince: null },
};
export const resetSheetState = (): void => {
  for (const a of ["secretary", "mate"] as const) sheetState[a] = { pickedConversationId: null, freshSince: null };
};
// `freshSince` (review round 1): when "새 대화" (or deleting the conversation on screen) left an empty
// chat. Until something is said or a row is opened, a reopened sheet stays empty: the latest
// conversation is shown only when it was spoken in after this moment (another device). Kept across
// a close, forgotten when the sheet goes away (another BE).
