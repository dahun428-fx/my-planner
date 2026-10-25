import { readFileSync } from "node:fs";
import { join } from "node:path";
import { screen, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import type { Status as StatusData } from "../api/types.gen";
import { copy } from "../lib/copy";
import statusJson from "../test/fixtures/status.json";
import { renderWithProviders } from "../test/render";
import { BASE, server } from "../test/server";
import { Status } from "./Status";
import { Today } from "./Today";

const status = statusJson as StatusData;

const act = (tasks: number, habit_checks: number, body_days: number) => ({ tasks, habit_checks, body_days });
/** The fixture with its areas set the way spec 10.2 shows them. */
const body: StatusData = {
  ...status,
  stats: status.stats.map((s) => {
    const patch: Record<string, object> = {
      career: { score: 6, bonus: 1.2, effective_score: 7.2, activity: act(12, 0, 0) },
      health: { score: 4, bonus: 1.5, effective_score: 5.5, activity: act(0, 28, 0) },
      learning: { score: null, period: null, bonus: 0.4, effective_score: null, activity: act(2, 0, 0) },
      finance: { bonus: 0, effective_score: 5, activity: act(0, 0, 0) },
      quality_of_life: { bonus: 0, effective_score: 5, activity: act(0, 0, 0) },
    };
    return { ...s, ...patch[s.area] };
  }),
};

const sectionOf = (heading: string) => screen.getByRole("heading", { level: 2, name: heading }).closest("section") as HTMLElement;

function serve(data: StatusData = body) {
  server.use(http.get(`${BASE}/status`, () => HttpResponse.json(data)));
}

describe("Status (spec 10.2)", () => {
  it("renders_level_stats_and_recent_areas", async () => {
    serve();
    renderWithProviders(<Status />, { route: "/status/" });
    expect(await screen.findByRole("heading", { level: 1, name: "상태창" })).toBeInTheDocument();

    // The level line.
    expect(screen.getByText("Lv. 6")).toBeInTheDocument();
    expect(screen.getByText("130 / 400 XP")).toBeInTheDocument();
    const bar = screen.getByRole("img", { name: copy.statusScreen.xpBar(130, 400) });
    expect(bar.querySelectorAll("rect")[1].getAttribute("width")).toBe(String((130 / 400) * 100));

    // The stats: pictogram + name, effective score at the right, base and bonus under the name.
    const stats = sectionOf(copy.statusScreen.statsHeading);
    const rows = within(stats).getAllByRole("listitem");
    expect(rows).toHaveLength(6);
    const health = rows[2];
    expect(health.querySelector("svg.pictogram use")).toHaveAttribute("href", "#p-health");
    expect(health.textContent).toContain("건강");
    expect(health.textContent).toContain("5.5");
    expect(health.textContent).toContain("바탕 4 · 요즘 +1.5");
    expect(rows[1].textContent).toContain("바탕 5"); // finance: no bonus
    expect(rows[1].textContent).not.toContain("요즘");
    const learning = rows[4];
    expect(learning.textContent).toContain("—");
    expect(learning.textContent).toContain("요즘 +0.4 · 분기 회고에서 점수를 정하면 더해져요");

    // 요즘 손이 간 영역: biggest bonus first.
    const recent = sectionOf("요즘 손이 간 영역");
    const lines = within(recent).getAllByRole("listitem");
    expect(lines.map((l) => l.dataset.area)).toEqual(["health", "career", "learning"]);
    expect(lines[0].textContent).toContain("+1.5");
    expect(lines[0].textContent).toContain("4주 동안 습관 28번");
    expect(lines[1].textContent).toContain("4주 동안 할 일 12개");
  });

  it("empty recent areas say what fills them", async () => {
    serve({ ...body, stats: body.stats.map((s) => ({ ...s, bonus: 0, effective_score: s.score })) });
    renderWithProviders(<Status />, { route: "/status/" });
    await screen.findByRole("heading", { name: "요즘 손이 간 영역" });
    const recent = sectionOf("요즘 손이 간 영역");
    expect(within(recent).getByText("4주 안에 끝낸 할 일이나 습관 체크가 생기면 여기에 보여요.")).toBeInTheDocument();
  });

  it("back_link_is_more", async () => {
    // SP9-01 has landed: the back link goes to the more screen, as every screen under it does.
    serve();
    renderWithProviders(<Status />, { route: "/status/" });
    const back = await screen.findByRole("link", { name: "‹ 더보기" });
    expect(back).toHaveAttribute("href", "/more/");
    expect(copy.statusScreen.back).toBe(copy.habits.back);
  });

  it("today_screen_has_no_status_link", async () => {
    renderWithProviders(<Today />);
    await screen.findByRole("heading", { level: 1, name: copy.today.title });
    expect(document.querySelector('a[href*="/status"]')).toBeNull();
  });

  it("offline_shows_notice", async () => {
    server.use(http.get(`${BASE}/status`, () => HttpResponse.error()));
    renderWithProviders(<Status />, { route: "/status/", conn: "offline" });
    expect(await screen.findByText(copy.offline.lead)).toBeInTheDocument();
    expect(screen.getByText("연결되면 상태창을 보여 드릴게요.")).toBeInTheDocument();
    expect(screen.queryByText("Lv. 6")).toBeNull();
  });

  it("css_module_imported_in_app", () => {
    // SP7 9장: every screen's CSS module goes out with _app as one stylesheet.
    const app = readFileSync(join(__dirname, "../pages/_app.tsx"), "utf8");
    expect(app).toMatch(/import "\.\.\/screens\/Status";/);
  });

  it("shows no mark of a falling bonus", async () => {
    serve();
    renderWithProviders(<Status />, { route: "/status/" });
    await screen.findByText("Lv. 6");
    const all = document.body.textContent ?? "";
    for (const mark of ["−", "%", "줄었", "↓"]) expect(all).not.toContain(mark);
  });
});
