import { apiFetch } from "../api/client";
import type { ChatStopped } from "../api/types.gen";

const AGAIN_MS = 1500;
const wait = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));

/**
 * POST /chat/stop for the message whose answer is coming (its client_msg_id). The app has already
 * stopped on its own; this asks the BE to stop too. Nothing it returns is shown: offline, a refusal,
 * or a BE from before the route (404) is dropped, and the BE's own answer then comes back later
 * through the history (the same message id) or a resend of the same client_msg_id.
 * `unknown` right after a send can be a request that has not reached the BE yet: asked once more.
 */
export async function stopOnBe(clientMsgId: string, pause: (ms: number) => Promise<void> = wait): Promise<ChatStopped["state"] | null> {
  for (let attempt = 0; ; attempt++) {
    const r = await apiFetch<ChatStopped>("POST", "/chat/stop", { body: { client_msg_id: clientMsgId }, model: "ChatStopped" });
    if (r.kind !== "ok") return null;
    if (r.data.state !== "unknown" || attempt > 0) return r.data.state;
    await pause(AGAIN_MS);
  }
}
