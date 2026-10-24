import type { ConnState } from "../lib/connection";
import { copy } from "../lib/copy";
import styles from "./StatusDot.module.css";

const LABEL: Record<ConnState["kind"], string> = {
  online: copy.status.connected,
  offline: copy.status.offline,
  unauthorized: copy.status.unauthorized,
  rate_limited: copy.status.tooMany,
  safe_mode: copy.status.safeMode,
};

// Spec 5.4: a dot beside the title plus words. The colour never carries the meaning alone.
export function StatusDot({ state }: { state: ConnState }) {
  return (
    <span className={styles.status}>
      <span className={`${styles.dot} ${styles[state.kind]}`} aria-hidden="true" />
      <span className={styles.label}>{LABEL[state.kind]}</span>
    </span>
  );
}
