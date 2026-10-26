import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { copy } from "../lib/copy";
import { saveConn } from "../lib/connection";
import { device, FAKE_VAPID, installPush, IPHONE_UA, type PushEnv, resetDevice } from "../test/push";
import { renderWithProviders, TEST_BE_URL } from "../test/render";
import { BASE, server } from "../test/server";
import { Connect } from "./Connect";

// Device pairing spec 5.3, 9장 (app): the pairing code form, the QR hash and the default BE address.
const WINDOWS_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36";
const DEVICE_TOKEN = "device-token-not-real";

let env: PushEnv | null = null;
beforeEach(() => {
  device(WINDOWS_UA);
  window.history.replaceState(null, "", "/connect/");
});
afterEach(() => {
  env?.restore();
  env = null;
  resetDevice();
  Reflect.deleteProperty(navigator, "maxTouchPoints");
  vi.unstubAllEnvs();
  window.history.replaceState(null, "", "/");
});

type Posted = { body: unknown; auth: string | null; type: string | null; url: string };

// POST /pair answering with `status` (201 = a device token for device 7), and /health remembering the key it got.
function servePair(status = 201, code = "bad_code", base = BASE) {
  const posted: Posted[] = [];
  const healthAuth: (string | null)[] = [];
  server.use(
    http.post(`${base}/pair`, async ({ request }) => {
      posted.push({ body: await request.json(), auth: request.headers.get("Authorization"), type: request.headers.get("Content-Type"), url: request.url });
      if (status === 201) return HttpResponse.json({ token: DEVICE_TOKEN, device: { id: 7, label: "Windows · 앱", client: "app" } }, { status: 201 });
      return HttpResponse.json({ error: { code, message: "x" } }, { status });
    }),
    http.get(`${base}/health`, ({ request }) => {
      healthAuth.push(request.headers.get("Authorization"));
      return undefined; // falls through to the default healthy answer
    }),
  );
  return { posted, healthAuth };
}

const box = (n: number) => screen.getByLabelText(copy.connect.digitLabel(n)) as HTMLInputElement;
const boxValues = () => [1, 2, 3, 4, 5, 6].map((n) => box(n).value).join("");

async function typeAddress(user: ReturnType<typeof userEvent.setup>) {
  await user.type(await screen.findByLabelText(copy.connect.urlLabel), TEST_BE_URL);
}

describe("Connect with a pairing code", () => {
  it("is the default: six numeric boxes, the first takes the one-time code", async () => {
    renderWithProviders(<Connect />, { conn: "none", route: "/connect/" });
    expect(await screen.findByLabelText(copy.connect.digitLabel(1))).toHaveAttribute("autocomplete", "one-time-code");
    for (const n of [1, 2, 3, 4, 5, 6]) expect(box(n)).toHaveAttribute("inputmode", "numeric");
    expect(screen.queryByLabelText(copy.connect.tokenLabel)).toBeNull();
    expect(screen.getByRole("button", { name: copy.connect.useKey })).toBeInTheDocument();
  });

  it("the sixth digit sends the code without a key, then saves the device token and goes today", async () => {
    const { posted, healthAuth } = servePair();
    const { router } = renderWithProviders(<Connect />, { conn: "none", route: "/connect/" });
    const user = userEvent.setup();
    await typeAddress(user);
    await user.type(box(1), "48291");
    expect(posted).toEqual([]);
    await user.keyboard("3");
    await waitFor(() => expect(router.push).toHaveBeenCalledWith("/"));
    expect(posted).toEqual([
      { body: { code: "482913", client: "app", label: "Windows · 앱" }, auth: null, type: "application/json", url: `${BASE}/pair` },
    ]);
    // The check before saving, then the provider's own once saved: both with the device token.
    expect(healthAuth.length).toBeGreaterThan(0);
    expect(new Set(healthAuth)).toEqual(new Set([`Bearer ${DEVICE_TOKEN}`]));
    expect(localStorage.getItem("mp.beUrl")).toBe(TEST_BE_URL);
    expect(localStorage.getItem("mp.token")).toBe(DEVICE_TOKEN);
    expect(localStorage.getItem("mp.tokenKind")).toBe("device");
    expect(localStorage.getItem("mp.deviceId")).toBe("7");
  });

  it("a pasted code is split across the boxes and sent", async () => {
    const { posted } = servePair();
    const { router } = renderWithProviders(<Connect />, { conn: "none", route: "/connect/" });
    const user = userEvent.setup();
    await typeAddress(user);
    await user.click(box(1));
    await user.paste("482 913");
    await waitFor(() => expect(router.push).toHaveBeenCalledWith("/"));
    expect(posted.map((p) => (p.body as { code: string }).code)).toEqual(["482913"]);
  });

  it("a wrong code says so and empties the boxes", async () => {
    const { posted } = servePair(401, "bad_code");
    const { router } = renderWithProviders(<Connect />, { conn: "none", route: "/connect/" });
    const user = userEvent.setup();
    await typeAddress(user);
    await user.type(box(1), "000000");
    expect(await screen.findByText(copy.connect.badCode)).toBeInTheDocument();
    expect(posted).toHaveLength(1);
    await waitFor(() => expect(boxValues()).toBe(""));
    expect(router.push).not.toHaveBeenCalled();
    expect(localStorage.getItem("mp.token")).toBeNull();
  });

  it("a BE without /pair (401 unauthorized) switches to the key form", async () => {
    servePair(401, "unauthorized");
    renderWithProviders(<Connect />, { conn: "none", route: "/connect/" });
    const user = userEvent.setup();
    await typeAddress(user);
    await user.type(box(1), "482913");
    expect(await screen.findByText(copy.connect.oldBe)).toBeInTheDocument();
    expect(screen.getByLabelText(copy.connect.tokenLabel)).toBeInTheDocument();
    expect(screen.getByLabelText(copy.connect.urlLabel)).toHaveValue(TEST_BE_URL);
    expect(localStorage.getItem("mp.token")).toBeNull();
  });

  it("unreachable, too many tries and safe mode keep the connect screen's words", async () => {
    server.use(http.post(`${BASE}/pair`, () => HttpResponse.error()));
    const { unmount } = renderWithProviders(<Connect />, { conn: "none", route: "/connect/" });
    let user = userEvent.setup();
    await typeAddress(user);
    await user.type(box(1), "482913");
    expect(await screen.findByText(copy.connect.unreachable)).toBeInTheDocument();
    unmount();

    server.use(http.post(`${BASE}/pair`, () => HttpResponse.json({ error: { code: "too_many_auth_failures", message: "x" } }, { status: 429 })));
    const second = renderWithProviders(<Connect />, { conn: "none", route: "/connect/" });
    user = userEvent.setup();
    await typeAddress(user);
    await user.type(box(1), "482913");
    expect(await screen.findByText(copy.status.tooMany)).toBeInTheDocument();
    second.unmount();

    server.use(http.post(`${BASE}/pair`, () => HttpResponse.json({ error: { code: "safe_mode", message: "x" } }, { status: 503 })));
    renderWithProviders(<Connect />, { conn: "none", route: "/connect/" });
    user = userEvent.setup();
    await typeAddress(user);
    await user.type(box(1), "482913");
    expect(await screen.findByText(copy.status.safeMode)).toBeInTheDocument();
  });

  it("in the iPhone home screen app the sixth digit waits for the button, which asks for notifications", async () => {
    env = installPush({ answer: "granted" });
    device(IPHONE_UA, { standalone: true });
    const { posted } = servePair();
    const subs: unknown[] = [];
    server.use(
      http.get(`${BASE}/push/vapid-public-key`, () => HttpResponse.json({ public_key: FAKE_VAPID })),
      http.post(`${BASE}/push/subscriptions`, async ({ request }) => {
        subs.push(request.headers.get("Authorization"));
        return HttpResponse.json({ id: 3 }, { status: 201 });
      }),
    );
    const { router } = renderWithProviders(<Connect />, { conn: "none", route: "/connect/" });
    const user = userEvent.setup();
    await typeAddress(user);
    await user.type(box(1), "482913");
    await new Promise((r) => setTimeout(r, 50));
    expect(posted).toEqual([]);
    expect(env.requestPermission).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: copy.connect.startWithPush }));
    await waitFor(() => expect(router.push).toHaveBeenCalledWith("/"));
    expect(env.requestPermission).toHaveBeenCalled();
    expect(posted).toHaveLength(1);
    expect(subs).toEqual([`Bearer ${DEVICE_TOKEN}`]);
    expect(localStorage.getItem("mp.tokenKind")).toBe("device");
  });

  it("a /health that refuses the new token revokes that new device and saves nothing", async () => {
    servePair();
    const revoked: { id: string; auth: string | null }[] = [];
    server.use(
      http.get(`${BASE}/health`, () => HttpResponse.json({ error: { code: "internal", message: "x" } }, { status: 500 })),
      http.delete(`${BASE}/devices/:id`, ({ params, request }) => {
        revoked.push({ id: String(params.id), auth: request.headers.get("Authorization") });
        return new HttpResponse(null, { status: 204 });
      }),
    );
    const { router } = renderWithProviders(<Connect />, { conn: "none", route: "/connect/" });
    const user = userEvent.setup();
    await typeAddress(user);
    await user.type(box(1), "482913");
    expect(await screen.findByText(copy.errors.block("internal"))).toBeInTheDocument();
    await waitFor(() => expect(revoked).toEqual([{ id: "7", auth: `Bearer ${DEVICE_TOKEN}` }]));
    expect(router.push).not.toHaveBeenCalled();
    expect(localStorage.getItem("mp.token")).toBeNull();
  });

  it("a new connection revokes the device token it replaces, and goes on when that fails", async () => {
    for (const answer of [204, 0]) {
      saveConn({ beUrl: TEST_BE_URL, token: "old-device-token" }, { id: 5 });
      servePair();
      const revoked: { id: string; auth: string | null }[] = [];
      server.use(
        http.delete(`${BASE}/devices/:id`, ({ params, request }) => {
          revoked.push({ id: String(params.id), auth: request.headers.get("Authorization") });
          return answer === 0 ? HttpResponse.error() : new HttpResponse(null, { status: answer });
        }),
      );
      const { router, unmount } = renderWithProviders(<Connect />, { conn: "none", route: "/connect/" });
      const user = userEvent.setup();
      await typeAddress(user);
      await user.type(box(1), "482913");
      await waitFor(() => expect(router.push).toHaveBeenCalledWith("/"));
      expect(revoked).toEqual([{ id: "5", auth: "Bearer old-device-token" }]);
      expect(localStorage.getItem("mp.token")).toBe(DEVICE_TOKEN);
      expect(localStorage.getItem("mp.deviceId")).toBe("7");
      unmount();
      server.resetHandlers();
      localStorage.clear();
    }
  });

  it("connecting with a key afterwards drops the device marks", async () => {
    saveConn({ beUrl: TEST_BE_URL, token: DEVICE_TOKEN }, { id: 7 });
    server.use(http.delete(`${BASE}/devices/:id`, () => new HttpResponse(null, { status: 204 })));
    const { router } = renderWithProviders(<Connect />, { conn: "none", route: "/connect/" });
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: copy.connect.useKey }));
    await user.type(screen.getByLabelText(copy.connect.urlLabel), TEST_BE_URL);
    await user.type(screen.getByLabelText(copy.connect.tokenLabel), "good-token");
    await user.click(screen.getByRole("button", { name: copy.connect.start }));
    await waitFor(() => expect(router.push).toHaveBeenCalledWith("/"));
    expect(localStorage.getItem("mp.token")).toBe("good-token");
    expect(localStorage.getItem("mp.tokenKind")).toBeNull();
    expect(localStorage.getItem("mp.deviceId")).toBeNull();
  });
});

describe("Connect from the QR hash (spec 3.3)", () => {
  it("fills both, goes on at once and clears the hash", async () => {
    const { posted } = servePair();
    window.history.replaceState(null, "", `/connect/#be=${TEST_BE_URL}&code=482913`);
    const { router } = renderWithProviders(<Connect />, { conn: "none", route: "/connect/" });
    await waitFor(() => expect(router.push).toHaveBeenCalledWith("/"));
    expect(window.location.hash).toBe("");
    expect(window.location.pathname).toBe("/connect/");
    expect(posted.map((p) => (p.body as { code: string }).code)).toEqual(["482913"]);
    expect(localStorage.getItem("mp.token")).toBe(DEVICE_TOKEN);
  });

  it("the hash address beats the default one", async () => {
    vi.stubEnv("NEXT_PUBLIC_DEFAULT_BE_URL", "https://other.example.ts.net");
    const other = servePair(201, "", "https://other.example.ts.net/api/v1");
    const { posted } = servePair();
    window.history.replaceState(null, "", `/connect/#be=${TEST_BE_URL}&code=482913`);
    const { router } = renderWithProviders(<Connect />, { conn: "none", route: "/connect/" });
    await waitFor(() => expect(router.push).toHaveBeenCalledWith("/"));
    expect(posted).toHaveLength(1);
    expect(other.posted).toEqual([]);
    expect(localStorage.getItem("mp.beUrl")).toBe(TEST_BE_URL);
  });

  it("an iPhone Safari tab does not read it: the home screen guide only", async () => {
    device(IPHONE_UA, { standalone: false });
    const { posted } = servePair();
    window.history.replaceState(null, "", `/connect/#be=${TEST_BE_URL}&code=482913`);
    renderWithProviders(<Connect />, { conn: "none", route: "/connect/" });
    expect(await screen.findByText(copy.connect.homeScreenGuide)).toBeInTheDocument();
    await new Promise((r) => setTimeout(r, 50));
    expect(posted).toEqual([]);
    expect(document.querySelectorAll("input")).toHaveLength(0);
    expect(localStorage.getItem("mp.token")).toBeNull();
    expect(location.hash).toBe(""); // unread, but not left for tab sync to carry
  });

  it("the be value may come percent-encoded (as the sheet writes it)", async () => {
    const { posted } = servePair();
    window.history.replaceState(null, "", `/connect/#be=${encodeURIComponent(TEST_BE_URL)}&code=482913`);
    const { router } = renderWithProviders(<Connect />, { conn: "none", route: "/connect/" });
    await waitFor(() => expect(router.push).toHaveBeenCalledWith("/"));
    expect(posted[0].url).toBe(`${BASE}/pair`);
  });
});

describe("Connect with NEXT_PUBLIC_DEFAULT_BE_URL (spec 6.1)", () => {
  it("fills the address and folds it; 주소 바꾸기 opens the field", async () => {
    vi.stubEnv("NEXT_PUBLIC_DEFAULT_BE_URL", `${TEST_BE_URL}/`);
    const { posted } = servePair();
    const { router } = renderWithProviders(<Connect />, { conn: "none", route: "/connect/" });
    expect(await screen.findByText("gp76.example.ts.net")).toBeInTheDocument();
    expect(screen.queryByLabelText(copy.connect.urlLabel)).toBeNull();
    const user = userEvent.setup();
    await user.type(box(1), "482913"); // only the code to type
    await waitFor(() => expect(router.push).toHaveBeenCalledWith("/"));
    expect(posted).toHaveLength(1);
  });

  it("주소 바꾸기 shows the field holding the default", async () => {
    vi.stubEnv("NEXT_PUBLIC_DEFAULT_BE_URL", TEST_BE_URL);
    renderWithProviders(<Connect />, { conn: "none", route: "/connect/" });
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: copy.connect.changeUrl }));
    expect(screen.getByLabelText(copy.connect.urlLabel)).toHaveValue(TEST_BE_URL);
  });

  it("without it the field starts empty", async () => {
    renderWithProviders(<Connect />, { conn: "none", route: "/connect/" });
    expect(await screen.findByLabelText(copy.connect.urlLabel)).toHaveValue("");
    expect(screen.queryByRole("button", { name: copy.connect.changeUrl })).toBeNull();
  });

  it("a default outside the allowed range is not used", async () => {
    vi.stubEnv("NEXT_PUBLIC_DEFAULT_BE_URL", "https://evil.example.com");
    renderWithProviders(<Connect />, { conn: "none", route: "/connect/" });
    expect(await screen.findByLabelText(copy.connect.urlLabel)).toHaveValue("");
  });
});
