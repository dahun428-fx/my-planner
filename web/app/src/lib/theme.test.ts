import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { applyPalette, applyTheme, loadPalette, loadTheme, PALETTE_GROUND, PALETTES, setPalette, setTheme } from "./theme";

function themeMetas() {
  document.head.innerHTML =
    '<meta name="theme-color" media="(prefers-color-scheme: light)" content="#f6f3ec">' +
    '<meta name="theme-color" media="(prefers-color-scheme: dark)" content="#12110f">';
}
const contents = () => [...document.querySelectorAll('meta[name="theme-color"]')].map((m) => m.getAttribute("content"));

beforeEach(themeMetas);
afterEach(() => {
  delete document.documentElement.dataset.theme;
  delete document.documentElement.dataset.palette;
  document.head.innerHTML = "";
});

describe("theme", () => {
  it("applies and persists theme", () => {
    expect(loadTheme()).toBe("system");
    setTheme("dark");
    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(localStorage.getItem("mp.theme")).toBe("dark");
    expect(loadTheme()).toBe("dark");
    expect(contents()).toEqual(["#12110f", "#12110f"]);
    setTheme("light");
    expect(document.documentElement.dataset.theme).toBe("light");
    expect(contents()).toEqual(["#f6f3ec", "#f6f3ec"]);
  });

  it("system removes attribute", () => {
    setTheme("dark");
    setTheme("system");
    expect(document.documentElement.hasAttribute("data-theme")).toBe(false);
    expect(localStorage.getItem("mp.theme")).toBe("system");
    expect(contents()).toEqual(["#f6f3ec", "#12110f"]);
  });

  it("unknown stored value reads as system", () => {
    localStorage.setItem("mp.theme", "purple");
    expect(loadTheme()).toBe("system");
    applyTheme(loadTheme());
    expect(document.documentElement.hasAttribute("data-theme")).toBe(false);
  });
});

describe("palette", () => {
  // DESIGN.md: paper is the default (no attribute); ink is a preset like the others.
  it("six presets, paper first", () => {
    expect(PALETTES).toEqual(["paper", "ink", "forest", "sea", "sunset", "lavender"]);
    expect(PALETTE_GROUND.paper).toEqual({ light: "#f6f3ec", dark: "#12110f" });
    expect(PALETTE_GROUND.ink).toEqual({ light: "#f2f2f5", dark: "#000000" });
  });

  it("applies and persists a palette; paper is no attribute", () => {
    expect(loadPalette()).toBe("paper");
    setPalette("forest");
    expect(document.documentElement.dataset.palette).toBe("forest");
    expect(localStorage.getItem("mp.palette")).toBe("forest");
    expect(loadPalette()).toBe("forest");
    setPalette("ink");
    expect(document.documentElement.dataset.palette).toBe("ink");
    expect(localStorage.getItem("mp.palette")).toBe("ink");
    setPalette("paper");
    expect(document.documentElement.hasAttribute("data-palette")).toBe(false);
    expect(localStorage.getItem("mp.palette")).toBe("paper");
  });

  it("theme-color metas follow the palette's ground in each theme", () => {
    const sea = PALETTE_GROUND.sea;
    setPalette("sea");
    expect(contents()).toEqual([sea.light, sea.dark]);
    setTheme("dark");
    expect(contents()).toEqual([sea.dark, sea.dark]);
    setTheme("light");
    expect(contents()).toEqual([sea.light, sea.light]);
    setPalette("ink");
    expect(contents()).toEqual(["#f2f2f5", "#f2f2f5"]);
    setPalette("paper");
    expect(contents()).toEqual(["#f6f3ec", "#f6f3ec"]);
    setTheme("system");
    expect(contents()).toEqual(["#f6f3ec", "#12110f"]);
  });

  it("unknown stored value reads as paper", () => {
    localStorage.setItem("mp.palette", "neon");
    expect(loadPalette()).toBe("paper");
    applyPalette(loadPalette());
    expect(document.documentElement.hasAttribute("data-palette")).toBe(false);
  });

  it("blocked storage still applies for this visit", () => {
    const set = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    const get = vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    setPalette("lavender");
    expect(document.documentElement.dataset.palette).toBe("lavender");
    expect(loadPalette()).toBe("paper");
    set.mockRestore();
    get.mockRestore();
  });
});
