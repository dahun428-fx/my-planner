import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { copy } from "../lib/copy";
import ActivityPage from "../pages/activity";
import { renderWithProviders } from "../test/render";
import { TabBar } from "./TabBar";

describe("TabBar", () => {
  it("marks current tab", () => {
    renderWithProviders(<TabBar current="todos" />);
    const nav = screen.getByRole("navigation");
    const current = within(nav)
      .getAllByRole("link")
      .filter((a) => a.getAttribute("aria-current") === "page");
    expect(current).toHaveLength(1);
    expect(current[0]).toHaveTextContent(copy.tabs.todos);
    for (const label of [copy.tabs.today, copy.tabs.todos, copy.tabs.memos, copy.tabs.settings]) {
      expect(within(nav).getByRole("link", { name: label })).toBeInTheDocument();
    }
  });

  it("tabs are links", () => {
    renderWithProviders(<TabBar current="today" />);
    const hrefs = screen.getAllByRole("link").map((a) => a.getAttribute("href"));
    expect(hrefs).toEqual(["/", "/todos/", "/memos/", "/settings/"]);
  });

  it("tabs are today, todos, memos, settings (SP9-04: memos takes the activity slot; settings leaves in SP9-07)", () => {
    renderWithProviders(<TabBar current="memos" />);
    const links = within(screen.getByRole("navigation")).getAllByRole("link");
    expect(links.map((a) => a.textContent)).toEqual(["오늘", "할 일", "메모", "설정"]);
    expect(links[2]).toHaveAttribute("aria-current", "page");
  });

  it("without a current tab no tab is marked (spec 9.1: /more/ and the screens under it)", () => {
    renderWithProviders(<TabBar />);
    for (const a of screen.getAllByRole("link")) expect(a).not.toHaveAttribute("aria-current");
  });

  it("the activity page is off the tabs: no tab marked", () => {
    renderWithProviders(<ActivityPage />, { route: "/activity/" });
    const nav = screen.getByRole("navigation", { name: copy.tabs.navLabel });
    for (const a of within(nav).getAllByRole("link")) expect(a).not.toHaveAttribute("aria-current");
  });
});
