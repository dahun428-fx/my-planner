import { type PointerEvent, useEffect, useRef } from "react";
import { copy } from "../lib/copy";
import { Icon } from "./icons";
import { PhotoImage } from "./PhotoImage";
import styles from "./PhotoViewer.module.css";

const SWIPE_PX = 40;

/** Where a swipe of `dx` px goes from photo `at` of `n`: the next (left), the previous (right), or nowhere (null). */
export function swipeStep(dx: number, at: number, n: number): number | null {
  if (dx <= -SWIPE_PX && at < n - 1) return at + 1;
  if (dx >= SWIPE_PX && at > 0) return at - 1;
  return null;
}

/**
 * SP10 7.1: one photo over the whole screen. Left and right (a swipe, the arrows, the arrow keys)
 * go through the memo's photos; "메모에서 빼기" only when `onDetach` is given (a screen that can write),
 * and "글자 읽기" (16장) only when `onRead` is given.
 */
export function PhotoViewer({
  photos,
  index,
  onIndex,
  onClose,
  onDetach,
  onRead,
}: {
  photos: { id: number }[];
  /** null: closed. */
  index: number | null;
  onIndex(i: number): void;
  onClose(): void;
  onDetach?: (id: number) => void;
  /** 16장: read the photo shown into the memo (the screen closes the viewer). */
  onRead?: (id: number) => void;
}) {
  const close = useRef<HTMLButtonElement>(null);
  const start = useRef<number | null>(null);
  const layer = useRef<HTMLDivElement>(null);
  const open = index !== null && photos.length > 0;
  const at = open ? Math.min(index, photos.length - 1) : 0;

  useEffect(() => {
    if (open) close.current?.focus();
  }, [open]);
  useEffect(() => {
    if (!open) return;
    // Caught first (capture): over the chat sheet (SP10 7.5), Escape closes the viewer alone, not the
    // sheet under it, and Tab goes round the viewer's own buttons, never to the sheet behind.
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        onClose();
      } else if (e.key === "Tab") {
        e.stopPropagation();
        e.preventDefault();
        const items = [...(layer.current?.querySelectorAll<HTMLElement>("button:not([disabled])") ?? [])];
        if (items.length === 0) return;
        const i = items.indexOf(document.activeElement as HTMLElement);
        const next = e.shiftKey ? (i <= 0 ? items.length - 1 : i - 1) : i === -1 || i === items.length - 1 ? 0 : i + 1;
        items[next].focus();
      } else if (e.key === "ArrowLeft" && at > 0) onIndex(at - 1);
      else if (e.key === "ArrowRight" && at < photos.length - 1) onIndex(at + 1);
    };
    document.addEventListener("keydown", onKey, true);
    return () => document.removeEventListener("keydown", onKey, true);
  }, [open, at, photos.length, onClose, onIndex]);

  if (!open) return null;
  const photo = photos[at];
  const onDown = (e: PointerEvent) => {
    start.current = e.clientX;
  };
  const onUp = (e: PointerEvent) => {
    if (start.current === null) return;
    const dx = e.clientX - start.current;
    start.current = null;
    const to = swipeStep(dx, at, photos.length);
    if (to !== null) onIndex(to);
  };

  return (
    <div ref={layer} className={styles.layer} role="dialog" aria-modal="true" aria-label={copy.photos.viewer}>
      <div className={styles.bar}>
        <button ref={close} type="button" className={styles.icon} onClick={onClose}>
          <Icon name="close" label={copy.photos.close} />
        </button>
        <span className={`tnum ${styles.count}`} aria-label={copy.photos.photo(at + 1, photos.length)}>
          {at + 1}/{photos.length}
        </span>
        <span className={styles.icon} aria-hidden="true" />
      </div>
      <div className={styles.stage} onPointerDown={onDown} onPointerUp={onUp} onPointerCancel={() => (start.current = null)}>
        <PhotoImage key={photo.id} id={photo.id} size="full" className={styles.photo} />
        {at > 0 && (
          <button type="button" className={`${styles.icon} ${styles.prev}`} onClick={() => onIndex(at - 1)}>
            <Icon name="chevron" label={copy.photos.prev} />
          </button>
        )}
        {at < photos.length - 1 && (
          <button type="button" className={`${styles.icon} ${styles.next}`} onClick={() => onIndex(at + 1)}>
            <Icon name="chevron" label={copy.photos.next} />
          </button>
        )}
      </div>
      {(onDetach || onRead) && (
        <div className={styles.foot}>
          {onRead && (
            <button type="button" className={styles.read} onClick={() => onRead(photo.id)}>
              {copy.photos.readText}
            </button>
          )}
          {onDetach && (
            <button type="button" className={styles.detach} onClick={() => onDetach(photo.id)}>
              {copy.photos.detach}
            </button>
          )}
        </div>
      )}
    </div>
  );
}
