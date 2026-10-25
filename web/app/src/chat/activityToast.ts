import type { ToastContent } from "../components/Toast";
import { copy } from "../lib/copy";
import type { ViewPart } from "./parts";

/**
 * SP9 9.6: the toast for one answer's changes, or null when none of them can be undone. One
 * undoable change shows its confirmation; several show "✓ {n}개를 바꿨어요", and "되돌리기" undoes all
 * of them, newest first (Toast), so the words and what is undone match.
 */
export function chatActivityToast(parts: ViewPart[]): ToastContent | null {
  const acts = parts.filter((p): p is Extract<ViewPart, { kind: "activity" }> => p.kind === "activity");
  const ids = [...new Set(acts.flatMap((a) => a.undoIds))];
  if (ids.length === 0) return null;
  if (ids.length > 1) return { text: copy.chat.changedMany(ids.length), undoIds: ids };
  // One: the confirmation of the part that holds it (its line in the chat says the same).
  const own = acts.find((a) => a.undoIds.includes(ids[0]))?.confirmation ?? null;
  return { text: own ?? copy.chat.changed, undoIds: ids };
}
