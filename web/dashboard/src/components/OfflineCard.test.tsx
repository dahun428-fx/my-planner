import { render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ConnectionProvider } from "../lib/ConnectionProvider";
import { OFFLINE_TEXT } from "../lib/labels";
import { ORIGIN, healthAnswers } from "../test/handlers";
import { server } from "../test/server";
import { StateNotice } from "./StateNotice";

const saveConn = () => localStorage.setItem("mp.connection", JSON.stringify({ beUrl: ORIGIN, token: "fake-token-abc" }));

const renderOffline = (settingsLink = true) =>
  render(
    <ConnectionProvider>
      <StateNotice result={{ kind: "offline" }} settingsLink={settingsLink} />
    </ConnectionProvider>,
  );

const CHECKS = ["노트북이 켜져 있고 절전 상태가 아닌지", "이 기기에서 Tailscale이 켜져 있는지", "Chrome이라면 로컬 네트워크 접근을 허용했는지"];

describe("offline card (DU-02)", () => {
  afterEach(() => vi.useRealTimers());

  it("for a browser that was never connected: three checks, no record, settings, and the retry", async () => {
    saveConn();
    server.use(healthAnswers.unreachable());
    renderOffline();
    expect(await screen.findByText("이 브라우저는 아직 노트북의 비서와 연결되지 않았어요.")).toBeInTheDocument();
    expect(screen.getByText("이 브라우저에는 아직 응답 기록이 없어요.")).toBeInTheDocument();
    expect(screen.getByText("처음 연결할 때는 이 세 가지를 확인해 주세요.")).toBeInTheDocument();
    const list = screen.getByRole("list", { name: "확인할 것" });
    expect(within(list).getAllByRole("listitem").map((li) => li.textContent)).toEqual(CHECKS);
    expect(screen.getByText("주소와 토큰도 설정에서 한 번 더 봐 주세요.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "설정 열기" })).toHaveAttribute("href", "/settings/");
    expect(await screen.findByText("10초마다 자동으로 다시 확인하고 있어요.")).toBeInTheDocument();
    expect(screen.getByText("BE가 켜지면 다시 보여 드릴게요.")).toBeInTheDocument();
    expect(document.querySelector(".offline-card")).toHaveAttribute("data-seen", "never");
  });

  it("for a browser that was connected: the last answer as M/D HH:MM and how long ago", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2026-10-24T08:00:05Z"));
    saveConn();
    localStorage.setItem("mp.lastHealthOk", JSON.stringify({ at: "2026-10-24T05:00:05Z", lastTickAt: "2026-10-24T05:00:00Z" }));
    server.use(healthAnswers.unreachable());
    renderOffline();
    expect(await screen.findByText("노트북의 비서가 지금 응답하지 않아요.")).toBeInTheDocument();
    expect(screen.getByText("마지막 응답 10/24 14:00 (3시간 전)")).toBeInTheDocument();
    expect(screen.getByText("잠시 쉬고 있을 수 있어요. 이 세 가지를 확인해 주세요.")).toBeInTheDocument();
    expect(within(screen.getByRole("list", { name: "확인할 것" })).getAllByRole("listitem")).toHaveLength(3);
    expect(screen.queryByText("주소와 토큰도 설정에서 한 번 더 봐 주세요.")).toBeNull();
    expect(screen.queryByRole("link", { name: "설정 열기" })).toBeNull();
    expect(document.querySelector(".offline-card")).toHaveAttribute("data-seen", "before");
  });

  it("says the screen's own minute while /health still answers", async () => {
    saveConn();
    renderOffline();
    expect(await screen.findByText("노트북의 비서가 지금 응답하지 않아요.")).toBeInTheDocument();
    expect(screen.getByText("1분마다 자동으로 다시 확인하고 있어요.")).toBeInTheDocument();
  });

  it("leaves out the settings link on the settings screen", async () => {
    saveConn();
    server.use(healthAnswers.unreachable());
    renderOffline(false);
    expect(await screen.findByText("주소와 토큰도 설정에서 한 번 더 봐 주세요.")).toBeInTheDocument();
    expect(screen.queryByRole("link")).toBeNull();
  });

  it("has the wait in seconds, then minutes", () => {
    expect(OFFLINE_TEXT.every(10_000)).toBe("10초");
    expect(OFFLINE_TEXT.every(40_000)).toBe("40초");
    expect(OFFLINE_TEXT.every(60_000)).toBe("1분");
  });

  it("announces only its first line", async () => {
    saveConn();
    server.use(healthAnswers.unreachable());
    renderOffline();
    const status = await screen.findByRole("status");
    expect(status).toHaveTextContent(/^이 브라우저는 아직 노트북의 비서와 연결되지 않았어요\.$/);
  });
});
