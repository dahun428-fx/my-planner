import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { copy } from "../lib/copy";
import { HAS_STATUS_PAGE } from "../lib/nav";
import { renderWithProviders } from "../test/render";
import MorePage from "../pages/more";
import { More } from "./More";

const rows = () =>
  within(screen.getByRole("main"))
    .getAllByRole("link")
    .map((a) => [a.textContent, a.getAttribute("href")]);

describe("More (spec 9.1)", () => {
  it("large title, no back link, rows in order", () => {
    renderWithProviders(<More hasStatus />, { route: "/more/" });
    expect(screen.getByRole("heading", { level: 1, name: "더보기" })).toBeInTheDocument();
    expect(rows()).toEqual([
      ["설정", "/settings/"],
      ["기록", "/activity/"],
      ["습관", "/habits/"],
      ["상태창", "/status/"],
      ["기기 연결", "/connect/"],
    ]);
    expect(screen.queryByRole("link", { name: copy.more.back })).toBeNull();
  });

  it("no status row while /status/ is not in the build", () => {
    expect(HAS_STATUS_PAGE).toBe(false);
    renderWithProviders(<More />, { route: "/more/" });
    expect(rows().map(([t]) => t)).toEqual(["설정", "기록", "습관", "기기 연결"]);
  });

  it("the page shows the tab bar with no tab marked", () => {
    renderWithProviders(<MorePage />, { route: "/more/" });
    const nav = screen.getByRole("navigation", { name: copy.tabs.navLabel });
    const links = within(nav).getAllByRole("link");
    expect(links).toHaveLength(4);
    for (const a of links) expect(a).not.toHaveAttribute("aria-current");
  });
});
