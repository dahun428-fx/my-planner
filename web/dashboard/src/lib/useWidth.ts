import { type RefObject, useEffect, useState } from "react";

/**
 * The content width of `ref`, kept up to date with a ResizeObserver. Charts get explicit pixel sizes from
 * this (no ResponsiveContainer). Where nothing can be measured (jsdom, first paint) it is `fallback`.
 */
export function useWidth(ref: RefObject<HTMLElement | null>, fallback = 328): number {
  const [width, setWidth] = useState(fallback);
  useEffect(() => {
    const el = ref.current;
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
  }, [ref]);
  return width;
}
