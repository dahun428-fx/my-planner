// SP12 11.1: the chat partner. The pick is kept on this device (localStorage); any failure reads as the secretary.
// SP15 11장: the life manager. A partner the BE lacks (no `features` entry) is the secretary's chat (ChatSheet).
export type Agent = "secretary" | "mate" | "manager";

const KEY = "chat.agent";

export function loadAgent(): Agent {
  try {
    const v = localStorage.getItem(KEY);
    return v === "mate" || v === "manager" ? v : "secretary";
  } catch {
    return "secretary";
  }
}

export function saveAgent(a: Agent): void {
  try {
    localStorage.setItem(KEY, a);
  } catch {
    // Private window or blocked storage: the pick lasts only while the sheet is open.
  }
}
