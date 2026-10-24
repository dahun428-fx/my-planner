import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { applyTheme, loadTheme, setTheme } from "./theme";

function themeMetas() {
  document.head.innerHTML =
    '<meta name="theme-color" media="(prefers-color-scheme: light)" content="#f2f2f5">' +
    '<meta name="theme-color" media="(prefers-color-scheme: dark)" content="#000000">';
}
const contents = () => [...document.querySelectorAll('meta[name="theme-color"]')].map((m) => m.getAttribute("content"));

beforeEach(themeMetas);
afterEach(() => {
  delete document.documentElement.dataset.theme;
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
