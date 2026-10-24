import { render, screen } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { ConnectionProvider } from "../lib/ConnectionProvider";
import degraded from "../test/fixtures/health-degraded.json";
import health from "../test/fixtures/health.json";
import quiet from "../test/fixtures/health-quiet.json";
import { BASE, ORIGIN, healthAnswers } from "../test/handlers";
import { server } from "../test/server";
import { HealthScreen } from "./HealthScreen";

function renderScreen() {
  localStorage.setItem("mp.connection", JSON.stringify({ beUrl: ORIGIN, token: "fake-token-abc" }));
  return render(
    <ConnectionProvider>
      <HealthScreen />
    </ConnectionProvider>,
  );
}

const text = () => document.body.textContent ?? "";

describe("HealthScreen", () => {
  it("draws the status of 13.2 from the BE fixture", async () => {
    renderScreen();
    expect(await screen.findByText("스키마 11")).toBeInTheDocument();
    expect(text()).toContain("my-planner 0.2.0 · API v1 · 스키마 11");
    expect(text()).toContain("마지막 tick 17:00 · 텔레그램 폴링 연결됨");
    expect(text()).toContain("Claude 로그인 정상 · 사용 한도 없음");
    expect(text()).toContain("멈춤 없음 · 주 통로 앱 (지금 앱) · 푸시 구독 1");
    const runs = screen.getAllByRole("listitem").map((li) => li.textContent);
    expect(runs).toEqual(["10:00아침 브리핑보냄 (앱) · 답함", "18:00저녁 체크인예정"]);
    expect(screen.getByRole("img", { name: "두뇌 호출 23 / 60" })).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "먼저 보낸 메시지 1 / 3" })).toBeInTheDocument();
    expect(text()).toContain("최근 24시간 경고·오류 2 (send_error 1, tick_error 1)");
    expect(document.querySelector("[style]")).toBeNull();
  });

  it("draws login trouble, a limit, skipped and unsent runs", async () => {
    server.use(healthAnswers.ok(degraded));
    renderScreen();
    expect(await screen.findByText(/Claude 로그인/)).toBeInTheDocument();
    expect(text()).toContain("Claude 로그인 다시 로그인 필요 · 사용 한도 18:30까지");
    const runs = screen.getAllByRole("listitem").map((li) => li.textContent);
    expect(runs).toEqual([
      "06:00주간 회고건너뜀(한계 시각 지남)",
      "08:30다시 이어서전송 안 됨",
      "10:00아침 브리핑보냄 (앱) · 답함",
      "18:00저녁 체크인건너뜀(로그인·결제 문제)",
    ]);
    expect(text()).toContain("최근 24시간 경고·오류 3 (brain_auth_error 1, send_error 2)");
  });

  it("shows the empty states", async () => {
    server.use(healthAnswers.ok(quiet));
    renderScreen();
    expect(await screen.findByText("오늘 예정된 회차가 아직 없어요.")).toBeInTheDocument();
    expect(screen.getByText("최근 24시간 경고 없음")).toBeInTheDocument();
    expect(text()).toContain("주 통로 앱 (지금 텔레그램) · 푸시 구독 0");
  });

  it("shows a pause and a zero bar honestly", async () => {
    server.use(
      healthAnswers.ok({ ...quiet, paused_until: "2026-10-26T00:00:00Z", brain: { ...quiet.brain, calls_today: 0 } }),
    );
    renderScreen();
    expect(await screen.findByText(/10\/26 09:00까지 멈춤/)).toBeInTheDocument();
    expect(document.querySelector(".meter-fill")).toBeNull();
  });

  it.each([
    ["offline", healthAnswers.unreachable, "BE가 켜지면 다시 보여 드릴게요."],
    ["401", healthAnswers.unauthorized, "토큰이 맞지 않아요. 설정에서 다시 넣어 주세요."],
    ["429", healthAnswers.tooMany, "잠시 뒤에 다시 시도해 주세요."],
    ["503", healthAnswers.safeMode, "데이터베이스 점검이 필요해요. PC에서 README의 복구 절차를 따라 주세요."],
    ["500", healthAnswers.internal, "BE가 응답했지만 이 화면을 그리지 못했어요 (internal)."],
  ])("shows the %s state", async (_name, answer, message) => {
    server.use(answer());
    renderScreen();
    expect(await screen.findByText(message)).toBeInTheDocument();
    expect(screen.queryByText(/오늘 회차/)).toBeNull();
  });

  it("shows a shape error", async () => {
    const { runs_today: _r, ...missing } = health;
    server.use(http.get(`${BASE}/health`, () => HttpResponse.json(missing)));
    renderScreen();
    expect(await screen.findByText("BE가 응답했지만 이 화면을 그리지 못했어요 (shape).")).toBeInTheDocument();
  });

  it("links 401 to the settings screen", async () => {
    server.use(healthAnswers.unauthorized());
    renderScreen();
    expect(await screen.findByRole("link", { name: "설정 열기" })).toHaveAttribute("href", "/settings/");
  });
});
