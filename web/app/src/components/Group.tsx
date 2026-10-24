import type { ReactNode } from "react";
import styles from "./Group.module.css";

// A section (DESIGN.md): an optional label head (with an optional control at its right, e.g.
// "모두 확정") and footer. Boxed: the grouped list (--surface, radius 16). `paper`: continuous paper,
// rows on the ground split by inset hairlines (Today, Todos, Activity).
export function Group({
  heading,
  action,
  footer,
  paper = false,
  children,
}: {
  heading?: ReactNode;
  action?: ReactNode;
  footer?: ReactNode;
  paper?: boolean;
  children: ReactNode;
}) {
  return (
    <section className={paper ? `${styles.group} ${styles.paper}` : styles.group}>
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
