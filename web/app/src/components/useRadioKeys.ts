import { type KeyboardEvent, useRef } from "react";

// The keys of a radio group (Segmented, PalettePicker): one tab stop on the chosen option; arrow
// keys move the choice and wrap, Home and End go to the first and last.
export function useRadioKeys<T>(options: { value: T }[], value: T, onChange: (v: T) => void) {
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  const index = Math.max(
    0,
    options.findIndex((o) => o.value === value),
  );

  function onKeyDown(e: KeyboardEvent<HTMLButtonElement>) {
    const last = options.length - 1;
    let next: number;
    if (e.key === "ArrowRight" || e.key === "ArrowDown") next = index === last ? 0 : index + 1;
    else if (e.key === "ArrowLeft" || e.key === "ArrowUp") next = index === 0 ? last : index - 1;
    else if (e.key === "Home") next = 0;
    else if (e.key === "End") next = last;
    else return;
    e.preventDefault();
    onChange(options[next].value);
    refs.current[next]?.focus();
  }

  const ref = (i: number) => (el: HTMLButtonElement | null) => {
    refs.current[i] = el;
  };
  return { index, onKeyDown, ref };
}
