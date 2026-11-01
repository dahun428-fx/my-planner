import { useId } from "react";
import styles from "./Segmented.module.css";
import { useRadioKeys } from "./useRadioKeys";

export interface SegmentedProps<T extends string> {
  /** `hint`: a small line under the label (SP14 "새로 본 것 n개"); the radio's name stays the label, the hint describes it. */
  options: { value: T; label: string; hint?: string }[];
  value: T;
  onChange(v: T): void;
  ariaLabel: string;
  disabled?: boolean;
}

// Segmented control as a radio group: one tab stop, arrow keys (and Home/End) move the choice.
export function Segmented<T extends string>({ options, value, onChange, ariaLabel, disabled }: SegmentedProps<T>) {
  const { index, onKeyDown, ref } = useRadioKeys(options, value, onChange);
  const id = useId();

  return (
    <div role="radiogroup" aria-label={ariaLabel} className={styles.group}>
      {options.map((o, i) => {
        const hintId = o.hint ? `${id}-${i}-hint` : undefined;
        return (
          <button
            key={o.value}
            ref={ref(i)}
            type="button"
            role="radio"
            aria-checked={o.value === value}
            aria-describedby={hintId}
            tabIndex={i === index ? 0 : -1}
            className={`${styles.option} ${o.hint ? styles.hinted : ""}`}
            disabled={disabled}
            onClick={() => onChange(o.value)}
            onKeyDown={onKeyDown}
          >
            {/* The hint is out of the name (aria-hidden) and back as the description (aria-describedby). */}
            {o.hint ? (
              <>
                <span>{o.label}</span>
                <span id={hintId} className={styles.hint} aria-hidden="true">
                  {o.hint}
                </span>
              </>
            ) : (
              o.label
            )}
          </button>
        );
      })}
    </div>
  );
}
