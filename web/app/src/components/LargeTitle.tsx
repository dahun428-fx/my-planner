import type { ReactNode } from "react";
import styles from "./LargeTitle.module.css";

// Spec 5.1/5.5.1: grey meta line (13) above a 30/700 title, optional trailing control, and an
// optional grey line under the title across the whole width (5.5.3 sent line, 5.5.6 intro).
// SP9 9.2: the schedule tab's title is its month toggle button, so `title` takes a node.
export function LargeTitle({ title, meta, sub, trailing }: { title: ReactNode; meta?: ReactNode; sub?: ReactNode; trailing?: ReactNode }) {
  return (
    <header className={styles.header}>
      <div className={styles.row}>
        <div className={styles.text}>
          {meta !== undefined && <div className={styles.meta}>{meta}</div>}
          <h1 className={styles.title}>{title}</h1>
        </div>
        {trailing !== undefined && <div className={styles.trailing}>{trailing}</div>}
      </div>
      {sub !== undefined && <p className={styles.sub}>{sub}</p>}
    </header>
  );
}
