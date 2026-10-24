import Link from "next/link";
import { copy } from "../lib/copy";
import { formatKst } from "../lib/time";
import styles from "./OfflineNotice.module.css";

// Spec 5.5.4: the notice at the top of a screen while the secretary cannot be reached.
export function OfflineNotice({ savedAt, onRetry }: { savedAt: string | null; onRetry: () => void }) {
  return (
    <section className={styles.notice} role="status">
      <p className={styles.text}>
        <strong className={styles.lead}>{copy.offline.lead}</strong>{" "}
        {savedAt ? copy.offline.snapshotAt(formatKst(savedAt, "HH:mm")) : copy.offline.noSnapshot}
      </p>
      <div className={styles.actions}>
        <button type="button" className={styles.action} onClick={onRetry}>
          {copy.offline.reconnect}
        </button>
        <Link href="/settings/" className={styles.action}>
          {copy.offline.check}
        </Link>
      </div>
    </section>
  );
}
