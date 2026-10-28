import { type KeyboardEvent, useEffect, useId, useRef, useState } from "react";
import { Icon, type IconName } from "../components/icons";
import { copy } from "../lib/copy";
import styles from "./ChatSheet.module.css";

export interface AttachItem {
  key: string;
  label: string;
  icon: IconName;
  /** Cannot be chosen now: it stays in the menu (and can hold the focus) but does nothing. */
  disabled?: boolean;
  /** Dimmed but still chosen: it says why it cannot act (the tray is full). */
  dimmed?: boolean;
  onSelect: () => void;
}

// The (+) at the field's leading edge: it opens a small menu above it (as Claude's and Codex's
// composers do) with what can go with a message. Escape, a press outside or a choice closes it;
// the arrows (and Home/End) move between the items. The focus goes into the menu only when it was
// opened from the keyboard: a tap leaves it in the field, so a phone's keyboard stays up. Closing
// gives it back to the (+), never to the page behind the sheet.
export function AttachMenu({ items, disabled }: { items: AttachItem[]; disabled?: boolean }) {
  const [open, setOpen] = useState(false);
  const [fromKeys, setFromKeys] = useState(false);
  const id = useId();
  const wrap = useRef<HTMLDivElement>(null);
  const button = useRef<HTMLButtonElement>(null);
  const menu = useRef<HTMLDivElement>(null);

  const itemEls = () => [...(menu.current?.querySelectorAll<HTMLElement>('[role="menuitem"]') ?? [])];
  const close = () => {
    if (wrap.current?.contains(document.activeElement)) button.current?.focus();
    setOpen(false);
  };

  useEffect(() => {
    if (!open) return;
    if (fromKeys) itemEls()[0]?.focus();
    const onDown = (e: PointerEvent) => {
      if (!wrap.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", onDown);
    return () => document.removeEventListener("pointerdown", onDown);
  }, [open, fromKeys]);

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
    } else if (e.key === "ArrowDown" || e.key === "ArrowUp" || e.key === "Home" || e.key === "End") {
      e.preventDefault();
      const list = itemEls();
      if (list.length === 0) return;
      const i = list.indexOf(document.activeElement as HTMLElement);
      const next =
        e.key === "Home" ? 0 : e.key === "End" ? list.length - 1 : e.key === "ArrowDown" ? (i + 1) % list.length : i <= 0 ? list.length - 1 : i - 1;
      list[next].focus();
    } else if (e.key === "Tab") {
      close();
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
        aria-controls={open ? id : undefined}
        data-open={open ? "" : undefined}
        disabled={disabled}
        // A tap keeps the focus where it is (the field), as the ×'s does.
        onPointerDown={(e) => e.preventDefault()}
        onClick={(e) => {
          // detail 0: Enter or Space, not a tap or a click.
          setFromKeys(e.detail === 0);
          setOpen((o) => !o);
        }}
      >
        <Icon name="plus" />
      </button>
      {open && (
        <div ref={menu} id={id} role="menu" aria-label={copy.chat.attach} className={styles.attachMenu}>
          {items.map((it) => (
            <button
              key={it.key}
              type="button"
              role="menuitem"
              className={styles.attachItem}
              tabIndex={-1}
              onPointerDown={(e) => e.preventDefault()}
              aria-disabled={it.disabled || it.dimmed ? true : undefined}
              onClick={() => {
                if (it.disabled) return;
                // The focus goes back to the (+) first; the file input's click stays inside the press.
                close();
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
