import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ConnectionBand } from "../components/ConnectionBand";
import { ConnectionProvider, useConnection } from "../lib/ConnectionProvider";
import { CurveScreen, resetCurveMemory } from "../screens/CurveScreen";
import { StatusScreen } from "../screens/StatusScreen";
import { TasksScreen } from "../screens/TasksScreen";
import { BASE, ORIGIN, healthAnswers } from "./handlers";
import { server } from "./server";

vi.mock("next/router", () => ({ useRouter: () => ({ isReady: true, query: {}, replace: async () => true }) }));

const saveConn = () => localStorage.setItem("mp.connection", JSON.stringify({ beUrl: ORIGIN, token: "fake-token-abc" }));

/** Every BE path off: the laptop is asleep. */
const allOff = () => server.use(http.get(`${BASE}/*`, () => HttpResponse.error()));

function renderWithBand(children: ReactNode) {
  saveConn();
  return render(
    <ConnectionProvider>
      <ConnectionBand />
      {children}
    </ConnectionProvider>,
  );
}

// B1, DU-03: when /health turns from offline to ok, each screen loads its own GETs right away instead of
// waiting up to 60 s for its next tick.
describe("back online", () => {
  afterEach(() => {
    vi.useRealTimers();
    resetCurveMemory();
  });

  it.each([
    ["status", () => <StatusScreen />, () => screen.findByText("Lv. 6")],
    ["tasks", () => <TasksScreen />, () => screen.findByRole("region", { name: "오늘 (10/24 토)" })],
    ["curve", () => <CurveScreen />, () => screen.findByRole("figure")],
  ])("the %s screen fills as soon as the check finds the BE again", async (_name, screenOf, filled) => {
    allOff();
    renderWithBand(screenOf());
    expect((await screen.findAllByText("BE가 켜지면 다시 보여 드릴게요.")).length).toBeGreaterThan(0);
    server.resetHandlers(); // the laptop wakes up
    await userEvent.click(screen.getByRole("button", { name: "연결 확인" }));
    expect(await filled()).toBeInTheDocument();
    expect(screen.queryByText("BE가 켜지면 다시 보여 드릴게요.")).toBeNull();
  });

  it("counts each offline to ok turn once, and not an ok after ok", async () => {
    function Probe() {
      const { backOnline, health } = useConnection();
      return <p data-testid="probe">{`${health?.kind ?? "none"} ${backOnline}`}</p>;
    }
    server.use(healthAnswers.unreachable());
    renderWithBand(<Probe />);
    await waitFor(() => expect(screen.getByTestId("probe")).toHaveTextContent("offline 0"));
    server.resetHandlers();
    await userEvent.click(screen.getByRole("button", { name: "연결 확인" }));
    await waitFor(() => expect(screen.getByTestId("probe")).toHaveTextContent("ok 1"));
    await userEvent.click(screen.getByRole("button", { name: "연결 확인" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "연결 확인" })).toBeEnabled());
    expect(screen.getByTestId("probe")).toHaveTextContent("ok 1");
  });

  it("checks /health again after 10 s while offline, then backs off", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const seen: number[] = [];
    server.use(
      http.get(`${BASE}/health`, () => {
        seen.push(Date.now());
        return HttpResponse.error();
      }),
    );
    function Probe() {
      return <p data-testid="retry">{String(useConnection().retryMs)}</p>;
    }
    renderWithBand(<Probe />);
    await waitFor(() => expect(screen.getByTestId("retry")).toHaveTextContent("10000"));
    expect(seen).toHaveLength(1);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10_000);
    });
    await waitFor(() => expect(seen).toHaveLength(2));
    expect(screen.getByTestId("retry")).toHaveTextContent("20000");
  });
});
