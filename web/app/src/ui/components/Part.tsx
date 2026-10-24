import type { ReactNode } from "react";
import { copy } from "../../lib/copy";
import styles from "./parts.module.css";

// The frame every part draws in: a white group with an optional title, and the one sentence that
// says why the buttons are off when the screen is read-only (spec 5.4).
export function Part({
  title,
  variant,
  readOnly = false,
  children,
}: {
  title?: string;
  variant?: "outlined" | "confirm";
  readOnly?: boolean;
  children: ReactNode;
}) {
  const cls = `${styles.card} ${variant === "outlined" ? styles.outlined : ""} ${variant === "confirm" ? styles.confirm : ""}`;
  return (
    <section className={cls}>
      {title !== undefined && <h3 className={styles.title}>{title}</h3>}
      {children}
      {readOnly && <p className={styles.reason}>{copy.offline.writeLater}</p>}
    </section>
  );
}

export function CheckRow({
  title,
  checked,
  disabled,
  done,
  onToggle,
}: {
  title: string;
  checked: boolean;
  disabled: boolean;
  done?: boolean;
  onToggle(): void;
}) {
  return (
    <li className={styles.row}>
      <button type="button" role="checkbox" aria-checked={checked} aria-label={copy.parts.checkLabel(title)} className={styles.check} disabled={disabled} onClick={onToggle}>
        <span className={styles.circle} />
      </button>
      <span className={`${styles.rowText} ${done ? styles.done : ""}`}>{title}</span>
    </li>
  );
}
