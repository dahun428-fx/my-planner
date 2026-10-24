import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ConnectionProvider } from "../lib/ConnectionProvider";
import { BASE, ORIGIN, healthAnswers } from "../test/handlers";
import { server } from "../test/server";
import { http, HttpResponse } from "msw";
import health from "../test/fixtures/health.json";
import { ConnectionBand } from "./ConnectionBand";

const saveConn = () => localStorage.setItem("mp.connection", JSON.stringify({ beUrl: ORIGIN, token: "fake-token-abc" }));

const renderBand = () =>
  render(
    <ConnectionProvider>
      <ConnectionBand />
    </ConnectionProvider>,
  );

describe("ConnectionBand", () => {
  afterEach(() => vi.restoreAllMocks());

  it("shows BE on with the answer time in KST", async () => {
    saveConn();
    renderBand();
    expect(await screen.findByText("BE 켜짐 · 17:00:05 응답")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "연결 확인" })).toBeInTheDocument();
    // the live region says on/off only, not the time that changes every minute
    expect(screen.getByRole("status")).toHaveTextContent(/^BE 켜짐$/);
    // the good answer is remembered for the next time the BE is off
    expect(JSON.parse(localStorage.getItem("mp.lastHealthOk") ?? "null")).toMatchObject({ lastTickAt: "2026-10-24T08:00:00Z" });
  });

  it("shows BE off with the last answer of this browser", async () => {
    saveConn();
    localStorage.setItem("mp.lastHealthOk", JSON.stringify({ at: "2026-10-24T08:00:05Z", lastTickAt: "2026-10-24T08:00:00Z" }));
    server.use(healthAnswers.unreachable());
    renderBand();
    expect(await screen.findByText("BE 꺼짐 · 마지막 응답 10/24 17:00")).toBeInTheDocument();
  });

  it("shows no record when the browser has none", async () => {
    saveConn();
    server.use(healthAnswers.unreachable());
    renderBand();
    expect(await screen.findByText("BE 꺼짐 · 마지막 응답 기록 없음")).toBeInTheDocument();
  });

  it("shows no record when localStorage is blocked", async () => {
    saveConn();
    localStorage.setItem("mp.lastHealthOk", JSON.stringify({ at: "2026-10-24T08:00:05Z", lastTickAt: null }));
    const real = Storage.prototype.getItem;
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(function (this: Storage, key: string) {
      if (key === "mp.lastHealthOk") throw new Error("blocked");
      return real.call(this, key);
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    server.use(healthAnswers.unreachable());
    renderBand();
    expect(await screen.findByText("BE 꺼짐 · 마지막 응답 기록 없음")).toBeInTheDocument();
  });

  it("shows BE not set up when there is no connection", async () => {
    renderBand();
    expect(await screen.findByRole("status")).toHaveTextContent("BE 연결 전");
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("counts any HTTP answer as BE on", async () => {
    saveConn();
    server.use(healthAnswers.unauthorized());
    renderBand();
    // the status region exists from the first render ("연결 확인 중"), so wait for its text, not for the element
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent(/^BE 켜짐$/));
    expect(document.querySelector(".band-text")).toHaveTextContent(/^BE 켜짐$/);
  });

  it("checks again on the button", async () => {
    saveConn();
    server.use(healthAnswers.unreachable());
    renderBand();
    expect(await screen.findByText("BE 꺼짐 · 마지막 응답 기록 없음")).toBeInTheDocument();
    server.use(http.get(`${BASE}/health`, () => HttpResponse.json({ ...health, now: "2026-10-24T08:01:00Z" })));
    await userEvent.click(screen.getByRole("button", { name: "연결 확인" }));
    expect(await screen.findByText("BE 켜짐 · 17:01:00 응답")).toBeInTheDocument();
  });
});
