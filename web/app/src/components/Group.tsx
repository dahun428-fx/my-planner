import type { ReactNode } from "react";
import styles from "./Group.module.css";

// iOS grouped list: white group (radius 16) on the grey ground, optional heading and footer.
export function Group({ heading, footer, children }: { heading?: ReactNode; footer?: ReactNode; children: ReactNode }) {
  return (
    <section className={styles.group}>
      {heading !== undefined && <h2 className={styles.heading}>{heading}</h2>}
      <div className={styles.body}>{children}</div>
      {footer !== undefined && <div className={styles.footer}>{footer}</div>}
    </section>
  );
}
