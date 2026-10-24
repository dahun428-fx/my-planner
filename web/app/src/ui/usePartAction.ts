import { type ActionName, type ActionOutcome, useAction } from "../api/actions";
import { useToast } from "../components/Toast";
import { copy } from "../lib/copy";

// The one way a part writes: useAction (second press ignored while the first is in flight, toasts
// for applied / rejected / failed) plus the two answers useAction leaves to the caller.
export function usePartAction() {
  const { run } = useAction();
  const toast = useToast();
  return async (action: ActionName, args: object, opts?: { confirmToken?: string }): Promise<ActionOutcome | null> => {
    const out = await run(action, args, opts);
    if (out?.kind === "conflict" || out?.kind === "needs_confirm") toast.show({ text: copy.actions.failed });
    return out;
  };
}
