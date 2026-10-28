import { type ReactNode, useEffect, useRef, useState } from "react";
import { useToast } from "../components/Toast";
import { copy } from "../lib/copy";
import styles from "./CopyHold.module.css";

/** How long a finger stays down before the copy menu opens (iOS's own context menu is about this). */
export const HOLD_MS = 450;
/** A finger that moves this far is scrolling, not holding. */
const MOVE_PX = 10;
/** Closer than this to the top of the list it scrolls in, the menu opens below the message instead of above. */
const ROOM_PX = 64;

// The text the menu copies: what the reader sees (innerText keeps the Markdown's line breaks), from
// every [data-copy] inside the held message, so a card's buttons and the change line are left out.
function shownText(root: HTMLElement): string {
  return Array.from(root.querySelectorAll<HTMLElement>("[data-copy]"))
    .map((el) => (el.innerText || el.textContent || "").trim())
    .filter((t) => t !== "")
    .join("\n\n");
}

// The top edge the menu must stay under: the scrolling list's (the sheet's header sits above it), else the screen's.
function topEdge(el: HTMLElement): number {
  for (let p = el.parentElement; p; p = p.parentElement) {
    if (/(auto|scroll)/.test(getComputedStyle(p).overflowY)) return p.getBoundingClientRect().top;
  }
  return 0;
}

async function writeClipboard(text: string): Promise<void> {
  if (navigator.clipboard?.writeText) return navigator.clipboard.writeText(text);
  // An older WebView without the async clipboard: a hidden field and the old copy command.
  const field = document.createElement("textarea");
  field.value = text;
  field.setAttribute("readonly", "");
  field.style.position = "fixed";
  field.style.opacity = "0";
  document.body.appendChild(field);
  field.select();
  const ok = document.execCommand("copy");
  field.remove();
  if (!ok) throw new Error("copy");
}

// A chat message held down (or right-clicked) opens a small "복사" menu over it, like iOS Messages:
// the message dims a little while the menu is open, one tap copies its text and says so on the toast,
// a tap anywhere else, a scroll or Escape closes it. Holds that start on a card's controls do nothing.
export function CopyHold({ side, className, children, ...rest }: { side: "mine" | "theirs"; className?: string; children: ReactNode; [data: `data-${string}`]: string }) {
  const toast = useToast();
  const box = useRef<HTMLDivElement>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const start = useRef<{ x: number; y: number } | null>(null);
  const [open, setOpen] = useState<null | "above" | "below">(null);

  const cancel = () => {
    if (timer.current) clearTimeout(timer.current);
    timer.current = null;
    start.current = null;
  };

  const openMenu = () => {
    const el = box.current;
    if (!el || shownText(el) === "") return;
    setOpen(el.getBoundingClientRect().top - topEdge(el) < ROOM_PX ? "below" : "above");
  };

  useEffect(() => {
    if (!open) return;
    const close = (e: Event) => {
      if (e instanceof KeyboardEvent && e.key !== "Escape") return;
      if (e.type === "pointerdown" && box.current?.querySelector("[data-copy-menu]")?.contains(e.target as Node)) return;
      setOpen(null);
    };
    document.addEventListener("pointerdown", close, true);
    document.addEventListener("scroll", close, true);
    document.addEventListener("keydown", close);
    return () => {
      document.removeEventListener("pointerdown", close, true);
      document.removeEventListener("scroll", close, true);
      document.removeEventListener("keydown", close);
    };
  }, [open]);

  useEffect(() => cancel, []);

  const doCopy = async () => {
    const el = box.current;
    setOpen(null);
    if (!el) return;
    try {
      await writeClipboard(shownText(el));
      toast.show({ text: copy.chat.copied });
    } catch {
      toast.show({ text: copy.chat.copyFailed });
    }
  };

  const fromControl = (t: EventTarget | null) => t instanceof Element && t.closest("button, a, input, textarea, select, [data-no-copy]") !== null;

  return (
    <div
      {...rest}
      ref={box}
      className={`${styles.hold} ${className ?? ""}`}
      data-held={open ? "" : undefined}
      onPointerDown={(e) => {
        if (e.button !== 0 || fromControl(e.target)) return;
        cancel();
        start.current = { x: e.clientX, y: e.clientY };
        timer.current = setTimeout(() => {
          timer.current = null;
          openMenu();
        }, HOLD_MS);
      }}
      onPointerMove={(e) => {
        const s = start.current;
        if (s && Math.hypot(e.clientX - s.x, e.clientY - s.y) > MOVE_PX) cancel();
      }}
      onPointerUp={cancel}
      onPointerCancel={cancel}
      onPointerLeave={cancel}
      onContextMenu={(e) => {
        // iOS/Android's own callout and a desktop right-click: ours instead (a card keeps the browser's).
        if (fromControl(e.target)) return;
        e.preventDefault();
        cancel();
        openMenu();
      }}
    >
      {children}
      {open && (
        <div className={styles.menu} data-side={side} data-place={open} data-copy-menu="" role="menu">
          <button type="button" role="menuitem" className={`${styles.item} pressable`} autoFocus onClick={() => void doCopy()}>
            {copy.chat.copy}
          </button>
        </div>
      )}
    </div>
  );
}
