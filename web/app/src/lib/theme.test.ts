import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { applyPalette, applyTheme, loadPalette, loadTheme, PALETTE_GROUND, PALETTES, setPalette, setTheme } from "./theme";

function themeMetas() {
  document.head.innerHTML =
    '<meta name="theme-color" media="(prefers-color-scheme: light)" content="#f2f2f5">' +
    '<meta name="theme-color" media="(prefers-color-scheme: dark)" content="#000000">';
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
    expect(contents()).toEqual(["#000000", "#000000"]);
    setTheme("light");
    expect(document.documentElement.dataset.theme).toBe("light");
    expect(contents()).toEqual(["#f2f2f5", "#f2f2f5"]);
  });

  it("system removes attribute", () => {
    setTheme("dark");
    setTheme("system");
    expect(document.documentElement.hasAttribute("data-theme")).toBe(false);
    expect(localStorage.getItem("mp.theme")).toBe("system");
    expect(contents()).toEqual(["#f2f2f5", "#000000"]);
  });

  it("unknown stored value reads as system", () => {
    localStorage.setItem("mp.theme", "purple");
    expect(loadTheme()).toBe("system");
    applyTheme(loadTheme());
    expect(document.documentElement.hasAttribute("data-theme")).toBe(false);
  });
});

describe("palette", () => {
  it("six presets, ink first", () => {
    expect(PALETTES).toEqual(["ink", "paper", "forest", "sea", "sunset", "lavender"]);
  });

  it("applies and persists a palette; ink is no attribute", () => {
    expect(loadPalette()).toBe("ink");
    setPalette("forest");
    expect(document.documentElement.dataset.palette).toBe("forest");
    expect(localStorage.getItem("mp.palette")).toBe("forest");
    expect(loadPalette()).toBe("forest");
    setPalette("ink");
    expect(document.documentElement.hasAttribute("data-palette")).toBe(false);
    expect(localStorage.getItem("mp.palette")).toBe("ink");
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
    setTheme("system");
    expect(contents()).toEqual(["#f2f2f5", "#000000"]);
  });

  it("unknown stored value reads as ink", () => {
    localStorage.setItem("mp.palette", "neon");
    expect(loadPalette()).toBe("ink");
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
    expect(loadPalette()).toBe("ink");
    set.mockRestore();
    get.mockRestore();
  });
});
