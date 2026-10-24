import { copy } from "../lib/copy";
import styles from "./ConfirmSheet.module.css";
import { Sheet } from "./Sheet";

export interface ConfirmSheetProps {
  summary: string;
  onKeep: () => void;
  onChange: () => void;
  busy: boolean;
}

// The sheet for a `needs_confirm` answer (spec 5.5.5): the BE's summary and two buttons. The caller
// sends the same action again with the confirm token and a NEW client_msg_id on "바꾸기".
export function ConfirmSheet({ summary, onKeep, onChange, busy }: ConfirmSheetProps) {
  return (
    <Sheet open onClose={() => !busy && onKeep()}>
      <p className={styles.summary}>{summary}</p>
      <div className={styles.buttons}>
        <button type="button" className={styles.keep} onClick={onKeep} disabled={busy}>
          {copy.todos.keep}
        </button>
        <button type="button" className={styles.change} onClick={onChange} disabled={busy}>
          {copy.todos.change}
        </button>
      </div>
    </Sheet>
  );
}
