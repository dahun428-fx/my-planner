import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ConnectionProvider, useConnection } from "../lib/ConnectionProvider";
import { ORIGIN, healthAnswers } from "./handlers";
import { server } from "./server";

const router = { asPath: "/settings/", pathname: "/settings", push: vi.fn(async () => true), replace: vi.fn(async () => true) };
vi.mock("next/router", () => ({ useRouter: () => router }));

const { default: Settings } = await import("../pages/settings");

function renderSettings() {
  return render(
    <ConnectionProvider>
      <Settings />
    </ConnectionProvider>,
  );
}

const saved = () => JSON.parse(localStorage.getItem("mp.connection") ?? "null");

async function fill(url: string, token: string) {
  const user = userEvent.setup();
  await user.clear(screen.getByLabelText("BE 주소"));
  if (url) await user.type(screen.getByLabelText("BE 주소"), url);
  await user.clear(screen.getByLabelText("API 토큰"));
  if (token) await user.type(screen.getByLabelText("API 토큰"), token);
  await user.click(screen.getByRole("button", { name: "연결 확인" }));
}

describe("settings", () => {
  beforeEach(() => router.push.mockClear());

  it("saves the BE URL and token and checks /health", async () => {
    renderSettings();
    await fill(`${ORIGIN}/api/v1`, "fake-token-abc");
    expect(await screen.findByText("연결했어요.")).toBeInTheDocument();
    expect(saved()).toEqual({ beUrl: ORIGIN, token: "fake-token-abc" });
    expect(screen.getByRole("link", { name: "비서 상태 보기" })).toHaveAttribute("href", "/");
  });

  it("goes to the home screen once connected (DU-04)", async () => {
    renderSettings();
    await fill(`${ORIGIN}/api/v1`, "fake-token-abc");
    await waitFor(() => expect(router.push).toHaveBeenCalledWith("/"));
    expect(router.push).toHaveBeenCalledTimes(1);
  });

  it.each([
    ["the token is wrong", healthAnswers.unauthorized],
    ["the BE is off", healthAnswers.unreachable],
  ])("stays when %s", async (_why, answer) => {
    server.use(answer());
    renderSettings();
    await fill(`${ORIGIN}/api/v1`, "fake-token-abc");
    expect(await screen.findByText("저장했어요.")).toBeInTheDocument();
    expect(router.push).not.toHaveBeenCalled();
  });

  it("says where the address and the token come from, folded until asked (DU-04)", async () => {
    renderSettings();
    const summary = await screen.findByText("주소와 토큰은 어디서 찾나요?");
    const help = summary.closest("details")!;
    expect(help).not.toHaveAttribute("open");
    await userEvent.click(summary);
    expect(help).toHaveAttribute("open");
    const text = help.textContent ?? "";
    expect(text).toContain("tailscale serve status");
    expect(text).toContain("https://<기계>.<tailnet>.ts.net");
    expect(text).toContain("python -m my_planner gen-token");
    expect(text).toContain("API_TOKEN");
    expect(text).toContain(".env");
    // a pattern only: no machine or tailnet name, not even the test fixture's
    expect(text.match(/[a-z0-9-]+\.[a-z0-9-]+\.ts\.net/gi)).toBeNull();
    expect(text).not.toContain("desk");
  });

  it.each([
    ["http://desk.example.ts.net/api/v1", "https 주소만 넣을 수 있어요."],
    ["https://desk.example.com/api/v1", "이 대시보드가 허용한 tailnet 주소가 아니에요."],
    ["desk", "주소 형식이 맞지 않아요."],
  ])("rejects %s without saving", async (url, message) => {
    renderSettings();
    await fill(url, "fake-token-abc");
    expect(await screen.findByRole("alert")).toHaveTextContent(message);
    expect(saved()).toBeNull();
  });

  it("asks for a token", async () => {
    renderSettings();
    await fill(`${ORIGIN}/api/v1`, "");
    expect(await screen.findByRole("alert")).toHaveTextContent("토큰을 넣어 주세요.");
    await fill(`${ORIGIN}/api/v1`, "토큰");
    expect(await screen.findByRole("alert")).toHaveTextContent("토큰에는 영문, 숫자, 기호만 들어가요.");
    expect(saved()).toBeNull();
  });

  it("says when the token is wrong", async () => {
    server.use(healthAnswers.unauthorized());
    renderSettings();
    await fill(`${ORIGIN}/api/v1`, "fake-token-wrong");
    expect(await screen.findByText("토큰이 맞지 않아요. 설정에서 다시 넣어 주세요.")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "설정 열기" })).toBeNull();
  });

  it("keeps the address when the BE is off", async () => {
    server.use(healthAnswers.unreachable());
    renderSettings();
    await fill(`${ORIGIN}/api/v1`, "fake-token-abc");
    expect(await screen.findByText("BE가 켜지면 다시 보여 드릴게요.")).toBeInTheDocument();
    expect(saved()).toEqual({ beUrl: ORIGIN, token: "fake-token-abc" });
  });

  it("restarts a poll stopped by 401 when the same token is entered again", async () => {
    localStorage.setItem("mp.connection", JSON.stringify({ beUrl: ORIGIN, token: "fake-token-abc" }));
    server.use(healthAnswers.unauthorized());
    function Probe() {
      return <p data-testid="probe">{useConnection().health?.kind ?? "none"}</p>;
    }
    render(
      <ConnectionProvider>
        <Settings />
        <Probe />
      </ConnectionProvider>,
    );
    expect(await screen.findByText("unauthorized")).toBeInTheDocument();
    server.resetHandlers(); // the BE accepts the token again
    await userEvent.click(screen.getByRole("button", { name: "연결 확인" }));
    expect(await screen.findByText("연결했어요.")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByTestId("probe")).toHaveTextContent("ok"));
  });

  it("fills the saved connection", async () => {
    localStorage.setItem("mp.connection", JSON.stringify({ beUrl: ORIGIN, token: "fake-token-abc" }));
    renderSettings();
    expect(await screen.findByDisplayValue(`${ORIGIN}/api/v1`)).toBeInTheDocument();
  });
});
