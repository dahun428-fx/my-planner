// SP12 11.1: the chat partner. The pick is kept on this device (localStorage); any failure reads as the secretary.
export type Agent = "secretary" | "mate";

const KEY = "chat.agent";

export function loadAgent(): Agent {
  try {
    return localStorage.getItem(KEY) === "mate" ? "mate" : "secretary";
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
