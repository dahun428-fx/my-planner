import { copy } from "../../lib/copy";
import type { Tag } from "./types";
import styles from "./primitives.module.css";

/** `tags` (5.3.6): pills that cannot be pressed. An area shows its Korean name, never its own colour. */
export function Tags({ items }: { items: Tag[] }) {
  return (
    <ul className={styles.tags} aria-label={copy.parts.tagsLabel}>
      {items.map((t, i) => (
        <li key={i}>
          <span className={styles.tag}>{"area" in t ? copy.areas[t.area] : t.text}</span>
        </li>
      ))}
    </ul>
  );
}
