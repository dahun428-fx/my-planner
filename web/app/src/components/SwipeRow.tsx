import { type PointerEvent as ReactPointerEvent, type ReactNode, useEffect, useRef, useState } from "react";
import styles from "./SwipeRow.module.css";
import { Sheet } from "./Sheet";

export interface SwipeAction {
  label: string;
  tone: "neutral" | "negative";
  onPress(): void;
}

const SLOP_PX = 8;
const OPEN_PX = 40;
const LONG_PRESS_MS = 500;
const BUTTON_REM = 5;
const HIDE_FALLBACK_MS = 260;

// One source for the drag limit and the resting position: the root font size in px (16 when unknown).
function remPx(): number {
  const v = parseFloat(getComputedStyle(document.documentElement).fontSize);
  return Number.isFinite(v) && v > 0 ? v : 16;
}

// Spec 5.5.5/9장: swipe left to show the row's actions; a long press (or the context menu) opens the
// same actions in a sheet for people who cannot swipe. The moving value goes straight to the DOM
// through a ref (no style attribute, so the CSP stays strict).
export function SwipeRow({
  actions,
  disabled,
  menuTitle,
  onLongPress,
  moreLabel,
  menuExtra = [],
  children,
}: {
  actions: SwipeAction[];
  disabled: boolean;
  menuTitle?: string;
  onLongPress?: () => void;
  /** Accessible name of the keyboard button that opens the same menu as a long press. */
  moreLabel?: string;
  /** Actions that only the menu offers (they have no swipe button). */
  menuExtra?: SwipeAction[];
  children: ReactNode;
}) {
  const surface = useRef<HTMLDivElement>(null);
  const [showActions, setShowActions] = useState(false);
  const [open, setOpen] = useState(false);
  const [menu, setMenu] = useState(false);
  const gesture = useRef<{ x: number; y: number; dragging: boolean; active: boolean } | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const swallowClick = useRef(false);
  const hideTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const off = disabled || actions.length === 0;

  const place = (value: string, animate: boolean) => {
    const el = surface.current;
    if (!el) return;
    el.classList.toggle(styles.animate, animate);
    el.style.transform = value;
  };
  const clearTimer = () => {
    if (timer.current) clearTimeout(timer.current);
    timer.current = null;
  };
  const clearHide = () => {
    if (hideTimer.current) clearTimeout(hideTimer.current);
    hideTimer.current = null;
  };
  // The buttons stay mounted while the row slides back, so the strip is never blank mid-slide.
  const close = () => {
    place("translateX(0)", true);
    setOpen(false);
    clearHide();
    hideTimer.current = setTimeout(() => setShowActions(false), HIDE_FALLBACK_MS);
  };

  useEffect(
    () => () => {
      clearTimer();
      clearHide();
    },
    [],
  );
  useEffect(() => {
    if (off) {
      clearTimer();
      clearHide();
      place("translateX(0)", false);
      setOpen(false);
      setShowActions(false);
      setMenu(false);
    }
  }, [off]);

  const onDown = (e: ReactPointerEvent<HTMLDivElement>) => {
    if (off || (e.pointerType === "mouse" && e.button !== 0)) return;
    swallowClick.current = false;
    clearHide();
    gesture.current = { x: e.clientX, y: e.clientY, dragging: false, active: true };
    clearTimer();
    timer.current = setTimeout(() => {
      timer.current = null;
      if (!gesture.current?.active || gesture.current.dragging) return;
      gesture.current.active = false;
      swallowClick.current = true;
      setMenu(true);
      onLongPress?.();
    }, LONG_PRESS_MS);
  };

  const onMove = (e: ReactPointerEvent<HTMLDivElement>) => {
    const g = gesture.current;
    if (!g?.active) return;
    const dx = e.clientX - g.x;
    const dy = e.clientY - g.y;
    if (!g.dragging) {
      if (Math.abs(dx) < SLOP_PX && Math.abs(dy) < SLOP_PX) return;
      clearTimer();
      if (Math.abs(dy) > Math.abs(dx)) {
        g.active = false; // a vertical scroll, not a swipe
        return;
      }
      g.dragging = true;
      setShowActions(true);
      try {
        e.currentTarget.setPointerCapture?.(e.pointerId);
      } catch {
        // capture is a nicety
      }
    }
    const limit = BUTTON_REM * remPx() * actions.length;
    const px = Math.min(0, Math.max(-limit, (open ? -limit : 0) + dx));
    place(`translateX(${px}px)`, false);
  };

  const onUp = (e: ReactPointerEvent<HTMLDivElement>) => {
    const g = gesture.current;
    clearTimer();
    gesture.current = null;
    if (!g?.dragging) return;
    swallowClick.current = true;
    setTimeout(() => (swallowClick.current = false), 0);
    const dx = e.clientX - g.x;
    const reveal = open ? dx < OPEN_PX : dx < -OPEN_PX;
    if (reveal) {
      place(`translateX(-${BUTTON_REM * remPx() * actions.length}px)`, true);
      setOpen(true);
    } else {
      close();
    }
  };

  const onCancel = () => {
    clearTimer();
    gesture.current = null;
  };

  const onClickCapture = (e: React.MouseEvent) => {
    if (swallowClick.current) {
      swallowClick.current = false;
      e.preventDefault();
      e.stopPropagation();
    } else if (open) {
      e.preventDefault();
      e.stopPropagation();
      close();
    }
  };

  const press = (a: SwipeAction) => {
    setMenu(false);
    close();
    a.onPress();
  };

  return (
    <div className={styles.wrap}>
      {showActions && !off && (
        <div className={styles.actions}>
          {actions.map((a) => (
            <button
              key={a.label}
              type="button"
              className={`${styles.action} ${a.tone === "negative" ? styles.negative : ""}`}
              onClick={() => press(a)}
            >
              {a.label}
            </button>
          ))}
        </div>
      )}
      <div
        ref={surface}
        className={styles.surface}
        onPointerDown={onDown}
        onPointerMove={onMove}
        onPointerUp={onUp}
        onPointerCancel={onCancel}
        onClickCapture={onClickCapture}
        onTransitionEnd={() => {
          if (!open && !gesture.current?.dragging) {
            clearHide();
            setShowActions(false);
          }
        }}
        onContextMenu={(e) => {
          if (off) return;
          e.preventDefault();
          clearTimer();
          setMenu(true);
        }}
      >
        {children}
        {moreLabel && !off && (
          <button type="button" className={styles.more} aria-label={moreLabel} onClick={() => setMenu(true)}>
            <span aria-hidden="true">…</span>
          </button>
        )}
      </div>
      <Sheet open={menu && !off} onClose={() => setMenu(false)} title={menuTitle}>
        <div className={styles.menu}>
          {[...actions, ...menuExtra].map((a) => (
            <button
              key={a.label}
              type="button"
              className={`${styles.menuItem} ${a.tone === "negative" ? styles.negativeText : ""}`}
              onClick={() => press(a)}
            >
              {a.label}
            </button>
          ))}
        </div>
      </Sheet>
    </div>
  );
}
