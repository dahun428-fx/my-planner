import Link from "next/link";
import type { ReactNode } from "react";
import styles from "./Row.module.css";

export interface RowProps {
  leading?: ReactNode;
  title: ReactNode;
  meta?: ReactNode;
  trailing?: ReactNode;
  href?: string;
  onPress?: () => void;
  /** With `onPress`: the row opens a panel in place (aria-expanded, aria-controls). */
  expanded?: boolean;
  controls?: string;
}

// One list row, min height --row. Navigation is <a>, an action is <button>, otherwise plain.
export function Row({ leading, title, meta, trailing, href, onPress, expanded, controls }: RowProps) {
  const inner = (
    <>
      {leading !== undefined && <span className={styles.leading}>{leading}</span>}
      <span className={styles.text}>
        <span className={styles.title}>{title}</span>
        {meta !== undefined && <span className={styles.meta}>{meta}</span>}
      </span>
      {trailing !== undefined && <span className={styles.trailing}>{trailing}</span>}
    </>
  );
  if (href !== undefined) {
    return (
      <Link href={href} className={`${styles.row} ${styles.interactive}`}>
        {inner}
      </Link>
    );
  }
  if (onPress !== undefined) {
    return (
      <button type="button" className={`${styles.row} ${styles.interactive}`} onClick={onPress} aria-expanded={expanded} aria-controls={controls}>
        {inner}
      </button>
    );
  }
  return <div className={styles.row}>{inner}</div>;
}
