import type { RefObject } from "react";
import { copy } from "../lib/copy";
import styles from "./ConfirmSheet.module.css";
import { Sheet } from "./Sheet";

export interface ConfirmSheetProps {
  summary: string;
  onKeep: () => void;
  onChange: () => void;
  busy: boolean;
  /** Words for the two buttons when the question is not a to-do's (default "그대로 두기" / "바꾸기"). */
  keepLabel?: string;
  changeLabel?: string;
  /** Where focus goes when the sheet closes (default: what had it when the sheet opened). */
  returnFocusTo?: RefObject<HTMLElement | null>;
}

// The sheet for a `needs_confirm` answer (spec 5.5.5): the BE's summary and two buttons. The caller
// sends the same action again with the confirm token and a NEW client_msg_id on "바꾸기".
export function ConfirmSheet({ summary, onKeep, onChange, busy, keepLabel, changeLabel, returnFocusTo }: ConfirmSheetProps) {
  return (
    <Sheet open onClose={() => !busy && onKeep()} returnFocusTo={returnFocusTo}>
      <p className={styles.summary}>{summary}</p>
      <div className={styles.buttons}>
        <button type="button" className={styles.keep} onClick={onKeep} disabled={busy}>
          {keepLabel ?? copy.todos.keep}
        </button>
        <button type="button" className={styles.change} onClick={onChange} disabled={busy}>
          {changeLabel ?? copy.todos.change}
        </button>
      </div>
    </Sheet>
  );
}
