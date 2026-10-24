import { copy } from "../lib/copy";
import styles from "./BlockError.module.css";

// Spec 5.4 "그 밖 오류": shown inside the one block that failed; other blocks stay as they are.
export function BlockError({ code, onRetry }: { code: string; onRetry: () => void }) {
  return (
    <div className={styles.error} role="status">
      <span>{copy.errors.block(code)}</span>
      <span aria-hidden="true"> · </span>
      <button type="button" className={styles.retry} onClick={onRetry}>
        {copy.errors.retry}
      </button>
    </div>
  );
}
