// Screen theme on this device (spec 5.5.7, 4.7 `mp.theme`, gap 9). "system" follows the media
// query tokens; "light"/"dark" set :root[data-theme]. With no inline script it is applied by
// _app's first effect, so it may change after the first paint.
export type Theme = "system" | "light" | "dark";

const KEY = "mp.theme";
// The --ground of each token set (tokens.css), for the browser chrome.
const GROUND = { light: "#f2f2f5", dark: "#000000" } as const;

export function loadTheme(): Theme {
  try {
    const v = localStorage.getItem(KEY);
    return v === "light" || v === "dark" || v === "system" ? v : "system";
  } catch {
    return "system";
  }
}

export function applyTheme(t: Theme): void {
  if (typeof document === "undefined") return;
  const root = document.documentElement;
  if (t === "system") delete root.dataset.theme;
  else root.dataset.theme = t;
  // Each theme-color meta answers its own media query; a chosen theme sets them all to its ground.
  document.querySelectorAll<HTMLMetaElement>('meta[name="theme-color"]').forEach((m) => {
    const own = /dark/.test(m.getAttribute("media") ?? "") ? GROUND.dark : GROUND.light;
    m.content = t === "system" ? own : GROUND[t];
  });
}

/** Keep the choice in `mp.theme` and apply it. */
export function setTheme(t: Theme): void {
  try {
    localStorage.setItem(KEY, t);
  } catch {
    // blocked storage: applies for this visit only
  }
  applyTheme(t);
}
