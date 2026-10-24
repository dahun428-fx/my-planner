import { useRef, useState } from "react";
import type { ButtonItem } from "./types";
import styles from "./primitives.module.css";

/**
 * `buttons` (5.3.8): a row of 44px pills of the same weight. Once a `send` or `complete` press
 * succeeds (`onPress` gives true), every `send` and `complete` pill is off and only the pressed one
 * stays dark (`aria-pressed`), as in ui_choice. `open` is not a write: it works any number of
 * times. A press made while another is in flight is ignored.
 */
export function Buttons({
  items,
  isDisabled,
  onPress,
}: {
  items: ButtonItem[];
  isDisabled(item: ButtonItem): boolean;
  onPress(item: ButtonItem): Promise<boolean> | boolean;
}) {
  const [pressed, setPressed] = useState<number | null>(null);
  const busy = useRef(false);

  const press = async (i: number) => {
    const item = items[i];
    if (busy.current || isDisabled(item)) return;
    if (item.do.kind !== "open" && pressed !== null) return;
    busy.current = true;
    try {
      const ok = await onPress(item);
      if (ok && item.do.kind !== "open") setPressed(i);
    } finally {
      busy.current = false;
    }
  };

  return (
    <div className={styles.buttons}>
      {items.map((item, i) => {
        const opens = item.do.kind === "open";
        return (
          <button
            key={i}
            type="button"
            className={`${styles.pill} pressable`}
            aria-pressed={opens ? undefined : pressed === i}
            disabled={isDisabled(item) || (!opens && pressed !== null)}
            onClick={() => void press(i)}
          >
            {item.label}
          </button>
        );
      })}
    </div>
  );
}
