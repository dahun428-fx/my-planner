import { type KeyboardEvent, useEffect, useRef, useState } from "react";
import { Icon, type IconName } from "../components/icons";
import { copy } from "../lib/copy";
import styles from "./ChatSheet.module.css";

export interface AttachItem {
  key: string;
  label: string;
  icon: IconName;
  /** Cannot be chosen now (no answer from the menu at all). */
  disabled?: boolean;
  /** Dimmed but still chosen: it says why it cannot act (the tray is full). */
  dimmed?: boolean;
  onSelect: () => void;
}

// The (+) at the field's leading edge: it opens a small menu above it (as Claude's and Codex's
// composers do) with what can go with a message. Escape, a press outside or a choice closes it;
// the arrows move between the items, and the focus goes back to the (+) on Escape.
export function AttachMenu({ items, disabled }: { items: AttachItem[]; disabled?: boolean }) {
  const [open, setOpen] = useState(false);
  const wrap = useRef<HTMLDivElement>(null);
  const button = useRef<HTMLButtonElement>(null);
  const menu = useRef<HTMLDivElement>(null);

  const enabled = () => [...(menu.current?.querySelectorAll<HTMLElement>('[role="menuitem"]:not([disabled])') ?? [])];

  useEffect(() => {
    if (!open) return;
    enabled()[0]?.focus();
    const onDown = (e: PointerEvent) => {
      if (!wrap.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", onDown);
    return () => document.removeEventListener("pointerdown", onDown);
  }, [open]);

  useEffect(() => {
    if (disabled) setOpen(false);
  }, [disabled]);

  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if (!open) return;
    if (e.key === "Escape") {
      // The menu alone closes, not the sheet under it.
      e.stopPropagation();
      e.preventDefault();
      setOpen(false);
      button.current?.focus();
    } else if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      const list = enabled();
      if (list.length === 0) return;
      const i = list.indexOf(document.activeElement as HTMLElement);
      const next = e.key === "ArrowDown" ? (i + 1) % list.length : i <= 0 ? list.length - 1 : i - 1;
      list[next].focus();
    } else if (e.key === "Tab") {
      setOpen(false);
    }
  };

  return (
    <div ref={wrap} className={styles.attach} onKeyDown={onKeyDown}>
      <button
        ref={button}
        type="button"
        className={`${styles.attachButton} pressable`}
        aria-label={copy.chat.attach}
        aria-haspopup="menu"
        aria-expanded={open}
        data-open={open ? "" : undefined}
        disabled={disabled}
        onClick={() => setOpen((o) => !o)}
      >
        <Icon name="plus" />
      </button>
      {open && (
        <div ref={menu} role="menu" aria-label={copy.chat.attach} className={styles.attachMenu}>
          {items.map((it) => (
            <button
              key={it.key}
              type="button"
              role="menuitem"
              className={styles.attachItem}
              aria-disabled={it.dimmed ? true : undefined}
              disabled={it.disabled}
              onClick={() => {
                setOpen(false);
                it.onSelect();
              }}
            >
              <Icon name={it.icon} />
              <span>{it.label}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
