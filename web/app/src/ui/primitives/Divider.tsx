import styles from "./primitives.module.css";

/** `divider` (5.3.9): screen readers skip it. */
export function Divider() {
  return <hr className={styles.divider} aria-hidden="true" />;
}
