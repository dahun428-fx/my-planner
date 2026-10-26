import { Icon } from "../components/icons";
import { copy } from "../lib/copy";
import { newClientMsgId } from "../lib/ids";
import styles from "./ChatSheet.module.css";

/** SP10 5.1 / 7.5: photos in one message. */
export const TRAY_MAX = 4;

/** A picked photo, already shrunk (7.2), waiting above the field. `url`: its small photo's blob: address. */
export interface TrayPhoto {
  key: string;
  image: Blob;
  thumb: Blob;
  url: string;
}

/** A tray entry for these bytes, with an address of its own (revoked when it leaves the tray). */
export function trayPhoto(image: Blob, thumb: Blob): TrayPhoto {
  return { key: newClientMsgId(), image, thumb, url: URL.createObjectURL(thumb) };
}

/** SP10 7.5: the photos waiting to be sent, small, above the field; each has a ✕. None: no tray. */
export function PhotoTray({ photos, onRemove, disabled = false }: { photos: TrayPhoto[]; onRemove(key: string): void; disabled?: boolean }) {
  if (photos.length === 0) return null;
  return (
    <ul className={styles.tray} aria-label={copy.chat.tray}>
      {photos.map((p, i) => (
        <li key={p.key} className={styles.trayItem}>
          <img className={styles.trayThumb} src={p.url} alt="" draggable={false} />
          <button
            type="button"
            className={styles.trayRemove}
            aria-label={copy.chat.unpick(i + 1, photos.length)}
            disabled={disabled}
            onClick={() => onRemove(p.key)}
          >
            <Icon name="clear" />
          </button>
        </li>
      ))}
    </ul>
  );
}
