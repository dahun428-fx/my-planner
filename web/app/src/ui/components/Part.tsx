import type { ReactNode, RefObject } from "react";
import { copy } from "../../lib/copy";
import styles from "./parts.module.css";

// The frame every part draws in: a white group with an optional title, and the one sentence that
// says why the buttons are off when the screen is read-only (spec 5.4). The check row is
// ui/primitives/CheckRow (SP6 5.3.5).
export function Part({
  title,
  variant,
  readOnly = false,
  restored = false,
  focusRef,
  children,
}: {
  title?: string;
  variant?: "outlined" | "confirm";
  readOnly?: boolean;
  /** A card restored after a reload (4.6): its marks are drawn read-only, without the offline reason. */
  restored?: boolean;
  /** A card that takes focus back itself (after a sheet over it closes): the frame can be focused from script. */
  focusRef?: RefObject<HTMLElement | null>;
  children: ReactNode;
}) {
  const cls = `${styles.card} ${variant === "outlined" ? styles.outlined : ""} ${variant === "confirm" ? styles.confirm : ""}`;
  // `data-read-only` draws CheckRow's mark round (SP5 5.5.4); CSS module classes do not reach across sheets.
  return (
    <section ref={focusRef} tabIndex={focusRef ? -1 : undefined} className={cls} data-read-only={readOnly || restored ? "" : undefined}>
      {title !== undefined && <h3 className={styles.title}>{title}</h3>}
      {children}
      {readOnly && <p className={styles.reason}>{copy.offline.writeLater}</p>}
    </section>
  );
}
