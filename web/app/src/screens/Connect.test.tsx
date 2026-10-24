import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { afterEach, describe, expect, it } from "vitest";
import { copy } from "../lib/copy";
import { healthAnswers } from "../test/handlers";
import { BASE, server } from "../test/server";
import { renderWithProviders } from "../test/render";
import { Connect } from "./Connect";

const URL_IN = "https://gp76.example.ts.net";
const IPHONE = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15";
const IPAD_AS_MAC = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15";

const originalUa = navigator.userAgent;
function device(ua: string, opts: { standalone?: boolean; touch?: number } = {}) {
  Object.defineProperty(navigator, "userAgent", { configurable: true, value: ua });
  Object.defineProperty(navigator, "standalone", { configurable: true, value: opts.standalone });
  Object.defineProperty(navigator, "maxTouchPoints", { configurable: true, value: opts.touch ?? 0 });
}
afterEach(() => {
  Object.defineProperty(navigator, "userAgent", { configurable: true, value: originalUa });
  Reflect.deleteProperty(navigator, "standalone");
  Reflect.deleteProperty(navigator, "maxTouchPoints");
});

async function fill(url: string, token: string) {
  const user = userEvent.setup();
  await user.type(await screen.findByLabelText(copy.connect.urlLabel), url);
  await user.type(screen.getByLabelText(copy.connect.tokenLabel), token);
  return user;
}

function unauthorized() {
  server.use(healthAnswers.unauthorized());
}

describe("Connect", () => {
  it("success saves and goes today", async () => {
    const { router } = renderWithProviders(<Connect />, { conn: "none", route: "/connect/" });
    const user = await fill("  https://GP76.example.ts.net/api/v1/ ", " good-token\n");
    await user.click(screen.getByRole("button", { name: copy.connect.start }));
    await waitFor(() => expect(router.push).toHaveBeenCalledWith("/"));
    expect(localStorage.getItem("mp.beUrl")).toBe(URL_IN);
    expect(localStorage.getItem("mp.token")).toBe("good-token");
    expect(localStorage.getItem("mp.lastHealthOk")).toMatch(/^\d{4}-\d\d-\d\dT/);
  });

  it("checks when leaving the field and shows the result line", async () => {
    renderWithProviders(<Connect />, { conn: "none", route: "/connect/" });
    const user = await fill(URL_IN, "good-token");
    await user.tab();
    expect(await screen.findByText(copy.connect.ok)).toBeInTheDocument();
    expect(localStorage.getItem("mp.token")).toBeNull();
  });

  it("wrong token shows copy and stays", async () => {
    unauthorized();
    const { router } = renderWithProviders(<Connect />, { conn: "none", route: "/connect/" });
    const user = await fill(URL_IN, "bad-token");
    await user.click(screen.getByRole("button", { name: copy.connect.start }));
    expect(await screen.findByText(copy.connect.badToken)).toBeInTheDocument();
    expect(router.push).not.toHaveBeenCalled();
    expect(localStorage.getItem("mp.token")).toBeNull();
    expect(localStorage.getItem("mp.beUrl")).toBeNull();
  });

  it("unreachable shows tailscale hint", async () => {
    server.use(http.get(`${BASE}/health`, () => HttpResponse.error()));
    const { router } = renderWithProviders(<Connect />, { conn: "none", route: "/connect/" });
    const user = await fill(URL_IN, "tok");
    await user.click(screen.getByRole("button", { name: copy.connect.start }));
    expect(await screen.findByText(copy.connect.unreachable)).toBeInTheDocument();
    expect(router.push).not.toHaveBeenCalled();
  });

  it("refuses addresses outside the range with a reason", async () => {
    const { router } = renderWithProviders(<Connect />, { conn: "none", route: "/connect/" });
    const user = await fill("https://evil.com", "tok");
    await user.click(screen.getByRole("button", { name: copy.connect.start }));
    expect(await screen.findByText(copy.connect.outOfRange)).toBeInTheDocument();
    expect(router.push).not.toHaveBeenCalled();
    await user.clear(screen.getByLabelText(copy.connect.urlLabel));
    await user.type(screen.getByLabelText(copy.connect.urlLabel), "http://gp76.example.ts.net");
    await user.tab();
    expect(await screen.findByText(copy.connect.notHttps)).toBeInTheDocument();
  });

  it("Safari tab shows home-screen guide only", async () => {
    device(IPHONE, { standalone: false, touch: 5 });
    const { unmount } = renderWithProviders(<Connect />, { conn: "none", route: "/connect/" });
    expect(await screen.findByText(copy.connect.homeScreenGuide)).toBeInTheDocument();
    expect(screen.queryAllByRole("textbox")).toHaveLength(0);
    expect(document.querySelectorAll("input")).toHaveLength(0);
    unmount();

    device(IPAD_AS_MAC, { standalone: false, touch: 5 });
    renderWithProviders(<Connect />, { conn: "none", route: "/connect/" });
    expect(await screen.findByText(copy.connect.homeScreenGuide)).toBeInTheDocument();
    expect(document.querySelectorAll("input")).toHaveLength(0);
  });

  it("shows the form in the installed app and on a computer", async () => {
    device(IPHONE, { standalone: true, touch: 5 });
    const { unmount } = renderWithProviders(<Connect />, { conn: "none", route: "/connect/" });
    expect(await screen.findByLabelText(copy.connect.urlLabel)).toBeInTheDocument();
    unmount();
    device(IPAD_AS_MAC, { standalone: false, touch: 0 }); // a real Mac
    renderWithProviders(<Connect />, { conn: "none", route: "/connect/" });
    expect(await screen.findByLabelText(copy.connect.urlLabel)).toBeInTheDocument();
    expect(screen.queryByText(copy.connect.homeScreenGuide)).toBeNull();
  });

  it("token field is password", async () => {
    renderWithProviders(<Connect />, { conn: "none", route: "/connect/" });
    expect(await screen.findByLabelText(copy.connect.tokenLabel)).toHaveAttribute("type", "password");
    expect(screen.getByLabelText(copy.connect.urlLabel)).toHaveAttribute("type", "url");
  });
});
