import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { ConnectionProvider } from "../lib/ConnectionProvider";
import conditionsEmpty from "../test/fixtures/conditions-empty.json";
import todayEmpty from "../test/fixtures/today-empty.json";
import today from "../test/fixtures/today.json";
import weekEmpty from "../test/fixtures/week-empty.json";
import week from "../test/fixtures/week.json";
import { BASE, ORIGIN, conditionsAnswers, todayAnswers, weekAnswers } from "../test/handlers";
import { server } from "../test/server";
import { TasksScreen } from "./TasksScreen";

function renderScreen() {
  localStorage.setItem("mp.connection", JSON.stringify({ beUrl: ORIGIN, token: "fake-token-abc" }));
  return render(
    <ConnectionProvider>
      <TasksScreen />
    </ConnectionProvider>,
  );
}

const text = () => document.body.textContent ?? "";
const titles = (root: HTMLElement) => within(root).getAllByRole("listitem").map((li) => li.dataset.title);

describe("TasksScreen", () => {
  it("today order equals API groups", async () => {
    renderScreen();
    const panel = await screen.findByRole("region", { name: "오늘 (10/24 토)" });
    expect(titles(panel)).toEqual(today.todos.map((t) => t.todo.title));
    expect(within(panel).getByText("우선순위")).toBeInTheDocument();
    expect(within(panel).getByText("일정")).toBeInTheDocument();
    expect(within(panel).getByText("열린 할 일")).toBeInTheDocument();
    const rows = within(panel).getAllByRole("listitem").map((li) => li.textContent);
    expect(rows).toEqual([
      "1.수채화 밑그림 그리기",
      "2.저녁 산책 30분",
      "14:00치과 정기 검진",
      "세탁소에 겨울 외투 맡기기 (10/22)",
      "첫 장면 색칠하기",
    ]);
    // read only (spec 13.3): no check boxes, no buttons on a to-do
    expect(screen.queryAllByRole("checkbox")).toHaveLength(0);
    expect(within(panel).queryAllByRole("button")).toHaveLength(0);
    expect(text()).toContain("바꾸려면 텔레그램이나 운영 앱에서 말씀해 주세요.");
    expect(document.querySelector("[style]")).toBeNull();
  });

  it("opens the morning brief", async () => {
    renderScreen();
    const summary = await screen.findByText("아침 브리핑");
    const details = summary.closest("details")!;
    expect(details.open).toBe(false);
    await userEvent.click(summary);
    expect(details.open).toBe(true);
    expect(details.textContent).toContain("14:00에 치과 정기 검진이 있어요.");
    expect(details.textContent).toContain("10:00");
  });

  it("week shows 7 day cells including empty", async () => {
    renderScreen();
    await userEvent.click(await screen.findByRole("tab", { name: "이번 주" }));
    const panel = await screen.findByRole("region", { name: "이번 주 (10/19~10/25)" });
    const days = within(panel).getAllByRole("listitem", { name: /^\d+\/\d+ / });
    expect(days.map((d) => d.querySelector(".day-name")?.textContent)).toEqual([
      "10/19 월",
      "10/20 화",
      "10/21 수",
      "10/22 목",
      "10/23 금",
      "10/24 토 (오늘)",
      "10/25 일",
    ]);
    expect(days[0].textContent).toContain("—");
    expect(days[5]).toHaveAttribute("aria-current", "date");
    expect(days[5].textContent).toContain("14:00치과 정기 검진");
    expect(within(panel).getByText("1.")).toBeInTheDocument(); // the week's priority, numbered
    expect(text()).toContain(week.priorities[0].title);
    expect(screen.queryAllByRole("checkbox")).toHaveLength(0);
    expect(screen.getByRole("tab", { name: "이번 주" })).toHaveAttribute("aria-selected", "true");
  });

  it("draws 30 days of condition dots with the head line", async () => {
    renderScreen();
    expect(await screen.findByText("평균 3.7 · 21일 기록")).toBeInTheDocument();
    expect(document.querySelectorAll(".cdots-dot")).toHaveLength(21);
  });

  it("shows the empty states", async () => {
    server.use(todayAnswers.ok(todayEmpty), conditionsAnswers.ok(conditionsEmpty), weekAnswers.ok(weekEmpty));
    renderScreen();
    expect(await screen.findByText("아직 비어 있어요.")).toBeInTheDocument();
    expect(screen.getByText("저녁 체크인에서 컨디션을 기록하면 여기에 그려져요.")).toBeInTheDocument();
    expect(screen.queryByText(/평균/)).toBeNull();
    expect(screen.queryByText("아침 브리핑")).toBeNull();
    await userEvent.click(screen.getByRole("tab", { name: "이번 주" }));
    const panel = await screen.findByRole("region", { name: /^이번 주/ });
    expect(within(panel).getByText("아직 비어 있어요.")).toBeInTheDocument();
    expect(within(panel).getAllByRole("listitem", { name: /^\d+\/\d+ / })).toHaveLength(7);
  });

  it.each([
    ["offline", "unreachable", "BE가 켜지면 다시 보여 드릴게요."],
    ["401", "unauthorized", "토큰이 맞지 않아요. 설정에서 다시 넣어 주세요."],
    ["429", "tooMany", "잠시 뒤에 다시 시도해 주세요."],
    ["503", "safeMode", "데이터베이스 점검이 필요해요. PC에서 README의 복구 절차를 따라 주세요."],
    ["500", "internal", "BE가 응답했지만 이 화면을 그리지 못했어요 (internal)."],
  ] as const)("shows the %s state once, without content", async (_name, answer, message) => {
    server.use(todayAnswers[answer](), conditionsAnswers[answer]());
    renderScreen();
    expect(await screen.findByText(message)).toBeInTheDocument();
    expect(screen.getAllByText(message)).toHaveLength(1);
    expect(screen.queryByText("우선순위")).toBeNull();
    expect(screen.queryByText(/평균/)).toBeNull();
  });

  it("shows a shape error in the to-do panel and keeps the conditions", async () => {
    const { todos: _t, ...missing } = today;
    server.use(http.get(`${BASE}/today`, () => HttpResponse.json(missing)));
    renderScreen();
    expect(await screen.findByText("BE가 응답했지만 이 화면을 그리지 못했어요 (shape).")).toBeInTheDocument();
    expect(await screen.findByText("평균 3.7 · 21일 기록")).toBeInTheDocument();
  });

  it("shows a conditions error inside its own panel", async () => {
    server.use(http.get(`${BASE}/conditions`, () => HttpResponse.json({ from: "2026-09-25" })));
    renderScreen();
    expect(await screen.findByText("BE가 응답했지만 이 화면을 그리지 못했어요 (shape).")).toBeInTheDocument();
    expect(await screen.findByRole("region", { name: "오늘 (10/24 토)" })).toBeInTheDocument();
  });
});
