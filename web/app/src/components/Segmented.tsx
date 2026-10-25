import styles from "./Segmented.module.css";
import { useRadioKeys } from "./useRadioKeys";

export interface SegmentedProps<T extends string> {
  options: { value: T; label: string }[];
  value: T;
  onChange(v: T): void;
  ariaLabel: string;
  disabled?: boolean;
}

// Segmented control as a radio group: one tab stop, arrow keys (and Home/End) move the choice.
export function Segmented<T extends string>({ options, value, onChange, ariaLabel, disabled }: SegmentedProps<T>) {
  const { index, onKeyDown, ref } = useRadioKeys(options, value, onChange);

  return (
    <div role="radiogroup" aria-label={ariaLabel} className={styles.group}>
      {options.map((o, i) => (
        <button
          key={o.value}
          ref={ref(i)}
          type="button"
          role="radio"
          aria-checked={o.value === value}
          tabIndex={i === index ? 0 : -1}
          className={styles.option}
          disabled={disabled}
          onClick={() => onChange(o.value)}
          onKeyDown={onKeyDown}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}
