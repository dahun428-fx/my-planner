import { type ActionName, type ActionOutcome, useAction } from "../api/actions";
import { useToast } from "../components/Toast";
import { copy } from "../lib/copy";

export type NeedsConfirm = Extract<ActionOutcome, { kind: "needs_confirm" }>;

// The one way a part writes: useAction (second press ignored while the first is in flight, toasts
// for applied / rejected / failed) plus the two answers useAction leaves to the caller. A card
// that can ask (SP6 11.5: ui_date_choice's ConfirmSheet) passes `onNeedsConfirm`; for every other
// card a confirm question is the failure sentence, as before.
export function usePartAction() {
  const { run } = useAction();
  const toast = useToast();
  return async (
    action: ActionName,
    args: object,
    opts?: { confirmToken?: string; onNeedsConfirm?(o: NeedsConfirm): void },
  ): Promise<ActionOutcome | null> => {
    const out = await run(action, args, opts?.confirmToken === undefined ? undefined : { confirmToken: opts.confirmToken });
    if (out?.kind === "needs_confirm" && opts?.onNeedsConfirm) opts.onNeedsConfirm(out);
    else if (out?.kind === "conflict" || out?.kind === "needs_confirm") toast.show({ text: copy.actions.failed });
    return out;
  };
}
