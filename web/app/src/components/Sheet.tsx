import {
  type PointerEvent as ReactPointerEvent,
  type ReactNode,
  type RefObject,
  useEffect,
  useId,
  useRef,
  useState,
} from "react";
import styles from "./Sheet.module.css";

export interface SheetProps {
  open: boolean;
  onClose: () => void;
  title?: string;
  /** Accessible name when the sheet draws its own heading instead of `title`. */
  ariaLabel?: string;
  /** Full height (the screen less 50px at the top, spec 5.5.2); the children lay out the body. */
  tall?: boolean;
  children: ReactNode;
  /** Element that gets focus back on close; defaults to whatever had focus when the sheet opened. */
  returnFocusTo?: RefObject<HTMLElement | null>;
}

const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';
const CLOSE_DRAG_PX = 120;
const EXIT_MS = 280;

// No animation where motion is reduced (or cannot be asked about): the sheet just goes.
const motionOk = () =>
  typeof window !== "undefined" && typeof window.matchMedia === "function" && !window.matchMedia("(prefers-reduced-motion: reduce)").matches;

// Bottom sheet (spec 5.1, 5.5.2, 9장): focus moves inside on open and back on close. Slides up and
// down 280ms with transform only; dragging the handle down more than 120px closes it (the moving
// value goes to the panel through CSSOM, never a style attribute).
export function Sheet({ open, onClose, title, ariaLabel, tall = false, children, returnFocusTo }: SheetProps) {
  const panel = useRef<HTMLDivElement>(null);
  const titleId = useId();
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;
  const [mounted, setMounted] = useState(open);
  const [closing, setClosing] = useState(false);
  const drag = useRef<{ id: number; y: number } | null>(null);

  useEffect(() => {
    if (open) {
      setMounted(true);
      setClosing(false);
      if (panel.current) panel.current.style.transform = "";
      return;
    }
    if (!mounted) return;
    if (!motionOk()) {
      setMounted(false);
      return;
    }
    setClosing(true);
    const fallback = setTimeout(() => {
      setMounted(false);
      setClosing(false);
    }, EXIT_MS + 120);
    return () => clearTimeout(fallback);
  }, [open, mounted]);

  // The exit ends with the panel's own animation (a native listener: React's name for the event
  // depends on the browser's prefixes).
  const leaving = !open && closing;
  useEffect(() => {
    const el = panel.current;
    if (!leaving || !el) return;
    const done = (e: AnimationEvent) => {
      if (e.target !== el) return;
      setMounted(false);
      setClosing(false);
    };
    el.addEventListener("animationend", done);
    return () => el.removeEventListener("animationend", done);
  }, [leaving]);

  useEffect(() => {
    if (!open) return;
    const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const el = panel.current;
    (el?.querySelector<HTMLElement>(FOCUSABLE) ?? el)?.focus();

    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        onCloseRef.current();
      } else if (e.key === "Tab" && el) {
        const items = [...el.querySelectorAll<HTMLElement>(FOCUSABLE)];
        if (items.length === 0) {
          e.preventDefault();
          return;
        }
        const first = items[0];
        const last = items[items.length - 1];
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      }
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      (returnFocusTo?.current ?? opener)?.focus();
    };
  }, [open, returnFocusTo]);

  const place = (px: number | null) => {
    const el = panel.current;
    if (!el) return;
    el.classList.toggle(styles.dragging, px !== null);
    el.style.transform = px === null ? "" : `translateY(${px}px)`;
  };

  const onDown = (e: ReactPointerEvent<HTMLDivElement>) => {
    if (!open || (e.pointerType === "mouse" && e.button !== 0)) return;
    drag.current = { id: e.pointerId, y: e.clientY };
    try {
      e.currentTarget.setPointerCapture?.(e.pointerId);
    } catch {
      // capture is a nicety
    }
  };
  const onMove = (e: ReactPointerEvent<HTMLDivElement>) => {
    const d = drag.current;
    if (!d || d.id !== e.pointerId) return;
    place(Math.max(0, e.clientY - d.y));
  };
  const onUp = (e: ReactPointerEvent<HTMLDivElement>) => {
    const d = drag.current;
    if (!d || d.id !== e.pointerId) return;
    drag.current = null;
    if (e.clientY - d.y > CLOSE_DRAG_PX) {
      panel.current?.classList.remove(styles.dragging);
      onCloseRef.current();
    } else {
      place(null);
    }
  };
  const onCancel = () => {
    drag.current = null;
    place(null);
  };

  if (!open && !mounted) return null;
  return (
    <div className={`${styles.layer} ${leaving ? styles.leaving : ""}`}>
      <div className={styles.backdrop} aria-hidden="true" onClick={open ? onClose : undefined} />
      <div
        ref={panel}
        className={`${styles.panel} ${tall ? styles.tall : ""} ${leaving ? styles.closing : ""}`}
        role="dialog"
        aria-modal="true"
        aria-labelledby={title ? titleId : undefined}
        aria-label={title ? undefined : ariaLabel}
        tabIndex={-1}
      >
        <div
          className={styles.grab}
          data-sheet-handle=""
          aria-hidden="true"
          onPointerDown={onDown}
          onPointerMove={onMove}
          onPointerUp={onUp}
          onPointerCancel={onCancel}
        >
          <div className={styles.handle} />
        </div>
        {title && (
          <h2 id={titleId} className={styles.title}>
            {title}
          </h2>
        )}
        <div className={styles.body}>{children}</div>
      </div>
    </div>
  );
}
