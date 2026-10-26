import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ConnectionProvider, useConnection } from "../lib/ConnectionProvider";
import { BASE, ORIGIN, PAIRED, healthAnswers, pairAnswers } from "./handlers";
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
  // a browser with no API token saved opens on the pairing code: the token form is one link away
  const toToken = await screen.findByRole("button", { name: /토큰으로 연결|연결 코드로 연결/ });
  if (toToken.textContent === "토큰으로 연결") await user.click(toToken);
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
    await waitFor(() => expect(router.push).toHaveBeenCalledWith("/"));
    expect(saved()).toEqual({ beUrl: ORIGIN, token: "fake-token-abc", kind: "api" });
    // the band on the home screen says it is connected: no notice of its own here
    expect(document.querySelector('.notice[data-kind="ok"]')).toBeNull();
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
    expect(saved()).toEqual({ beUrl: ORIGIN, token: "fake-token-abc", kind: "api" });
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
    await waitFor(() => expect(router.push).toHaveBeenCalledWith("/"));
    await waitFor(() => expect(screen.getByTestId("probe")).toHaveTextContent("ok"));
  });

  it("fills the saved connection", async () => {
    localStorage.setItem("mp.connection", JSON.stringify({ beUrl: ORIGIN, token: "fake-token-abc" }));
    renderSettings();
    expect(await screen.findByDisplayValue(`${ORIGIN}/api/v1`)).toBeInTheDocument();
  });
});

// Device pairing spec 5.3, 6, 6.1, 9.
describe("settings pairing code", () => {
  // Every `POST /pair` body the BE got in this test.
  let pairs: unknown[] = [];
  const recordPairs = (answer: () => Response) =>
    http.post(`${BASE}/pair`, async ({ request }) => {
      pairs.push({ type: request.headers.get("content-type"), auth: request.headers.get("authorization"), body: await request.json() });
      return answer();
    });
  const okPair = () => recordPairs(() => HttpResponse.json(PAIRED, { status: 201 }));
  const box = (n: number) => screen.getByLabelText(`연결 코드 ${n}번째 숫자`);
  const boxValues = () => [1, 2, 3, 4, 5, 6].map((n) => (box(n) as HTMLInputElement).value).join("");

  beforeEach(() => {
    router.push.mockClear();
    pairs = [];
    window.history.replaceState(null, "", "/settings/");
  });
  afterEach(() => vi.unstubAllEnvs());

  async function typeUrl(url: string) {
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText("BE 주소"), url);
    return user;
  }

  it("opens on six digit boxes for the one-time code", async () => {
    renderSettings();
    await screen.findByLabelText("BE 주소");
    expect(screen.queryByLabelText("API 토큰")).toBeNull();
    const first = box(1);
    expect(first).toHaveAttribute("inputmode", "numeric");
    expect(first).toHaveAttribute("autocomplete", "one-time-code");
    expect(box(6)).toHaveAttribute("inputmode", "numeric");
  });

  it("spreads a pasted code and sends it on the sixth digit", async () => {
    server.use(okPair());
    renderSettings();
    const user = await typeUrl(`${ORIGIN}/api/v1`);
    await user.click(box(1));
    await user.paste("482 913");
    await waitFor(() => expect(router.push).toHaveBeenCalledWith("/"));
    expect(pairs).toEqual([
      { type: "application/json", auth: null, body: { code: "482913", client: "dashboard", label: "Linux · 대시보드" } },
    ]);
    expect(saved()).toEqual({ beUrl: ORIGIN, token: "fake-device-token", kind: "device", deviceId: 7 });
  });

  it("sends when the sixth digit is typed, not before", async () => {
    server.use(okPair());
    renderSettings();
    const user = await typeUrl(ORIGIN);
    await user.click(box(1));
    await user.keyboard("48291");
    expect(boxValues()).toBe("48291");
    expect(pairs).toHaveLength(0);
    await user.keyboard("3");
    await waitFor(() => expect(router.push).toHaveBeenCalledWith("/"));
    expect(pairs).toHaveLength(1);
  });

  it("checks the new token with /health before going home", async () => {
    server.use(okPair(), healthAnswers.unreachable());
    renderSettings();
    const user = await typeUrl(ORIGIN);
    await user.click(box(1));
    await user.paste("482913");
    expect(await screen.findByText("BE가 켜지면 다시 보여 드릴게요.")).toBeInTheDocument();
    expect(screen.getByText("저장했어요.")).toBeInTheDocument();
    expect(router.push).not.toHaveBeenCalled();
    expect(saved()).toEqual({ beUrl: ORIGIN, token: "fake-device-token", kind: "device", deviceId: 7 });
  });

  it("says a wrong or expired code and empties the boxes", async () => {
    server.use(pairAnswers.badCode());
    renderSettings();
    const user = await typeUrl(ORIGIN);
    await user.click(box(1));
    await user.paste("482913");
    expect(await screen.findByRole("alert")).toHaveTextContent("코드가 맞지 않거나 만료됐어요. 연결된 기기에서 새 코드를 만들어 주세요.");
    expect(boxValues()).toBe("");
    expect(box(1)).toHaveFocus();
    expect(saved()).toBeNull();
  });

  it("moves to the token form on an old BE without /pair", async () => {
    server.use(pairAnswers.oldBe());
    renderSettings();
    const user = await typeUrl(ORIGIN);
    await user.click(box(1));
    await user.paste("482913");
    expect(await screen.findByRole("alert")).toHaveTextContent("BE를 먼저 업데이트해야 해요. 지금은 토큰으로 연결해 주세요.");
    expect(screen.getByLabelText("API 토큰")).toBeInTheDocument();
    expect(screen.getByLabelText("BE 주소")).toHaveValue(ORIGIN);
    expect(saved()).toBeNull();
  });

  it.each([
    ["the BE is off", pairAnswers.unreachable, "BE가 켜지면"],
    ["too many tries", pairAnswers.tooMany, "잠시 뒤에 다시 시도해 주세요."],
    ["safe mode", pairAnswers.safeMode, "데이터베이스 점검이 필요해요."],
  ])("uses the usual notice when %s, saving nothing", async (_why, answer, text) => {
    server.use(answer());
    renderSettings();
    const user = await typeUrl(ORIGIN);
    await user.click(box(1));
    await user.paste("482913");
    expect(await screen.findByText(new RegExp(text))).toBeInTheDocument();
    expect(screen.queryByText("저장했어요.")).toBeNull();
    expect(saved()).toBeNull();
  });

  it("checks the address before sending the code", async () => {
    server.use(okPair());
    renderSettings();
    const user = await typeUrl("https://desk.example.com");
    await user.click(box(1));
    await user.paste("482913");
    expect(await screen.findByRole("alert")).toHaveTextContent("이 대시보드가 허용한 tailnet 주소가 아니에요.");
    expect(pairs).toHaveLength(0);
  });

  it("switches to the token form and back", async () => {
    renderSettings();
    await userEvent.click(await screen.findByRole("button", { name: "토큰으로 연결" }));
    expect(screen.getByLabelText("API 토큰")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "연결 코드로 연결" }));
    expect(box(1)).toBeInTheDocument();
  });

  describe("default BE address (spec 6.1)", () => {
    it("fills and folds a default that passes the check", async () => {
      vi.stubEnv("NEXT_PUBLIC_DEFAULT_BE_URL", `${ORIGIN}/api/v1`);
      server.use(okPair());
      renderSettings();
      expect(await screen.findByText(ORIGIN)).toBeInTheDocument();
      expect(screen.queryByLabelText("BE 주소")).toBeNull();
      const user = userEvent.setup();
      await user.click(box(1));
      await user.paste("482913");
      await waitFor(() => expect(router.push).toHaveBeenCalledWith("/"));
      expect(saved().beUrl).toBe(ORIGIN);
    });

    it("opens the address on 주소 바꾸기", async () => {
      vi.stubEnv("NEXT_PUBLIC_DEFAULT_BE_URL", ORIGIN);
      renderSettings();
      await userEvent.click(await screen.findByRole("button", { name: "주소 바꾸기" }));
      expect(screen.getByLabelText("BE 주소")).toHaveValue(ORIGIN);
    });

    it.each([
      ["absent", undefined],
      ["outside the tailnet", "https://desk.example.com"],
      ["not https", "http://desk.example.ts.net"],
    ])("leaves the address empty when %s", async (_why, value) => {
      if (value !== undefined) vi.stubEnv("NEXT_PUBLIC_DEFAULT_BE_URL", value);
      renderSettings();
      expect(await screen.findByLabelText("BE 주소")).toHaveValue("");
      expect(screen.queryByRole("button", { name: "주소 바꾸기" })).toBeNull();
    });
  });

  describe("#be=…&code=… (spec 3.3)", () => {
    it("fills both, sends at once and takes them off the address", async () => {
      server.use(okPair());
      window.history.replaceState(null, "", `/settings/#be=${encodeURIComponent(ORIGIN)}&code=482913`);
      renderSettings();
      await waitFor(() => expect(router.push).toHaveBeenCalledWith("/"));
      expect(window.location.hash).toBe("");
      expect(window.location.pathname).toBe("/settings/");
      expect(pairs).toEqual([expect.objectContaining({ body: expect.objectContaining({ code: "482913" }) })]);
      expect(saved()).toEqual({ beUrl: ORIGIN, token: "fake-device-token", kind: "device", deviceId: 7 });
    });

    it("beats the default address", async () => {
      vi.stubEnv("NEXT_PUBLIC_DEFAULT_BE_URL", "https://other.example.ts.net");
      server.use(okPair());
      window.history.replaceState(null, "", `/settings/#be=${encodeURIComponent(`${ORIGIN}/api/v1`)}&code=482913`);
      renderSettings();
      await waitFor(() => expect(router.push).toHaveBeenCalledWith("/"));
      expect(saved().beUrl).toBe(ORIGIN);
    });

    it("beats a saved API token and opens on the code", async () => {
      localStorage.setItem("mp.connection", JSON.stringify({ beUrl: "https://other.example.ts.net", token: "fake-token-abc" }));
      server.use(okPair());
      window.history.replaceState(null, "", `/settings/#be=${encodeURIComponent(ORIGIN)}&code=482913`);
      renderSettings();
      await waitFor(() => expect(router.push).toHaveBeenCalledWith("/"));
      expect(saved()).toEqual({ beUrl: ORIGIN, token: "fake-device-token", kind: "device", deviceId: 7 });
    });

    it("takes an address with no code off and waits for the digits", async () => {
      window.history.replaceState(null, "", `/settings/#be=${encodeURIComponent(ORIGIN)}`);
      renderSettings();
      expect(await screen.findByText(ORIGIN)).toBeInTheDocument();
      expect(window.location.hash).toBe("");
      expect(boxValues()).toBe("");
      expect(pairs).toHaveLength(0);
    });
  });

  describe("연결 지우기 (spec 5.4)", () => {
    let deletes: { path: string; auth: string | null }[] = [];
    const deleteAnswer = (status: number) =>
      http.delete(`${BASE}/devices/:id`, ({ request }) => {
        deletes.push({ path: new URL(request.url).pathname, auth: request.headers.get("authorization") });
        return status === 0 ? HttpResponse.error() : new HttpResponse(null, { status });
      });
    beforeEach(() => {
      deletes = [];
    });

    it.each([
      ["the BE revokes it", 204],
      ["the BE is off", 0],
      ["the device is already gone", 404],
    ])("revokes a device token first and forgets it when %s", async (_why, status) => {
      localStorage.setItem("mp.connection", JSON.stringify({ beUrl: ORIGIN, token: "fake-device-token", kind: "device", deviceId: 7 }));
      server.use(deleteAnswer(status));
      renderSettings();
      await userEvent.click(await screen.findByRole("button", { name: "연결 지우기" }));
      expect(await screen.findByText("이 브라우저의 연결을 지웠어요.")).toBeInTheDocument();
      expect(deletes).toEqual([{ path: "/api/v1/devices/7", auth: "Bearer fake-device-token" }]);
      expect(saved()).toBeNull();
      expect(screen.queryByRole("button", { name: "연결 지우기" })).toBeNull();
      expect(box(1)).toBeInTheDocument();
    });

    it("only forgets an API token", async () => {
      localStorage.setItem("mp.connection", JSON.stringify({ beUrl: ORIGIN, token: "fake-token-abc" }));
      server.use(deleteAnswer(204));
      renderSettings();
      await userEvent.click(await screen.findByRole("button", { name: "연결 지우기" }));
      expect(await screen.findByText("이 브라우저의 연결을 지웠어요.")).toBeInTheDocument();
      expect(deletes).toEqual([]);
      expect(saved()).toBeNull();
    });
  });
});
