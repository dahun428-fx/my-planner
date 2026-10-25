import { render, screen, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import type { Status } from "../api/types.gen";
import { ConnectionProvider } from "../lib/ConnectionProvider";
import statusEmpty from "../test/fixtures/status-empty.json";
import status from "../test/fixtures/status.json";
import { BASE, ORIGIN, statusAnswers } from "../test/handlers";
import { server } from "../test/server";
import { StatusScreen } from "./StatusScreen";

function renderScreen() {
  localStorage.setItem("mp.connection", JSON.stringify({ beUrl: ORIGIN, token: "fake-token-abc" }));
  return render(
    <ConnectionProvider>
      <StatusScreen />
    </ConnectionProvider>,
  );
}

const text = () => document.body.textContent ?? "";

// Streak, time left, missed counts and loss words (ADR 0006, spec 13.5), written as escapes so src/
// stays clean of them, plus the "D-3" countdown below.
const PRESSURE = [
  "\uc5f0\uc18d",
  "\uc2a4\ud2b8\ub9ad",
  "\ub0a8\uc740",
  "\ub0a8\uc74c",
  "\ub193\uce5c",
  "\ub193\uce68",
  "\uc77c\uc9f8",
  "\ub9c8\uac10",
  "\uc2e4\ud328",
  "\uac10\uc18c",
];

describe("StatusScreen", () => {
  it("renders snapshot", async () => {
    renderScreen();
    expect(await screen.findByText("Lv. 6")).toBeInTheDocument();
    expect(screen.getByText("130 / 400 XP")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "경험치 130 / 400" })).toBeInTheDocument();
    expect(screen.getByText("HP 4/5")).toBeInTheDocument();
    expect(screen.getByText("오늘 컨디션")).toBeInTheDocument();
    expect(document.querySelectorAll(".hp-cell[data-on='true']")).toHaveLength(4);

    const stats = screen.getByRole("region", { name: "스탯 (2026-Q4)" });
    const rows = within(stats).getAllByRole("listitem");
    expect(rows.map((r) => r.dataset.area)).toEqual(status.stats.map((s) => s.area));
    expect(rows.map((r) => within(r).getByRole("img").getAttribute("aria-label"))).toEqual([
      "커리어 6 / 10",
      "경제 5 / 10",
      "건강 4 / 10",
      "관계 7 / 10",
      "배움 6 / 10",
      "삶의 질 5 / 10",
    ]);
    const health = rows[2];
    expect(within(health).getByText("↓ 디버프 (Q3 6)")).toBeInTheDocument();
    expect(health.textContent).toContain("회복 퀘스트: 저녁에 20분 걷기 (15~30분)");
    expect(rows.filter((r) => r.textContent?.includes("디버프"))).toHaveLength(1);

    expect(text()).toContain("1.꾸민 작은 그림책 만들기첫 걸음 3/5");
    expect(text()).toContain("첫 장면 색칠하기 (15~30분)");
    expect(text()).toContain("텔레그램이나 운영 앱에서 '그 퀘스트 할게'라고 말씀해 주세요.");
    expect(text()).toContain("「꾸민 첫 전시」의 순간 · 「꾸민 이사 결정」을 지나온 사람");
    expect(text()).toContain("+10 할 일 완료 · +5 회차 답 · +5 컨디션 기록 · +5 쉬는 날 · +10 할 일 완료");
    expect(screen.queryAllByRole("checkbox")).toHaveLength(0);
    expect(document.querySelector("[style]")).toBeNull();
  });

  it("marks a daily quest with a dot, not a box that looks tickable (DU-27)", async () => {
    renderScreen();
    await screen.findByText("첫 장면 색칠하기 (15~30분)");
    const daily = document.querySelectorAll(".quests.daily .quest");
    expect(daily).toHaveLength(status.daily_quests.length);
    for (const q of daily) {
      expect(q.querySelector(".quest-dot")).not.toBeNull();
      expect(q.querySelector(".quest-dot")).toHaveAttribute("aria-hidden", "true");
    }
    expect(document.querySelector(".quest-mark, input, [role='checkbox']")).toBeNull();
    const { readFileSync } = await import("node:fs");
    const { join } = await import("node:path");
    const css = readFileSync(join(__dirname, "../styles/globals.css"), "utf8");
    expect(css).not.toContain(".quest-mark");
    const rule = /\.quest-dot\s*\{([^}]*)\}/.exec(css)?.[1] ?? "";
    expect(rule).toMatch(/border-radius:\s*50%/); // round
    expect(rule).not.toMatch(/inset|border:/); // filled, no outline like an empty box
  });

  it("shows an older quarter next to its score and a dash for no score", async () => {
    const stats = status.stats.map((s) =>
      s.area === "career"
        ? { ...s, period: "2026-Q3", prev_score: null, prev_period: null }
        : s.area === "finance"
          ? { ...s, score: null, period: null, prev_score: null, prev_period: null }
          : s,
    );
    server.use(statusAnswers.ok({ ...status, stats }));
    renderScreen();
    const region = await screen.findByRole("region", { name: "스탯 (2026-Q4)" });
    const [career, finance] = within(region).getAllByRole("listitem");
    expect(career.textContent).toContain("6.5 (2026-Q3)");
    expect(finance.textContent).toContain("—");
    expect(within(finance).getByRole("img")).toHaveAttribute("aria-label", "경제 기록 없음");
    expect(finance.querySelector(".stat-fill")).toBeNull();
  });

  it("empty states", async () => {
    server.use(statusAnswers.ok(statusEmpty));
    renderScreen();
    expect(await screen.findByText("Lv. 1")).toBeInTheDocument();
    expect(screen.getByText("0 / 150 XP")).toBeInTheDocument();
    expect(document.querySelector(".xp-fill")).toBeNull(); // a zero has no stub
    expect(screen.getByText("HP 기록 없음")).toBeInTheDocument();
    expect(document.querySelectorAll(".hp-cell[data-on='true']")).toHaveLength(0);
    expect(screen.getByText("영역 점수는 분기 마지막 주 회고에서 함께 정해요.")).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "스탯" })).toBeInTheDocument();
    expect(
      screen.getByText("이번 분기 메인 퀘스트가 아직 없어요. 계획 모드(/plan)에서 함께 정할 수 있어요."),
    ).toBeInTheDocument();
    expect(screen.getByText("오늘의 퀘스트는 첫 걸음이 생기면 나타나요.")).toBeInTheDocument();
    expect(screen.getByText("고점이나 전환점을 곡선에 남기면 칭호가 생겨요.")).toBeInTheDocument();
    expect(screen.getByText("할 일, 체크인 답, 컨디션 기록, 쉬는 날 모두 경험치가 돼요.")).toBeInTheDocument();
  });

  it("no streak or countdown words", async () => {
    for (const body of [status, statusEmpty]) {
      server.use(statusAnswers.ok(body));
      const { unmount } = renderScreen();
      await screen.findByText(/^Lv\. /);
      const all = text();
      expect(PRESSURE.filter((w) => all.includes(w))).toEqual([]);
      expect(all).not.toMatch(/D-\d/);
      expect(all).not.toMatch(/\d+일 (?:동안|째)/);
      expect(all).not.toMatch(/까지/); // no "next level in …", no deadline
      expect(all).not.toMatch(/-\d+ ?XP|−\d/); // XP only rises
      unmount();
      localStorage.clear();
    }
  });

  it.each([
    ["offline", statusAnswers.unreachable, "BE가 켜지면 다시 보여 드릴게요."],
    ["401", statusAnswers.unauthorized, "토큰이 맞지 않아요. 설정에서 다시 넣어 주세요."],
    ["503", statusAnswers.safeMode, "데이터베이스 점검이 필요해요. PC에서 README의 복구 절차를 따라 주세요."],
    ["500", statusAnswers.internal, "BE가 응답했지만 이 화면을 그리지 못했어요 (internal)."],
  ])("shows the %s state", async (_name, answer, message) => {
    server.use(answer());
    renderScreen();
    expect(await screen.findByText(message)).toBeInTheDocument();
    expect(screen.queryByText(/^Lv\. /)).toBeNull();
  });

  it("shows a shape error", async () => {
    const { stats: _s, ...missing } = status;
    server.use(http.get(`${BASE}/status`, () => HttpResponse.json(missing)));
    renderScreen();
    expect(await screen.findByText("BE가 응답했지만 이 화면을 그리지 못했어요 (shape).")).toBeInTheDocument();
  });
});

// SP8-02 (spec 10.1): bonus cells, the base-and-bonus line, "요즘 손이 간 영역".

const withStats = (patch: Record<string, Record<string, unknown>>) => ({
  ...status,
  stats: status.stats.map((s) => ({ ...s, ...patch[s.area] })),
});
const act = (tasks: number, habit_checks: number, body_days: number) => ({ tasks, habit_checks, body_days });

describe("StatusScreen bonus (SP8-02)", () => {
  const body = withStats({
    career: { score: 6, bonus: 1.2, effective_score: 7.2, activity: act(12, 0, 0) },
    health: { score: 4, bonus: 1.5, effective_score: 5.5, activity: act(0, 28, 0) },
    learning: { score: null, period: null, prev_score: null, prev_period: null, bonus: 0.4, effective_score: null, activity: act(2, 0, 0) },
    finance: { bonus: 0, effective_score: 5, activity: act(0, 0, 0) },
    relationships: { bonus: 0, effective_score: 7, activity: act(0, 0, 0) },
    quality_of_life: { bonus: 0, effective_score: 5, activity: act(0, 0, 0) },
  });
  const rowOf = async (area: string) => {
    const region = await screen.findByRole("region", { name: "스탯 (2026-Q4)" });
    return within(region)
      .getAllByRole("listitem")
      .find((r) => r.dataset.area === area)!;
  };

  it("stat_line_shows_effective_and_base_and_bonus", async () => {
    server.use(statusAnswers.ok(body));
    renderScreen();
    const health = await rowOf("health");
    expect(within(health).getByText("5.5")).toBeInTheDocument();
    expect(within(health).getByText("바탕 4 · 요즘 +1.5")).toBeInTheDocument();
    expect(health.querySelectorAll("rect.stat-bonus")).toHaveLength(1);
    expect(within(health).getByRole("img")).toHaveAttribute("aria-label", "건강 4 / 10");
    const career = await rowOf("career");
    expect(within(career).getByText("7.2")).toBeInTheDocument();
    expect(within(career).getByText("바탕 6 · 요즘 +1.2")).toBeInTheDocument();
  });

  it("zero_bonus_shows_base_only", async () => {
    server.use(statusAnswers.ok(body));
    renderScreen();
    const finance = await rowOf("finance");
    expect(within(finance).getByText("바탕 5")).toBeInTheDocument();
    expect(finance.textContent).not.toContain("요즘");
    expect(finance.querySelector("rect.stat-bonus")).toBeNull();
  });

  it("no_base_shows_dash_and_hint", async () => {
    server.use(statusAnswers.ok(body));
    renderScreen();
    const learning = await rowOf("learning");
    expect(within(learning).getByText("—")).toBeInTheDocument();
    expect(within(learning).getByText("요즘 +0.4 · 분기 회고에서 점수를 정하면 더해져요")).toBeInTheDocument();
    expect(learning.querySelector("rect.stat-bonus")).toBeNull();
  });

  it("recent_areas_sorted_and_counts", async () => {
    server.use(statusAnswers.ok(body));
    renderScreen();
    const panel = await screen.findByRole("region", { name: "요즘 손이 간 영역" });
    const lines = within(panel).getAllByRole("listitem");
    expect(lines.map((l) => l.dataset.area)).toEqual(["health", "career", "learning"]); // 1.5, 1.2, 0.4
    expect(lines[0].textContent).toContain("건강");
    expect(lines[0].textContent).toContain("+1.5");
    expect(lines[0].textContent).toContain("4주 동안 습관 28번");
    expect(lines[1].textContent).toContain("4주 동안 할 일 12개");
    expect(lines[2].textContent).toContain("+0.4");
    expect(lines[0].querySelector("svg.pictogram use")).toHaveAttribute("href", "#p-health");
    expect(lines[0].querySelector("svg.pictogram")).toHaveAttribute("aria-hidden", "true");
  });

  it("recent_areas_ties_keep_area_order_and_zero_counts_are_left_out", async () => {
    const tie = withStats({
      quality_of_life: { bonus: 0.5, activity: act(1, 2, 3) },
      finance: { bonus: 0.5, activity: act(0, 0, 4) },
    });
    server.use(
      statusAnswers.ok({ ...tie, stats: tie.stats.map((s) => (["finance", "quality_of_life"].includes(s.area) ? s : { ...s, bonus: 0 })) }),
    );
    renderScreen();
    const panel = await screen.findByRole("region", { name: "요즘 손이 간 영역" });
    const lines = within(panel).getAllByRole("listitem");
    expect(lines.map((l) => l.dataset.area)).toEqual(["finance", "quality_of_life"]);
    expect(lines[0].textContent).toContain("4주 동안 몸 기록 4일");
    expect(lines[0].textContent).not.toContain("할 일");
    expect(lines[1].textContent).toContain("4주 동안 할 일 1개 · 습관 2번 · 몸 기록 3일");
  });

  it("recent_areas_empty_copy", async () => {
    server.use(statusAnswers.ok(statusEmpty));
    renderScreen();
    const panel = await screen.findByRole("region", { name: "요즘 손이 간 영역" });
    expect(within(panel).getByText("4주 안에 끝낸 할 일이나 습관 체크가 생기면 여기에 보여요.")).toBeInTheDocument();
    expect(within(panel).queryAllByRole("listitem")).toHaveLength(0);
  });

  it("debuff_unchanged_with_bonus", async () => {
    server.use(statusAnswers.ok(body));
    renderScreen();
    const health = await rowOf("health");
    expect(within(health).getByText("↓ 디버프 (Q3 6)")).toBeInTheDocument();
    expect(health.textContent).toContain("회복 퀘스트: 저녁에 20분 걷기 (15~30분)");
  });

  it("no_decline_marks", async () => {
    server.use(statusAnswers.ok(body));
    renderScreen();
    await rowOf("health");
    const clone = document.body.cloneNode(true) as HTMLElement;
    clone.querySelectorAll(".stat-debuff").forEach((n) => n.remove());
    const all = clone.textContent ?? "";
    for (const mark of ["−", "%", "줄었", "↓"]) expect(all).not.toContain(mark);
  });
});

// SP8 10.1: the moments panel. Read only; hiding and deleting live in the ops app.
describe("StatusScreen moments panel (SP8 10.1)", () => {
  const moment = (id: number, date: string, text: string, area: Status["moments"][number]["area"]) => ({
    id,
    date,
    text,
    area,
    sources: ["task" as const],
    hidden: false,
  });
  const withMoments = (moments: Status["moments"]) => ({ ...status, moments }) as Status;

  it("moments_panel_groups_and_footer", async () => {
    server.use(
      statusAnswers.ok(
        withMoments([
          moment(1, "2026-10-24", "포트폴리오 사례 하나를 끝까지 다듬었어요", "career"),
          moment(2, "2026-10-24", "아침마다 물을 마셨어요", "health"),
          moment(3, "2026-10-23", "오래 미룬 전화를 걸었어요", null),
        ]),
      ),
    );
    renderScreen();
    const panel = await screen.findByRole("region", { name: "이룬 순간" });
    expect(within(panel).getAllByRole("heading", { level: 3 }).map((h) => h.textContent)).toEqual(["10월 24일 (토)", "10월 23일 (금)"]);
    const rows = within(panel).getAllByRole("listitem");
    expect(rows).toHaveLength(3);
    expect(rows[0].textContent).toBe("포트폴리오 사례 하나를 끝까지 다듬었어요");
    expect(rows[0].querySelector("svg.pictogram use")).toHaveAttribute("href", "#p-career");
    expect(rows[0]).toHaveAttribute("data-area", "career");
    expect(rows[2].querySelector("svg.pictogram use")).toHaveAttribute("href", "#p-memory"); // no area: memory
    expect(rows[2]).not.toHaveAttribute("data-area");
    expect(within(panel).getByText("숨기거나 지우는 것은 운영 앱 상태창에서 할 수 있어요.")).toBeInTheDocument();
  });

  it("moments_panel_empty_copy", async () => {
    renderScreen();
    const panel = await screen.findByRole("region", { name: "이룬 순간" });
    expect(within(panel).getByText("하루가 끝나면 비서가 그날 해낸 일을 몇 줄로 남겨 둬요.")).toBeInTheDocument();
    expect(within(panel).queryByRole("listitem")).toBeNull();
    expect(within(panel).queryByText(/운영 앱 상태창/)).toBeNull();
  });

  it("dashboard_has_no_hide_or_delete", async () => {
    server.use(statusAnswers.ok(withMoments([moment(1, "2026-10-24", "물을 마셨어요", "health")])));
    renderScreen();
    const panel = await screen.findByRole("region", { name: "이룬 순간" });
    expect(within(panel).queryAllByRole("button")).toHaveLength(0);
    for (const w of ["숨기기", "지우기", "다시 보이기", "숨긴 순간"]) expect(panel.textContent).not.toContain(w);
  });
});

// SP8-07 (spec 7.5, 10.1): the body record line under the health row.

describe("StatusScreen body line (SP8-07)", () => {
  const healthRow = async () => {
    const region = await screen.findByRole("region", { name: /^스탯/ });
    return within(region)
      .getAllByRole("listitem")
      .find((r) => r.dataset.area === "health")!;
  };
  const withBody = (b: Record<string, unknown> | null) => ({ ...status, body: b }) as unknown as Status;

  it("body_line_under_health", async () => {
    server.use(statusAnswers.ok(withBody({ last_date: "2026-10-24", days_7: 6, steps_avg_7: 6800, sleep_avg_7: 410 })));
    renderScreen();
    const health = await healthRow();
    expect(within(health).getByText("몸 기록 · 지난 7일 걸음 평균 6,800 · 잠 평균 6시간 50분")).toBeInTheDocument();
    expect(screen.getAllByText(/^몸 기록 · /)).toHaveLength(1);
  });

  it("body_line_omits_missing_values", async () => {
    server.use(statusAnswers.ok(withBody({ last_date: "2026-10-24", days_7: 2, steps_avg_7: null, sleep_avg_7: 450 })));
    renderScreen();
    const health = await healthRow();
    expect(within(health).getByText("몸 기록 · 지난 7일 잠 평균 7시간 30분")).toBeInTheDocument();
    expect(health.textContent).not.toContain("걸음");
  });

  it("no_body_line_when_null", async () => {
    server.use(statusAnswers.ok(withBody(null)));
    renderScreen();
    const health = await healthRow();
    expect(health.textContent).not.toContain("몸 기록");
    expect(text()).not.toContain("단축어");
  });

  it("no_warning_when_old", async () => {
    server.use(statusAnswers.ok(withBody({ last_date: "2026-08-30", days_7: 0, steps_avg_7: null, sleep_avg_7: null })));
    renderScreen();
    const health = await healthRow();
    expect(health.textContent).not.toContain("몸 기록");
    expect(health.textContent).not.toContain("마지막");
    for (const w of ["오래", "경고", "끊", "부족", "목표", "못 "]) expect(health.textContent).not.toContain(w);
  });
});
