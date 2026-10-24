// Screen theme on this device (spec 5.5.7, 4.7 `mp.theme`, gap 9). "system" follows the media
// query tokens; "light"/"dark" set :root[data-theme]. With no inline script it is applied by
// _app's first effect, so it may change after the first paint.
export type Theme = "system" | "light" | "dark";

// Colour preset on this device (`mp.palette`): :root[data-palette], none for ink (the spec 5.2
// tokens). Each has a light and a dark set in tokens.css, so it goes with any theme.
export const PALETTES = ["ink", "paper", "forest", "sea", "sunset", "lavender"] as const;
export type Palette = (typeof PALETTES)[number];

const KEY = "mp.theme";
const PALETTE_KEY = "mp.palette";
// The --ground of each token set (tokens.css), for the browser chrome. contrast.test.ts checks them.
export const PALETTE_GROUND: Record<Palette, { light: string; dark: string }> = {
  ink: { light: "#f2f2f5", dark: "#000000" },
  paper: { light: "#f4f1ea", dark: "#12100d" },
  forest: { light: "#eff3f0", dark: "#040806" },
  sea: { light: "#eef2f6", dark: "#03070b" },
  sunset: { light: "#f7f1ee", dark: "#0b0605" },
  lavender: { light: "#f2f1f7", dark: "#06050a" },
};

export function loadTheme(): Theme {
  try {
    const v = localStorage.getItem(KEY);
    return v === "light" || v === "dark" || v === "system" ? v : "system";
  } catch {
    return "system";
  }
}

export function loadPalette(): Palette {
  try {
    const v = localStorage.getItem(PALETTE_KEY);
    return (PALETTES as readonly string[]).includes(v ?? "") ? (v as Palette) : "ink";
  } catch {
    return "ink";
  }
}

// Each theme-color meta answers its own media query; a chosen theme sets them all to its ground.
function paintChrome(): void {
  const root = document.documentElement;
  const t = root.dataset.theme;
  const ground = PALETTE_GROUND[(root.dataset.palette as Palette | undefined) ?? "ink"] ?? PALETTE_GROUND.ink;
  document.querySelectorAll<HTMLMetaElement>('meta[name="theme-color"]').forEach((m) => {
    const own = /dark/.test(m.getAttribute("media") ?? "") ? ground.dark : ground.light;
    m.content = t === "light" || t === "dark" ? ground[t] : own;
  });
}

export function applyTheme(t: Theme): void {
  if (typeof document === "undefined") return;
  const root = document.documentElement;
  if (t === "system") delete root.dataset.theme;
  else root.dataset.theme = t;
  paintChrome();
}

export function applyPalette(p: Palette): void {
  if (typeof document === "undefined") return;
  const root = document.documentElement;
  if (p === "ink") delete root.dataset.palette;
  else root.dataset.palette = p;
  paintChrome();
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

/** Keep the choice in `mp.palette` and apply it. */
export function setPalette(p: Palette): void {
  try {
    localStorage.setItem(PALETTE_KEY, p);
  } catch {
    // blocked storage: applies for this visit only
  }
  applyPalette(p);
}
