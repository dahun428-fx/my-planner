import { useCallback, useRef, useState } from "react";
import { newClientMsgId } from "../lib/ids";
import { copy } from "../lib/copy";
import { useToast } from "../components/Toast";
import { type ApiResult, apiFetch } from "./client";

// Hand-written from SP3-4 6.4.2 / 6.4.3 until the BE write models are in schema.json.

/** The `action` names of the POST /actions table (SP3-4 6.4.2). The BE does not offer propose_tasks, add_milestone, propose_chapter or grant_xp. */
export type ActionName =
  | "add_task"
  | "update_task"
  | "move_task"
  | "complete_task"
  | "reopen_task"
  | "drop_task"
  | "confirm_tasks"
  | "set_priorities"
  | "record_condition"
  | "record_ladder_score"
  | "record_area_scores"
  | "confirm_milestones"
  | "confirm_chapters"
  | "drop_milestone"
  | "drop_chapter"
  | "pin_card"
  | "unpin_card"
  | "reorder_cards"
  | "decline_confirm";

export type ActionOutcome =
  | { kind: "applied"; activityId: number; undoId: number | null; confirmation: string; result: unknown }
  | { kind: "needs_confirm"; confirmToken: string; summary: string; expiresAt: string }
  | { kind: "rejected"; message: string }
  | { kind: "conflict" }
  | { kind: "failed"; result: ApiResult<never> };

export type UndoBlockReason = "superseded" | "undo_expired" | "not_undoable";
export type UndoOutcome =
  | { kind: "undone"; confirmation: string }
  | { kind: "already_undone" }
  | { kind: "blocked"; reason: UndoBlockReason }
  | { kind: "failed"; result: ApiResult<never> };

interface ActionResponse {
  status?: unknown;
  activity_id?: unknown;
  undo_id?: unknown;
  result?: unknown;
  confirmation?: unknown;
  confirm_token?: unknown;
  summary?: unknown;
  expires_at?: unknown;
}

const SHAPE: ApiResult<never> = { kind: "error", status: 200, code: "shape" };
const asFailure = (r: ApiResult<unknown>): ApiResult<never> => (r.kind === "ok" ? SHAPE : (r as ApiResult<never>));

// A network error may have hidden an answer that did arrive, so the same request goes again once
// with the same client_msg_id: the BE gives back the first answer instead of doing it twice (6.1).
async function sendOnce<T>(path: string, body: Record<string, unknown>): Promise<ApiResult<T>> {
  const first = await apiFetch<T>("POST", path, { body });
  if (first.kind !== "offline") return first;
  return apiFetch<T>("POST", path, { body });
}

export async function runAction(action: ActionName, args: object, opts: { confirmToken?: string } = {}): Promise<ActionOutcome> {
  const r = await sendOnce<ActionResponse>("/actions", {
    action,
    args,
    client_msg_id: newClientMsgId(),
    confirm_token: opts.confirmToken ?? null,
  });
  if (r.kind === "error") {
    if (r.status === 422 && r.code === "rejected") return { kind: "rejected", message: r.message ?? "" };
    if (r.status === 409 && r.code === "conflict") return { kind: "conflict" };
  }
  if (r.kind !== "ok") return { kind: "failed", result: asFailure(r) };
  const d = r.data ?? {};
  if (d.status === "applied" && typeof d.activity_id === "number" && typeof d.confirmation === "string") {
    return {
      kind: "applied",
      activityId: d.activity_id,
      undoId: typeof d.undo_id === "number" ? d.undo_id : null,
      confirmation: d.confirmation,
      result: d.result,
    };
  }
  if (d.status === "needs_confirm" && typeof d.confirm_token === "string" && typeof d.summary === "string") {
    return {
      kind: "needs_confirm",
      confirmToken: d.confirm_token,
      summary: d.summary,
      expiresAt: typeof d.expires_at === "string" ? d.expires_at : "",
    };
  }
  return { kind: "failed", result: SHAPE };
}

export async function undoActivity(id: number): Promise<UndoOutcome> {
  const r = await sendOnce<{ status?: unknown; confirmation?: unknown }>(`/activity/${id}/undo`, {
    client_msg_id: newClientMsgId(),
  });
  if (r.kind === "error") {
    if (r.status === 409 && (r.code === "superseded" || r.code === "undo_expired")) return { kind: "blocked", reason: r.code };
    if (r.status === 422 && r.code === "not_undoable") return { kind: "blocked", reason: "not_undoable" };
  }
  if (r.kind !== "ok") return { kind: "failed", result: asFailure(r) };
  if (r.data?.status === "undone" && typeof r.data.confirmation === "string") return { kind: "undone", confirmation: r.data.confirmation };
  if (r.data?.status === "already_undone") return { kind: "already_undone" };
  return { kind: "failed", result: SHAPE };
}

/** The sentence for a write that did not go through (5.4). */
export function failureText(result: ApiResult<unknown>): string {
  switch (result.kind) {
    case "offline":
      return copy.actions.offline;
    case "unauthorized":
      return copy.status.unauthorized;
    case "rate_limited":
      return copy.status.tooMany;
    case "safe_mode":
      return copy.status.safeMode;
    default:
      return copy.actions.failed;
  }
}

const keyOf = (action: ActionName, args: object) => `${action}:${JSON.stringify(args)}`;

export interface UseAction {
  /**
   * Resolves null (and sends nothing) while the same action with the same args is still in flight.
   * Shows a toast for applied, rejected and failed only: callers must handle `conflict` and
   * `needs_confirm` themselves.
   */
  run(action: ActionName, args: object, opts?: { confirmToken?: string }): Promise<ActionOutcome | null>;
  isPending(action: ActionName, args: object): boolean;
}

// The one door for writes from a screen: ignores a second press, tells the person what happened.
export function useAction(): UseAction {
  const toast = useToast();
  const toastRef = useRef(toast);
  toastRef.current = toast;
  const inFlight = useRef(new Set<string>());
  const [pending, setPending] = useState<ReadonlySet<string>>(new Set());

  const run = useCallback(async (action: ActionName, args: object, opts?: { confirmToken?: string }) => {
    const key = keyOf(action, args);
    if (inFlight.current.has(key)) return null;
    inFlight.current.add(key);
    setPending(new Set(inFlight.current));
    try {
      const out = await runAction(action, args, opts);
      if (out.kind === "applied") toastRef.current.show({ text: out.confirmation, undoId: out.undoId });
      else if (out.kind === "rejected" && out.message) toastRef.current.show({ text: out.message });
      else if (out.kind === "failed") toastRef.current.show({ text: failureText(out.result) });
      return out;
    } finally {
      inFlight.current.delete(key);
      setPending(new Set(inFlight.current));
    }
  }, []);

  const isPending = useCallback((action: ActionName, args: object) => pending.has(keyOf(action, args)), [pending]);
  return { run, isPending };
}
