import { useSyncExternalStore } from "react";

/** DESIGN.md's two-column width: a viewport of 720px and wider is a desktop. */
export const DESKTOP_QUERY = "(min-width: 720px)";

function subscribe(onChange: () => void): () => void {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") return () => {};
  const mq = window.matchMedia(DESKTOP_QUERY);
  mq.addEventListener("change", onChange);
  return () => mq.removeEventListener("change", onChange);
}

const snapshot = () => typeof window === "undefined" || typeof window.matchMedia !== "function" || !window.matchMedia(DESKTOP_QUERY).matches;

/** True below 720px of viewport. Where `matchMedia` is missing (jsdom) it is a phone. */
export function useIsPhone(): boolean {
  return useSyncExternalStore(subscribe, snapshot, () => true);
}
