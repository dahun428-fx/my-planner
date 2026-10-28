import { type ReactNode, useEffect, useId, useRef, useState } from "react";
import { copy } from "../lib/copy";
import { Icon } from "./icons";
import styles from "./DoneFold.module.css";

// The done rows of a to-do list, folded under one quiet line ("완료 3개 ▸") that opens only when
// pressed (Dahun 2026-10-28). Starts closed, and closes again once nothing is done. Nothing when there are none.
export function DoneFold({ count, children }: { count: number; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const id = useId();
  const toggle = useRef<HTMLButtonElement>(null);
  const last = useRef(count);

  useEffect(() => {
    if (count === 0) setOpen(false);
    // A check (or un-check) moves its row across the fold, so the pressed box leaves the DOM and
    // focus falls to the page: hand it to the fold line, whose new count says what happened.
    if (count !== last.current && document.activeElement === document.body) toggle.current?.focus();
    last.current = count;
  }, [count]);

  if (count === 0) return null;
  return (
    <>
      <button
        ref={toggle}
        type="button"
        className={`${styles.toggle} pressable`}
        aria-expanded={open}
        aria-controls={id}
        onClick={() => setOpen((o) => !o)}
      >
        {copy.today.doneFold(count)}
        <span className={`${styles.chevron} ${open ? styles.open : ""}`} aria-hidden="true">
          <Icon name="chevron" />
        </span>
      </button>
      <div id={id} className={styles.panel} hidden={!open}>
        {open && children}
      </div>
    </>
  );
}
