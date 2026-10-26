import { createContext, useContext } from "react";

// The chat sheet's door, held by _app (spec 5.3: the launcher on Today, Todos and Activity opens
// it). Kept apart from ChatSheet so screens do not pull the AI SDK into the first load.
export interface ChatSheetApi {
  open(): void;
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
export const sheetState: { pickedConversationId: number | null; freshSince: string | null } = { pickedConversationId: null, freshSince: null };
// `freshSince` (review round 1): when "새 대화" (or deleting the conversation on screen) left an empty
// chat. Until something is said or a row is opened, a reopened sheet stays empty: the latest
// conversation is shown only when it was spoken in after this moment (another device). Kept across
// a close, forgotten when the sheet goes away (another BE).
