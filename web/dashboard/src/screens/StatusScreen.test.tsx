import { render, screen, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
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
    expect(career.textContent).toContain("6 (2026-Q3)");
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
