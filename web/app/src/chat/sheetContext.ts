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
