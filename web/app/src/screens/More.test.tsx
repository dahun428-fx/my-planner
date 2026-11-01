import { screen, waitFor, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import health from "../test/fixtures/health.json";
import { BASE, server } from "../test/server";
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
      ["연결된 기기", "/devices/"],
    ]);
    expect(screen.queryByRole("link", { name: copy.more.back })).toBeNull();
  });

  it("lists the status row once /status/ is in the build (SP8-02)", () => {
    expect(HAS_STATUS_PAGE).toBe(true);
    renderWithProviders(<More />, { route: "/more/" });
    expect(rows().map(([t]) => t)).toEqual(["설정", "기록", "습관", "상태창", "기기 연결", "연결된 기기"]);
  });

  it("leaves the status row out when told the build has no /status/", () => {
    renderWithProviders(<More hasStatus={false} />, { route: "/more/" });
    expect(rows().map(([t]) => t)).toEqual(["설정", "기록", "습관", "기기 연결", "연결된 기기"]);
  });

  it("workout row only with mate feature", async () => {
    server.use(http.get(`${BASE}/health`, () => HttpResponse.json({ ...health, features: ["mate"] })));
    renderWithProviders(<More hasStatus={false} />, { route: "/more/" });
    expect(await screen.findByRole("link", { name: copy.more.workout })).toHaveAttribute("href", "/workout/");
    expect(rows().map(([t]) => t)).toEqual(["설정", "기록", "습관", "운동", "기기 연결", "연결된 기기"]);
  });

  it("no workout row without the mate feature", async () => {
    let healthReads = 0;
    server.use(http.get(`${BASE}/health`, () => (healthReads++, HttpResponse.json(health))));
    renderWithProviders(<More hasStatus={false} />, { route: "/more/" });
    await screen.findByRole("link", { name: "기기 연결" });
    await waitFor(() => expect(healthReads).toBeGreaterThan(0)); // /health has answered
    expect(rows().map(([t]) => t)).not.toContain(copy.more.workout);
  });

  it("offline cold start keeps the workout row once the mate was seen", async () => {
    localStorage.setItem("mp.mate", "1");
    renderWithProviders(<More hasStatus={false} />, { route: "/more/", conn: "offline" });
    expect(await screen.findByRole("link", { name: copy.more.workout })).toBeInTheDocument();
  });

  // SP14 10장: "비서 메모" opens in place (no page), the last 7 days of the partners' notes.
  describe("agent notes row", () => {
    const withNotes = (notes: unknown[]) => {
      const reads: string[] = [];
      server.use(
        http.get(`${BASE}/health`, () => HttpResponse.json({ ...health, features: ["mate", "agent_notes"] })),
        http.get(`${BASE}/agents/notes`, ({ request }) => {
          reads.push(new URL(request.url).search);
          return HttpResponse.json({ notes });
        }),
      );
      return reads;
    };
    const note = (id: number, agent: "mate" | "manager", text: string, day: string) => ({
      id,
      agent,
      text,
      day,
      priority: 2,
      created_at: `${day}T12:00:00Z`,
      shown_at: null,
    });

    it("comes after the workout row and lists the notes when pressed", async () => {
      const reads = withNotes([note(2, "mate", "가짜 관찰 하나예요.", "2026-10-31"), note(1, "manager", "가짜 관찰 둘이에요.", "2026-10-29")]);
      renderWithProviders(<More hasStatus={false} />, { route: "/more/" });
      const row = await screen.findByRole("button", { name: copy.more.agentNotes });
      expect(row).toHaveAttribute("aria-expanded", "false");
      const workout = screen.getByRole("link", { name: copy.more.workout });
      expect(Boolean(workout.compareDocumentPosition(row) & Node.DOCUMENT_POSITION_FOLLOWING)).toBe(true);
      await userEvent.setup().click(row);
      expect(row).toHaveAttribute("aria-expanded", "true");
      const first = (await screen.findByText("가짜 관찰 하나예요.")).closest("li")!;
      expect(first.querySelector('use[href="#p-dumbbell"]')).not.toBeNull();
      expect(within(first).getByText(copy.agentNames.mate)).toBeInTheDocument();
      expect(within(first).getByText("10/31")).toBeInTheDocument();
      const second = screen.getByText("가짜 관찰 둘이에요.").closest("li")!;
      expect(second.querySelector('use[href="#p-compass"]')).not.toBeNull();
      expect(within(second).getByText(copy.agentNames.manager)).toBeInTheDocument();
      expect(reads).toEqual(["?days=7"]);
      expect(screen.getByRole("link", { name: "기기 연결" })).toBeInTheDocument(); // still the same page
    });

    it("says so when there are none", async () => {
      withNotes([]);
      renderWithProviders(<More hasStatus={false} />, { route: "/more/" });
      await userEvent.setup().click(await screen.findByRole("button", { name: copy.more.agentNotes }));
      expect(await screen.findByText(copy.more.agentNotesEmpty)).toBeInTheDocument();
    });

    it("no row without the feature", async () => {
      server.use(http.get(`${BASE}/health`, () => HttpResponse.json({ ...health, features: ["mate"] })));
      renderWithProviders(<More hasStatus={false} />, { route: "/more/" });
      await screen.findByRole("link", { name: copy.more.workout });
      expect(screen.queryByRole("button", { name: copy.more.agentNotes })).toBeNull();
    });
  });

  it("the page shows the tab bar with no tab marked", () => {
    renderWithProviders(<MorePage />, { route: "/more/" });
    const nav = screen.getByRole("navigation", { name: copy.tabs.navLabel });
    const links = within(nav).getAllByRole("link");
    expect(links).toHaveLength(4);
    for (const a of links) expect(a).not.toHaveAttribute("aria-current");
  });
});
