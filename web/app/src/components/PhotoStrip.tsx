import { copy } from "../lib/copy";
import { PhotoImage } from "./PhotoImage";
import styles from "./PhotoStrip.module.css";

/** SP10 7.1: the row of small photos above the memo body (64px squares, scrolls sideways). None: no row. */
export function PhotoStrip({ photos, onOpen }: { photos: { id: number }[]; onOpen(index: number): void }) {
  if (photos.length === 0) return null;
  return (
    <ul className={styles.strip} aria-label={copy.photos.strip}>
      {photos.map((p, i) => (
        <li key={p.id} className={styles.item}>
          <button type="button" className={styles.cell} aria-label={copy.photos.photo(i + 1, photos.length)} onClick={() => onOpen(i)}>
            <PhotoImage id={p.id} size="thumb" className={styles.thumb} />
          </button>
        </li>
      ))}
    </ul>
  );
}
