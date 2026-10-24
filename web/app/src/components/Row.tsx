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
}

// One list row, min height --row. Navigation is <a>, an action is <button>, otherwise plain.
export function Row({ leading, title, meta, trailing, href, onPress }: RowProps) {
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
      <button type="button" className={`${styles.row} ${styles.interactive}`} onClick={onPress}>
        {inner}
      </button>
    );
  }
  return <div className={styles.row}>{inner}</div>;
}
