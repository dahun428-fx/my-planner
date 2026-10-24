import type { ReactNode } from "react";
import styles from "./LargeTitle.module.css";

// Spec 5.1/5.5.1: grey meta line (13) above a 30/700 title, optional trailing control.
export function LargeTitle({ title, meta, trailing }: { title: string; meta?: ReactNode; trailing?: ReactNode }) {
  return (
    <header className={styles.header}>
      <div className={styles.text}>
        {meta !== undefined && <div className={styles.meta}>{meta}</div>}
        <h1 className={styles.title}>{title}</h1>
      </div>
      {trailing !== undefined && <div className={styles.trailing}>{trailing}</div>}
    </header>
  );
}
