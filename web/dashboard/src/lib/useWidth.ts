import { useEffect, useState } from "react";

/**
 * The content width of an element, kept up to date with a ResizeObserver. Charts get explicit pixel sizes from
 * this (no ResponsiveContainer). Pass `ref` as the element's callback ref, so an element that appears later
 * (an empty panel that gets data on the next poll) is measured too. Where nothing can be measured (jsdom,
 * first paint) the width is `fallback`.
 */
export function useWidth<T extends HTMLElement>(fallback = 328): { ref: (el: T | null) => void; width: number } {
  const [el, setEl] = useState<T | null>(null);
  const [width, setWidth] = useState(fallback);
  useEffect(() => {
    if (!el) return;
    const read = () => {
      const w = Math.floor(el.clientWidth);
      if (w > 0) setWidth(w);
    };
    read();
    if (typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(read);
    ro.observe(el);
    return () => ro.disconnect();
  }, [el]);
  return { ref: setEl, width };
}
