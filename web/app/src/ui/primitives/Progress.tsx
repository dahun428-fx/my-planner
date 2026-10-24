import { copy } from "../../lib/copy";
import styles from "./primitives.module.css";

/** `progress` (5.3.4): a <progress> element, so no width is ever written inline. "n/m", never a ratio. */
export function Progress({ label, value, max }: { label: string; value: number; max: number }) {
  return (
    <div className={styles.progress}>
      <div className={styles.progressHead}>
        <span className={styles.progressLabel}>{label}</span>
        <span className={styles.progressCount}>{`${value}/${max}`}</span>
      </div>
      <progress className={styles.bar} value={value} max={max} aria-label={copy.parts.progressAria(label, value, max)} />
    </div>
  );
}
