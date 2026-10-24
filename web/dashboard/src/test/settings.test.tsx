import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { ConnectionProvider } from "../lib/ConnectionProvider";
import Settings from "../pages/settings";
import { ORIGIN, healthAnswers } from "./handlers";
import { server } from "./server";

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
  it("saves the BE URL and token and checks /health", async () => {
    renderSettings();
    await fill(`${ORIGIN}/api/v1`, "fake-token-abc");
    expect(await screen.findByText("연결했어요.")).toBeInTheDocument();
    expect(saved()).toEqual({ beUrl: ORIGIN, token: "fake-token-abc" });
    expect(screen.getByRole("link", { name: "비서 상태 보기" })).toHaveAttribute("href", "/");
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

  it("fills the saved connection", async () => {
    localStorage.setItem("mp.connection", JSON.stringify({ beUrl: ORIGIN, token: "fake-token-abc" }));
    renderSettings();
    expect(await screen.findByDisplayValue(`${ORIGIN}/api/v1`)).toBeInTheDocument();
  });
});
