import { readFileSync } from "node:fs";
import { join } from "node:path";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
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

const act = (tasks: number, habit_checks: number, body_days: number) => ({ tasks, habit_checks, body_days, workout_days: 0 });
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

  it("no_score_and_no_bonus_still_hints_at_the_review", async () => {
    serve({ ...body, stats: body.stats.map((s) => (s.area === "finance" ? { ...s, score: null, period: null, bonus: 0, effective_score: null } : s)) });
    renderWithProviders(<Status />, { route: "/status/" });
    await screen.findByRole("heading", { level: 1, name: "상태창" });
    const finance = within(sectionOf(copy.statusScreen.statsHeading))
      .getAllByRole("listitem")
      .find((r) => r.dataset.area === "finance")!;
    expect(within(finance).getByText("분기 회고에서 점수를 정하면 더해져요")).toBeInTheDocument();
    expect(finance.textContent).not.toContain("요즘");
  });

  it("empty recent areas say what fills them", async () => {
    serve({ ...body, stats: body.stats.map((s) => ({ ...s, bonus: 0, effective_score: s.score })) });
    renderWithProviders(<Status />, { route: "/status/" });
    await screen.findByRole("heading", { name: "요즘 손이 간 영역" });
    const recent = sectionOf("요즘 손이 간 영역");
    expect(within(recent).getByText("4주 안에 끝낸 할 일이나 습관 체크가 생기면 여기에 보여요.")).toBeInTheDocument();
  });

  it("shows_moments_block_and_refreshes_after_hide", async () => {
    let hidden = false;
    server.use(
      http.get(`${BASE}/status`, () =>
        HttpResponse.json(hidden ? { ...body, moments: body.moments.slice(1), moments_hidden: 2 } : body),
      ),
      http.post(`${BASE}/actions`, () => {
        hidden = true;
        return HttpResponse.json({ status: "applied", activity_id: 5, undo_id: 6, result: {}, confirmation: "x" });
      }),
    );
    renderWithProviders(<Status />, { route: "/status/" });
    expect(await screen.findByRole("heading", { level: 2, name: "이룬 순간" })).toBeInTheDocument();
    const first = body.moments[0].text;
    expect(screen.getByText(first)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "숨긴 순간 1개" })).toBeInTheDocument();
    await userEvent.click(within(screen.getByText(first).closest("li") as HTMLElement).getByRole("button", { name: /^더 보기/ }));
    await userEvent.click(await screen.findByRole("button", { name: "숨기기" }));
    expect(await screen.findByRole("button", { name: "숨긴 순간 2개" })).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByText(first)).toBeNull());
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

  // SP8-07 (spec 7.5, 10.2): the body record line under the health row.
  const healthRow = () => within(sectionOf(copy.statusScreen.statsHeading)).getAllByRole("listitem")[2];

  it("body_line_and_last_date", async () => {
    serve({ ...body, body: { last_date: "2026-10-24", days_7: 6, steps_avg_7: 6800, sleep_avg_7: 410 } });
    renderWithProviders(<Status />, { route: "/status/" });
    await screen.findByRole("heading", { level: 2, name: copy.statusScreen.statsHeading });
    const health = healthRow();
    expect(within(health).getByText("몸 기록 · 지난 7일 걸음 평균 6,800 · 잠 평균 6시간 50분")).toBeInTheDocument();
    expect(within(health).getByText("마지막 기록 10/24")).toBeInTheDocument();
    expect(screen.queryByText(/단축어/)).toBeNull();
  });

  it("body_line_omits_missing_values", async () => {
    serve({ ...body, body: { last_date: "2026-10-20", days_7: 1, steps_avg_7: null, sleep_avg_7: 420 } });
    renderWithProviders(<Status />, { route: "/status/" });
    await screen.findByRole("heading", { level: 2, name: copy.statusScreen.statsHeading });
    const health = healthRow();
    expect(within(health).getByText("몸 기록 · 지난 7일 잠 평균 7시간 0분")).toBeInTheDocument();
    expect(within(health).getByText("마지막 기록 10/20")).toBeInTheDocument();
  });

  it("old_record_shows_only_last_date_and_no_warning", async () => {
    serve({ ...body, body: { last_date: "2026-08-02", days_7: 0, steps_avg_7: null, sleep_avg_7: null } });
    renderWithProviders(<Status />, { route: "/status/" });
    await screen.findByRole("heading", { level: 2, name: copy.statusScreen.statsHeading });
    const health = healthRow();
    expect(within(health).getByText("마지막 기록 8/2")).toBeInTheDocument();
    expect(health.textContent).not.toContain("몸 기록");
    for (const w of ["오래", "경고", "끊", "부족", "목표"]) expect(health.textContent).not.toContain(w);
  });

  it("connect_hint_when_null", async () => {
    serve({ ...body, body: null });
    renderWithProviders(<Status />, { route: "/status/" });
    await screen.findByRole("heading", { level: 2, name: copy.statusScreen.statsHeading });
    expect(
      within(healthRow()).getByText("아이폰 단축어로 걸음과 잠을 보내면 건강 스탯의 근거가 돼요. 설정은 README의 'iPhone 단축어'를 봐 주세요."),
    ).toBeInTheDocument();
    expect(screen.queryByText(/마지막 기록/)).toBeNull();
  });
});
