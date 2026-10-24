import { type KeyboardEvent, useRef } from "react";
import styles from "./PalettePicker.module.css";

export interface PalettePickerProps<T extends string> {
  options: { value: T; label: string }[];
  value: T;
  onChange(v: T): void;
  ariaLabel: string;
}

// A row of colour swatches as a radio group, like Segmented: one tab stop, arrow keys move the
// choice. Each swatch carries data-palette, so tokens.css paints it in that palette's own colours
// (its ground and hue) in the current theme, whatever palette the page has.
export function PalettePicker<T extends string>({ options, value, onChange, ariaLabel }: PalettePickerProps<T>) {
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  const index = Math.max(
    0,
    options.findIndex((o) => o.value === value),
  );

  function onKeyDown(e: KeyboardEvent<HTMLButtonElement>) {
    const step = e.key === "ArrowRight" || e.key === "ArrowDown" ? 1 : e.key === "ArrowLeft" || e.key === "ArrowUp" ? -1 : 0;
    if (step === 0) return;
    e.preventDefault();
    const next = (index + step + options.length) % options.length;
    onChange(options[next].value);
    refs.current[next]?.focus();
  }

  return (
    <div role="radiogroup" aria-label={ariaLabel} className={styles.group}>
      {options.map((o, i) => (
        <button
          key={o.value}
          ref={(el) => {
            refs.current[i] = el;
          }}
          type="button"
          role="radio"
          aria-checked={o.value === value}
          tabIndex={i === index ? 0 : -1}
          className={styles.option}
          onClick={() => onChange(o.value)}
          onKeyDown={onKeyDown}
        >
          <span className={styles.ring} aria-hidden="true">
            <span className={styles.swatch} data-palette={o.value} />
          </span>
          <span className={styles.label}>{o.label}</span>
        </button>
      ))}
    </div>
  );
}
