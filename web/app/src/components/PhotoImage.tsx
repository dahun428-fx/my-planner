import { useEffect, useState } from "react";
import { photoBlobUrl } from "../api/photos";
import { useConnection } from "../lib/ConnectionProvider";
import { cachedPhoto, holdPhoto, type PhotoSize, photoKey } from "../lib/photoCache";
import styles from "./PhotoStrip.module.css";

/**
 * One photo from its blob: address (SP10 7.3). Until it is had, and when it cannot be had (offline,
 * a missing file), the place is a grey cell.
 */
export function PhotoImage({ id, size, className }: { id: number; size: PhotoSize; className?: string }) {
  const { conn } = useConnection();
  const beUrl = conn?.beUrl ?? null;
  const token = conn?.token ?? null;
  const [url, setUrl] = useState<string | null>(() => (beUrl ? cachedPhoto(photoKey(beUrl, id, size)) : null));

  useEffect(() => {
    if (!beUrl || !token) return;
    let live = true;
    let release = () => {};
    void photoBlobUrl({ beUrl, token }, id, size).then((u) => {
      if (!live) return;
      if (u) release = holdPhoto(photoKey(beUrl, id, size));
      setUrl(u);
    });
    return () => {
      live = false;
      release();
    };
  }, [beUrl, token, id, size]);

  if (!url) return <span className={`${styles.empty} ${className ?? ""}`} data-photo={id} aria-hidden="true" />;
  return <img className={className} src={url} alt="" data-photo={id} draggable={false} />;
}
