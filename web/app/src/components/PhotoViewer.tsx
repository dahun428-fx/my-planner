import { type PointerEvent, useEffect, useRef } from "react";
import { copy } from "../lib/copy";
import { Icon } from "./icons";
import { PhotoImage } from "./PhotoImage";
import styles from "./PhotoViewer.module.css";

const SWIPE_PX = 40;

/**
 * SP10 7.1: one photo over the whole screen. Left and right (a swipe, the arrows, the arrow keys)
 * go through the memo's photos; "메모에서 빼기" only when `onDetach` is given (a screen that can write).
 */
export function PhotoViewer({
  photos,
  index,
  onIndex,
  onClose,
  onDetach,
}: {
  photos: { id: number }[];
  /** null: closed. */
  index: number | null;
  onIndex(i: number): void;
  onClose(): void;
  onDetach?: (id: number) => void;
}) {
  const close = useRef<HTMLButtonElement>(null);
  const start = useRef<number | null>(null);
  const open = index !== null && photos.length > 0;
  const at = open ? Math.min(index, photos.length - 1) : 0;

  useEffect(() => {
    if (open) close.current?.focus();
  }, [open]);
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
      else if (e.key === "ArrowLeft" && at > 0) onIndex(at - 1);
      else if (e.key === "ArrowRight" && at < photos.length - 1) onIndex(at + 1);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
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
    if (dx <= -SWIPE_PX && at < photos.length - 1) onIndex(at + 1);
    else if (dx >= SWIPE_PX && at > 0) onIndex(at - 1);
  };

  return (
    <div className={styles.layer} role="dialog" aria-modal="true" aria-label={copy.photos.viewer}>
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
      {onDetach && (
        <div className={styles.foot}>
          <button type="button" className={styles.detach} onClick={() => onDetach(photo.id)}>
            {copy.photos.detach}
          </button>
        </div>
      )}
    </div>
  );
}
