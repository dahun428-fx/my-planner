import { type ReactNode, useId, useState } from "react";
import { copy } from "../lib/copy";
import { Icon } from "./icons";
import styles from "./DoneFold.module.css";

// The done rows of a to-do list, folded under one quiet line ("완료 3개 ▸") that opens only when
// pressed (Dahun 2026-10-28). Closed again each time the screen mounts. Nothing when there are none.
export function DoneFold({ count, children }: { count: number; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const id = useId();
  if (count === 0) return null;
  return (
    <>
      <button
        type="button"
        className={`${styles.toggle} pressable`}
        aria-expanded={open}
        aria-controls={id}
        onClick={() => setOpen((o) => !o)}
      >
        <span className={styles.label}>{copy.today.doneFold(count)}</span>
        <span className={`${styles.chevron} ${open ? styles.open : ""}`} aria-hidden="true">
          <Icon name="chevron" />
        </span>
      </button>
      <div id={id} hidden={!open}>
        {open && children}
      </div>
    </>
  );
}
