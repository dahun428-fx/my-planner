import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { afterEach, describe, expect, it } from "vitest";
import { copy } from "../lib/copy";
import { device, fakeSub, storePushId, storedPushId, FAKE_VAPID, installPush, IPHONE_UA, type PushEnv, resetDevice } from "../test/push";
import { saveConn } from "../lib/connection";
import { renderWithProviders, TEST_BE_URL, TEST_TOKEN } from "../test/render";
import { BASE, server } from "../test/server";
import { Connect } from "./Connect";

let env: PushEnv | null = null;
afterEach(() => {
  env?.restore();
  env = null;
  resetDevice();
});

function servePush() {
  const posted: unknown[] = [];
  server.use(
    http.get(`${BASE}/push/vapid-public-key`, () => HttpResponse.json({ public_key: FAKE_VAPID })),
    http.post(`${BASE}/push/subscriptions`, async ({ request }) => {
      posted.push(await request.json());
      return HttpResponse.json({ id: 3 }, { status: 201 });
    }),
  );
  return posted;
}

// The key form is behind "열쇠로 연결" since device pairing (spec 5.3).
async function keyMode() {
  const user = userEvent.setup();
  await user.click(await screen.findByRole("button", { name: copy.connect.useKey }));
  return user;
}

async function fill() {
  const user = await keyMode();
  await user.type(await screen.findByLabelText(copy.connect.urlLabel), "https://gp76.example.ts.net");
  await user.type(screen.getByLabelText(copy.connect.tokenLabel), "good-token");
  return user;
}

describe("Connect with push (iPhone home screen app)", () => {
  it("start with push subscribes then goes today", async () => {
    env = installPush({ answer: "granted" });
    device(IPHONE_UA, { standalone: true });
    const posted = servePush();
    const { router } = renderWithProviders(<Connect />, { conn: "none", route: "/connect/" });
    const user = await fill();
    expect(screen.queryByRole("button", { name: copy.connect.start })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: copy.connect.startWithPush }));
    await waitFor(() => expect(router.push).toHaveBeenCalledWith("/"));
    expect(env.requestPermission).toHaveBeenCalled();
    expect(posted).toHaveLength(1);
    expect(storedPushId()).toEqual({ beUrl: TEST_BE_URL, id: 3 });
    expect(localStorage.getItem("mp.token")).toBe("good-token");
  });

  it("denied still goes today", async () => {
    env = installPush({ answer: "denied" });
    device(IPHONE_UA, { standalone: true });
    const posted = servePush();
    const { router } = renderWithProviders(<Connect />, { conn: "none", route: "/connect/" });
    const user = await fill();
    await user.click(screen.getByRole("button", { name: copy.connect.startWithPush }));
    await waitFor(() => expect(router.push).toHaveBeenCalledWith("/"));
    expect(posted).toEqual([]);
    expect(localStorage.getItem("mp.pushId")).toBeNull();
    expect(localStorage.getItem("mp.token")).toBe("good-token");
  });

  it("push later goes today without asking", async () => {
    env = installPush({ answer: "granted" });
    device(IPHONE_UA, { standalone: true });
    const posted = servePush();
    const { router } = renderWithProviders(<Connect />, { conn: "none", route: "/connect/" });
    const user = await fill();
    await user.click(screen.getByRole("button", { name: copy.connect.pushLater }));
    await waitFor(() => expect(router.push).toHaveBeenCalledWith("/"));
    expect(env.requestPermission).not.toHaveBeenCalled();
    expect(posted).toEqual([]);
  });

  it("a wrong key saves nothing and subscribes nothing", async () => {
    env = installPush({ answer: "granted" });
    device(IPHONE_UA, { standalone: true });
    const posted = servePush();
    server.use(http.get(`${BASE}/health`, () => HttpResponse.json({ error: { code: "unauthorized", message: "x" } }, { status: 401 })));
    const { router } = renderWithProviders(<Connect />, { conn: "none", route: "/connect/" });
    const user = await fill();
    await user.click(screen.getByRole("button", { name: copy.connect.startWithPush }));
    expect(await screen.findByText(copy.connect.badToken)).toBeInTheDocument();
    expect(router.push).not.toHaveBeenCalled();
    expect(posted).toEqual([]);
  });

  it("connecting to another BE drops the old BE's push subscription without asking it", async () => {
    const OLD = "https://old.example.ts.net";
    const sub = fakeSub();
    env = installPush({ permission: "granted", existing: sub });
    device(IPHONE_UA, { standalone: true });
    saveConn({ beUrl: OLD, token: TEST_TOKEN });
    storePushId(3, OLD);
    servePush();
    const { router } = renderWithProviders(<Connect />, { conn: "none", route: "/connect/" });
    const user = await fill();
    await user.click(screen.getByRole("button", { name: copy.connect.pushLater }));
    await waitFor(() => expect(router.push).toHaveBeenCalledWith("/"));
    expect(sub.unsubscribe).toHaveBeenCalledOnce(); // no DELETE goes anywhere: no handler for it
    expect(storedPushId()).toBeNull();
    expect(localStorage.getItem("mp.beUrl")).toBe(TEST_BE_URL);
  });

  it("re-entering the same BE keeps the subscription", async () => {
    const sub = fakeSub();
    env = installPush({ permission: "granted", existing: sub });
    device(IPHONE_UA, { standalone: true });
    saveConn({ beUrl: TEST_BE_URL, token: "old-token" });
    storePushId(3);
    const { router } = renderWithProviders(<Connect />, { conn: "none", route: "/connect/" });
    const user = await fill();
    await user.click(screen.getByRole("button", { name: copy.connect.pushLater }));
    await waitFor(() => expect(router.push).toHaveBeenCalledWith("/"));
    expect(sub.unsubscribe).not.toHaveBeenCalled();
    expect(storedPushId()).toEqual({ beUrl: TEST_BE_URL, id: 3 });
  });

  it("an address that cannot be used does not ask for permission", async () => {
    env = installPush({ answer: "granted" });
    device(IPHONE_UA, { standalone: true });
    renderWithProviders(<Connect />, { conn: "none", route: "/connect/" });
    const user = await keyMode();
    await user.type(await screen.findByLabelText(copy.connect.urlLabel), "http://gp76.example.ts.net");
    await user.type(screen.getByLabelText(copy.connect.tokenLabel), "good-token");
    await user.click(screen.getByRole("button", { name: copy.connect.startWithPush }));
    expect(await screen.findByText(copy.connect.notHttps)).toBeInTheDocument();
    expect(env.requestPermission).not.toHaveBeenCalled();
  });

  it("an empty key does not ask for permission", async () => {
    env = installPush({ answer: "granted" });
    device(IPHONE_UA, { standalone: true });
    renderWithProviders(<Connect />, { conn: "none", route: "/connect/" });
    const user = await keyMode();
    await user.type(await screen.findByLabelText(copy.connect.urlLabel), "https://gp76.example.ts.net");
    await user.type(screen.getByLabelText(copy.connect.tokenLabel), "   ");
    await user.click(screen.getByRole("button", { name: copy.connect.startWithPush }));
    expect(env.requestPermission).not.toHaveBeenCalled();
  });

  it("a subscription that fails says so and still goes today", async () => {
    env = installPush({ answer: "granted" });
    device(IPHONE_UA, { standalone: true });
    server.use(
      http.get(`${BASE}/push/vapid-public-key`, () => HttpResponse.json({ public_key: FAKE_VAPID })),
      http.post(`${BASE}/push/subscriptions`, () => HttpResponse.json({ error: { code: "invalid_request", message: "x" } }, { status: 400 })),
    );
    const { router } = renderWithProviders(<Connect />, { conn: "none", route: "/connect/" });
    const user = await fill();
    await user.click(screen.getByRole("button", { name: copy.connect.startWithPush }));
    await waitFor(() => expect(router.push).toHaveBeenCalledWith("/"));
    expect(await screen.findByText(copy.settings.pushTurnOnFailed)).toBeInTheDocument();
  });

  it("a BE without push says so and still goes today", async () => {
    env = installPush({ answer: "granted" });
    device(IPHONE_UA, { standalone: true });
    server.use(http.get(`${BASE}/push/vapid-public-key`, () => HttpResponse.json({ error: { code: "not_found", message: "x" } }, { status: 404 })));
    const { router } = renderWithProviders(<Connect />, { conn: "none", route: "/connect/" });
    const user = await fill();
    await user.click(screen.getByRole("button", { name: copy.connect.startWithPush }));
    await waitFor(() => expect(router.push).toHaveBeenCalledWith("/"));
    expect(await screen.findByText(copy.settings.pushUnavailable)).toBeInTheDocument();
  });
});
