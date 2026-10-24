import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { copy } from "../lib/copy";
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
    for (const label of [copy.tabs.today, copy.tabs.todos, copy.tabs.activity, copy.tabs.settings]) {
      expect(within(nav).getByRole("link", { name: label })).toBeInTheDocument();
    }
  });

  it("tabs are links", () => {
    renderWithProviders(<TabBar current="today" />);
    const hrefs = screen.getAllByRole("link").map((a) => a.getAttribute("href"));
    expect(hrefs).toEqual(["/", "/todos/", "/activity/", "/settings/"]);
  });
});
