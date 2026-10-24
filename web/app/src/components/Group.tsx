import type { ReactNode } from "react";
import styles from "./Group.module.css";

// iOS grouped list: white group (radius 16) on the grey ground, optional heading (with an optional
// control at its right, e.g. "모두 확정") and footer.
export function Group({ heading, action, footer, children }: { heading?: ReactNode; action?: ReactNode; footer?: ReactNode; children: ReactNode }) {
  return (
    <section className={styles.group}>
      {heading !== undefined &&
        (action !== undefined ? (
          <div className={styles.headRow}>
            <h2 className={styles.heading}>{heading}</h2>
            {action}
          </div>
        ) : (
          <h2 className={styles.heading}>{heading}</h2>
        ))}
      <div className={styles.body}>{children}</div>
      {footer !== undefined && <div className={styles.footer}>{footer}</div>}
    </section>
  );
}
