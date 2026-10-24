// Device checks for the first-connect screen (spec 5.5.8). Browser only; call from effects.
export function isIos(): boolean {
  if (typeof navigator === "undefined") return false;
  if (/iP(hone|ad|od)/.test(navigator.userAgent)) return true;
  // iPadOS Safari reports a Mac user agent; touch points tell it apart from a real Mac.
  return /Macintosh/.test(navigator.userAgent) && navigator.maxTouchPoints > 1;
}

export function isStandalone(): boolean {
  if (typeof navigator === "undefined") return false;
  const nav = navigator as Navigator & { standalone?: boolean };
  if (nav.standalone === true) return true;
  return typeof window.matchMedia === "function" && window.matchMedia("(display-mode: standalone)").matches;
}
