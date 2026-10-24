import { type Conn, loadConn, reportResult } from "../lib/connection";
import { newClientMsgId } from "../lib/ids";

// A BE command (`/pause N`, `/unpause`, SP3-4 6.4.1) sent through POST /chat without the chat
// sheet (spec 5.5.7). The reply stream is read to the end and dropped; the command and its answer
// stay in the app conversation's history. Plain fetch, so the settings screen does not load the AI SDK.
// The caller reads /health again afterwards (recheck) to see the new state.

const TIMEOUT_MS = 30_000;

export async function sendCommand(text: "/pause 3" | "/unpause" | string): Promise<{ ok: boolean }> {
  const conn: Conn | null = loadConn();
  if (!conn) return { ok: false };
  const id = newClientMsgId();
  const body = {
    client_msg_id: id,
    conversation_id: null,
    checkin_id: null,
    message: { id, role: "user", parts: [{ type: "text", text }] },
  };
  const ac = new AbortController();
  const timer = setTimeout(() => ac.abort(), TIMEOUT_MS);
  try {
    let res: Response;
    try {
      res = await fetch(`${conn.beUrl}/api/v1/chat`, {
        method: "POST",
        headers: { Authorization: `Bearer ${conn.token}`, "Content-Type": "application/json", Accept: "text/event-stream" },
        body: JSON.stringify(body),
        signal: ac.signal,
        cache: "no-store",
      });
    } catch {
      reportResult({ kind: "offline" }, conn);
      return { ok: false };
    }
    if (res.status === 401) reportResult({ kind: "unauthorized" }, conn);
    if (res.status === 429) reportResult({ kind: "rate_limited" }, conn);
    if (!res.ok || !res.body) return { ok: false };
    try {
      const reader = res.body.getReader();
      for (;;) {
        const { done } = await reader.read();
        if (done) break;
      }
    } catch {
      return { ok: false }; // cut short: the command may still have been applied; recheck shows it
    }
    return { ok: true };
  } finally {
    clearTimeout(timer);
  }
}
