import "fake-indexeddb/auto";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { clear, get, set } from "idb-keyval";
import { http, HttpResponse } from "msw";
import { afterEach, describe, expect, it, vi } from "vitest";
import { hardReplace } from "../lib/nav";
import { copy } from "../lib/copy";
import { PALETTES } from "../lib/theme";
import { formatKst } from "../lib/time";
import degraded from "../test/fixtures/health-degraded.json";
import paused from "../test/fixtures/health-paused.json";
import notify from "../test/fixtures/notify.json";
import notifyTelegram from "../test/fixtures/notify-effective-telegram.json";
import { device, storePushId, storedPushId, FAKE_VAPID, fakeSub, installPush, IPHONE_UA, type PushEnv, resetDevice } from "../test/push";
import { renderWithProviders, TEST_BE_URL } from "../test/render";
import { BASE, server } from "../test/server";
import { Settings } from "./Settings";

vi.mock("../lib/nav", () => ({ hardReplace: vi.fn() }));

let env: PushEnv | null = null;
afterEach(async () => {
  vi.mocked(hardReplace).mockClear();
  env?.restore();
  env = null;
  resetDevice();
  delete document.documentElement.dataset.palette;
  await clear();
});

// `hold`: write answers wait until released, so a second tap lands while the first is in flight.
function serve(opts: { notifyAnswer?: object; vapid?: boolean; hold?: boolean } = {}) {
  let release!: () => void;
  const gate = opts.hold ? new Promise<void>((r) => (release = r)) : Promise.resolve();
  const calls = {
    release: () => release?.(), put: [] as unknown[], chat: [] as string[], deleted: [] as string[], tests: 0, posted: 0 };
  server.use(
    http.get(`${BASE}/settings/notify`, () => HttpResponse.json(notify)),
    http.put(`${BASE}/settings/notify`, async ({ request }) => {
      calls.put.push(await request.json());
      await gate;
      return HttpResponse.json(opts.notifyAnswer ?? notify);
    }),
    http.get(`${BASE}/push/vapid-public-key`, () =>
      opts.vapid === false ? HttpResponse.json({ error: { code: "not_found", message: "x" } }, { status: 404 }) : HttpResponse.json({ public_key: FAKE_VAPID }),
    ),
    http.post(`${BASE}/push/subscriptions`, () => {
      calls.posted += 1;
      return HttpResponse.json({ id: 3 }, { status: 201 });
    }),
    http.delete(`${BASE}/push/subscriptions/:id`, ({ params }) => {
      calls.deleted.push(String(params.id));
      return new HttpResponse(null, { status: 204 });
    }),
    http.post(`${BASE}/push/test`, async () => {
      calls.tests += 1;
      await gate;
      return HttpResponse.json({ ok: 2, failed: 1 });
    }),
    http.post(`${BASE}/chat`, async ({ request }) => {
      const body = (await request.json()) as { message: { parts: { text: string }[] } };
      calls.chat.push(body.message.parts[0].text);
      await gate;
      return new HttpResponse('data: {"type":"start"}\n\ndata: {"type":"finish"}\n\ndata: [DONE]\n\n', {
        headers: { "Content-Type": "text/event-stream" },
      });
    }),
  );
  return calls;
}

const pushRow = () => screen.findByTestId("device-push");

describe("Settings", () => {
  it("primary channel change shows effective telegram", async () => {
    const calls = serve({ notifyAnswer: notifyTelegram });
    renderWithProviders(<Settings />, { route: "/settings/" });
    const user = userEvent.setup();
    const group = await screen.findByRole("radiogroup", { name: copy.settings.notifyWhere });
    await waitFor(() => expect(within(group).getByRole("radio", { name: copy.settings.primaryApp })).toHaveAttribute("aria-checked", "true"));
    expect(screen.getByText(copy.settings.notifyHelp)).toBeInTheDocument();
    expect(screen.queryByText(copy.settings.effectiveTelegram)).not.toBeInTheDocument();
    await user.click(within(group).getByRole("radio", { name: copy.settings.primaryTelegram }));
    await user.click(within(group).getByRole("radio", { name: copy.settings.primaryApp }));
    expect(await screen.findByText(copy.settings.effectiveTelegram)).toBeInTheDocument();
    expect(calls.put[0]).toEqual({ primary: "telegram" });
  });

  it("primary change sends once on a double tap", async () => {
    const calls = serve({ hold: true });
    renderWithProviders(<Settings />, { route: "/settings/" });
    const user = userEvent.setup();
    const group = await screen.findByRole("radiogroup", { name: copy.settings.notifyWhere });
    await waitFor(() => expect(within(group).getByRole("radio", { name: copy.settings.primaryApp })).toHaveAttribute("aria-checked", "true"));
    const telegram = within(group).getByRole("radio", { name: copy.settings.primaryTelegram });
    await user.dblClick(telegram);
    await waitFor(() => expect(calls.put).toHaveLength(1));
    calls.release();
    await waitFor(() => expect(within(group).getByRole("radio", { name: copy.settings.primaryApp })).toBeEnabled());
    expect(calls.put).toHaveLength(1);
  });

  it("primary change failure says so", async () => {
    serve();
    server.use(http.put(`${BASE}/settings/notify`, () => HttpResponse.json({ error: { code: "internal", message: "x" } }, { status: 500 })));
    renderWithProviders(<Settings />, { route: "/settings/" });
    const user = userEvent.setup();
    const group = await screen.findByRole("radiogroup", { name: copy.settings.notifyWhere });
    await waitFor(() => expect(within(group).getByRole("radio", { name: copy.settings.primaryApp })).toHaveAttribute("aria-checked", "true"));
    await user.click(within(group).getByRole("radio", { name: copy.settings.primaryTelegram }));
    expect(await screen.findByText(copy.actions.failed)).toBeInTheDocument();
    expect(within(group).getByRole("radio", { name: copy.settings.primaryApp })).toHaveAttribute("aria-checked", "true");
  });

  describe("device push states", () => {
    it("on", async () => {
      env = installPush({ permission: "granted", existing: fakeSub() });
      storePushId(3);
      serve();
      renderWithProviders(<Settings />, { route: "/settings/" });
      expect(await within(await pushRow()).findByText(copy.settings.pushOn)).toBeInTheDocument();
    });

    it("denied", async () => {
      env = installPush({ permission: "denied" });
      serve();
      renderWithProviders(<Settings />, { route: "/settings/" });
      const row = await pushRow();
      expect(await within(row).findByText(copy.settings.pushDenied)).toBeInTheDocument();
      expect(within(row).getByText(copy.settings.pushOff)).toBeInTheDocument();
    });

    it("home screen guide on an iPhone tab", async () => {
      env = installPush();
      device(IPHONE_UA, { standalone: false });
      serve();
      renderWithProviders(<Settings />, { route: "/settings/" });
      expect(await within(await pushRow()).findByText(copy.settings.needsHomeScreen)).toBeInTheDocument();
    });

    it("unsupported browser", async () => {
      serve();
      renderWithProviders(<Settings />, { route: "/settings/" });
      expect(await within(await pushRow()).findByText(copy.settings.pushUnsupported)).toBeInTheDocument();
    });

    it("BE without push", async () => {
      env = installPush({ permission: "granted" });
      serve({ vapid: false });
      renderWithProviders(<Settings />, { route: "/settings/" });
      expect(await within(await pushRow()).findByText(copy.settings.pushUnavailable)).toBeInTheDocument();
      expect(screen.queryByRole("button", { name: copy.settings.testPush })).not.toBeInTheDocument();
    });

    it("allow subscribes and turns on", async () => {
      env = installPush({ permission: "default", answer: "granted" });
      const calls = serve();
      renderWithProviders(<Settings />, { route: "/settings/" });
      const user = userEvent.setup();
      const allow = await within(await pushRow()).findByRole("button", { name: copy.settings.pushAllow });
      await user.dblClick(allow);
      expect(await within(await pushRow()).findByText(copy.settings.pushOn)).toBeInTheDocument();
      expect(calls.posted).toBe(1);
      expect(env.requestPermission).toHaveBeenCalledOnce();
      expect(storedPushId()).toEqual({ beUrl: TEST_BE_URL, id: 3 });
    });

    it("allow refused shows the denied guide", async () => {
      env = installPush({ permission: "default", answer: "denied" });
      serve();
      renderWithProviders(<Settings />, { route: "/settings/" });
      const user = userEvent.setup();
      await user.click(await within(await pushRow()).findByRole("button", { name: copy.settings.pushAllow }));
      expect(await within(await pushRow()).findByText(copy.settings.pushDenied)).toBeInTheDocument();
    });

    it("allow when iOS dropped the subscription", async () => {
      env = installPush({ permission: "granted", existing: null });
      storePushId(3);
      serve();
      renderWithProviders(<Settings />, { route: "/settings/" });
      expect(await within(await pushRow()).findByRole("button", { name: copy.settings.pushAllow })).toBeInTheDocument();
    });

    it("allow when the stored id belongs to another BE", async () => {
      env = installPush({ permission: "granted", existing: fakeSub() });
      storePushId(3, "https://other.example.ts.net");
      serve();
      renderWithProviders(<Settings />, { route: "/settings/" });
      expect(await within(await pushRow()).findByRole("button", { name: copy.settings.pushAllow })).toBeInTheDocument();
    });

    it("allow that cannot finish says so", async () => {
      env = installPush({ permission: "default", answer: "granted" });
      serve();
      server.use(http.post(`${BASE}/push/subscriptions`, () => HttpResponse.json({ error: { code: "invalid_request", message: "x" } }, { status: 400 })));
      renderWithProviders(<Settings />, { route: "/settings/" });
      const user = userEvent.setup();
      await user.click(await within(await pushRow()).findByRole("button", { name: copy.settings.pushAllow }));
      expect(await screen.findByText(copy.settings.pushTurnOnFailed)).toBeInTheDocument();
      expect(within(await pushRow()).getByRole("button", { name: copy.settings.pushAllow })).toBeInTheDocument();
    });
  });

  it("test push result", async () => {
    env = installPush({ permission: "granted", existing: fakeSub() });
    storePushId(3);
    const calls = serve({ hold: true });
    renderWithProviders(<Settings />, { route: "/settings/" });
    const user = userEvent.setup();
    const button = await screen.findByRole("button", { name: copy.settings.testPush });
    await waitFor(() => expect(button).toBeEnabled());
    await user.dblClick(button);
    calls.release();
    expect(await screen.findByText(copy.settings.testResult(2, 1))).toBeInTheDocument();
    expect(calls.tests).toBe(1);
    expect(copy.settings.testResult(2, 0)).toBe("2대에 보냈어요");
    expect(copy.settings.testResult(2, 1)).toBe("2대에 보냈고 1대에는 안 갔어요");
  });

  it("a test push the BE does not answer in 30 s says it is slow, not that the secretary is unreachable", async () => {
    env = installPush({ permission: "granted", existing: fakeSub() });
    storePushId(3);
    serve();
    server.use(http.post(`${BASE}/push/test`, () => new Promise<Response>(() => {})));
    renderWithProviders(<Settings />, { route: "/settings/" });
    const button = await screen.findByRole("button", { name: copy.settings.testPush });
    await waitFor(() => expect(button).toBeEnabled());
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    try {
      fireEvent.click(button);
      await vi.advanceTimersByTimeAsync(10_001);
      expect(screen.queryByText(copy.settings.testSlow)).toBeNull(); // still waiting past the usual 10 s
      await vi.advanceTimersByTimeAsync(20_000);
    } finally {
      vi.useRealTimers();
    }
    expect(await screen.findByText(copy.settings.testSlow)).toBeInTheDocument();
    expect(screen.queryByText(copy.actions.offline)).toBeNull();
  });

  it("test push with no devices says so", async () => {
    env = installPush({ permission: "granted", existing: fakeSub() });
    storePushId(3);
    serve();
    server.use(http.post(`${BASE}/push/test`, () => HttpResponse.json({ ok: 0, failed: 0 })));
    renderWithProviders(<Settings />, { route: "/settings/" });
    const user = userEvent.setup();
    const button = await screen.findByRole("button", { name: copy.settings.testPush });
    await waitFor(() => expect(button).toBeEnabled());
    await user.click(button);
    expect(await screen.findByText(copy.settings.testNoDevices)).toBeInTheDocument();
  });

  it("schedule is read-only constants", async () => {
    serve();
    renderWithProviders(<Settings />, { route: "/settings/" });
    const group = (await screen.findByRole("heading", { name: copy.settings.schedule })).closest("section") as HTMLElement;
    expect(within(group).getByText(copy.settings.weekdays)).toBeInTheDocument();
    expect(within(group).getByText("09:00 · 17:30")).toBeInTheDocument();
    expect(within(group).getByText(copy.settings.weekend)).toBeInTheDocument();
    expect(within(group).getByText("10:00 · 18:00")).toBeInTheDocument();
    expect(within(group).getByText(copy.settings.scheduleNote)).toBeInTheDocument();
    expect(within(group).queryAllByRole("button")).toEqual([]);
    expect(within(group).queryAllByRole("textbox")).toEqual([]);
  });

  it("pause sheet offers 1 3 7 14", async () => {
    const calls = serve({ hold: true });
    renderWithProviders(<Settings />, { route: "/settings/" });
    const user = userEvent.setup();
    const row = await screen.findByRole("button", { name: copy.settings.pauseRow });
    await waitFor(() => expect(row).toBeEnabled());
    await user.click(row);
    const sheet = await screen.findByRole("dialog", { name: copy.settings.pauseSheet });
    const days = within(sheet).getAllByRole("button").map((b) => b.textContent);
    expect(days).toEqual([1, 3, 7, 14].map((n) => copy.settings.pauseDays(n)));
    server.use(http.get(`${BASE}/health`, () => HttpResponse.json(paused)));
    await user.dblClick(within(sheet).getByRole("button", { name: copy.settings.pauseDays(7) }));
    calls.release();
    const until = copy.settings.pausedUntil(formatKst(paused.paused_until, copy.dateStyle.monthDayTime));
    expect(await screen.findByText(until)).toBeInTheDocument();
    expect(calls.chat).toEqual(["/pause 7"]);
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("pause that cannot be sent says so", async () => {
    serve();
    server.use(http.post(`${BASE}/chat`, () => HttpResponse.json({ error: { code: "internal", message: "x" } }, { status: 500 })));
    renderWithProviders(<Settings />, { route: "/settings/" });
    const user = userEvent.setup();
    const row = await screen.findByRole("button", { name: copy.settings.pauseRow });
    await waitFor(() => expect(row).toBeEnabled());
    await user.click(row);
    const sheet = await screen.findByRole("dialog", { name: copy.settings.pauseSheet });
    await user.click(within(sheet).getByRole("button", { name: copy.settings.pauseDays(3) }));
    expect(await screen.findByText(copy.actions.failed)).toBeInTheDocument();
  });

  it("paused shows until and resume", async () => {
    serve();
    server.use(http.get(`${BASE}/health`, () => HttpResponse.json(paused)));
    renderWithProviders(<Settings />, { route: "/settings/" });
    const user = userEvent.setup();
    expect(await screen.findByText(copy.settings.pausedUntil("10월 27일 18:00"))).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: copy.settings.pauseRow })).not.toBeInTheDocument();
    server.resetHandlers();
    const calls = serve();
    await user.dblClick(screen.getByRole("button", { name: copy.settings.resume }));
    expect(await screen.findByRole("button", { name: copy.settings.pauseRow })).toBeInTheDocument();
    expect(calls.chat).toEqual(["/unpause"]);
  });

  it("disconnect clears device and goes connect", async () => {
    env = installPush({ permission: "granted", existing: fakeSub() });
    storePushId(3);
    localStorage.setItem("mp.theme", "dark");
    localStorage.setItem("mp.palette", "sea");
    document.documentElement.dataset.palette = "sea";
    localStorage.setItem("mp.lastHealthOk", "2026-10-24T08:00:00Z");
    localStorage.setItem("other.key", "kept");
    await set("snap:today", { data: {}, savedAt: "2026-10-24T08:00:00Z", beUrl: TEST_BE_URL });
    await set("parts:1", []);
    await set("catalog", {});
    const calls = serve();
    renderWithProviders(<Settings />, { route: "/settings/" });
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: copy.settings.disconnect }));
    const sheet = await screen.findByRole("dialog", { name: copy.settings.disconnectSummary });
    await user.click(within(sheet).getByRole("button", { name: copy.settings.cancel }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(localStorage.getItem("mp.token")).not.toBeNull();

    await user.click(screen.getByRole("button", { name: copy.settings.disconnect }));
    const again = await screen.findByRole("dialog", { name: copy.settings.disconnectSummary });
    await user.dblClick(within(again).getByRole("button", { name: copy.settings.disconnectConfirm }));
    // A full page load, so nothing of the old connection stays in memory.
    await waitFor(() => expect(hardReplace).toHaveBeenCalledWith("/connect/"));
    expect(hardReplace).toHaveBeenCalledOnce();
    expect(calls.deleted).toEqual(["3"]);
    expect(env.current()?.unsubscribe).toHaveBeenCalledOnce();
    for (const k of ["mp.beUrl", "mp.token", "mp.lastHealthOk", "mp.pushId", "mp.theme", "mp.palette"]) expect(localStorage.getItem(k)).toBeNull();
    expect(localStorage.getItem("other.key")).toBe("kept");
    expect(await get("snap:today")).toBeUndefined();
    expect(await get("parts:1")).toBeUndefined();
    expect(await get("catalog")).toBeUndefined();
    expect(document.documentElement.hasAttribute("data-theme")).toBe(false);
    expect(document.documentElement.hasAttribute("data-palette")).toBe(false);
  });

  it("disconnect goes on when the BE cannot be reached", async () => {
    env = installPush({ permission: "granted", existing: fakeSub() });
    storePushId(3);
    serve();
    server.use(http.delete(`${BASE}/push/subscriptions/:id`, () => HttpResponse.error()));
    renderWithProviders(<Settings />, { route: "/settings/" });
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: copy.settings.disconnect }));
    const sheet = await screen.findByRole("dialog", { name: copy.settings.disconnectSummary });
    await user.click(within(sheet).getByRole("button", { name: copy.settings.disconnectConfirm }));
    await waitFor(() => expect(hardReplace).toHaveBeenCalledWith("/connect/"));
    expect(localStorage.getItem("mp.token")).toBeNull();
  });

  it("degraded telegram line only here", async () => {
    serve();
    server.use(http.get(`${BASE}/health`, () => HttpResponse.json(degraded)));
    renderWithProviders(<Settings />, { route: "/settings/" });
    expect(await screen.findByText(copy.status.telegramDown)).toBeInTheDocument();
  });

  it("connection group shows status, address and re-enter link, never the key", async () => {
    serve();
    localStorage.setItem("mp.lastHealthOk", new Date().toISOString());
    const { container } = renderWithProviders(<Settings />, { route: "/settings/" });
    expect(await screen.findByText(copy.settings.connectedChecked(copy.settings.checkedJustNow))).toBeInTheDocument();
    expect(screen.getByText(TEST_BE_URL.replace("https://", ""))).toBeInTheDocument();
    expect(screen.getByRole("link", { name: copy.settings.reenter })).toHaveAttribute("href", "/connect/");
    expect(container.textContent).not.toContain(localStorage.getItem("mp.token"));
  });

  it("theme segmented sets the theme", async () => {
    serve();
    renderWithProviders(<Settings />, { route: "/settings/" });
    const user = userEvent.setup();
    const group = await screen.findByRole("radiogroup", { name: copy.settings.theme });
    expect(within(group).getByRole("radio", { name: copy.settings.themeSystem })).toHaveAttribute("aria-checked", "true");
    await user.click(within(group).getByRole("radio", { name: copy.settings.themeDark }));
    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(localStorage.getItem("mp.theme")).toBe("dark");
    await user.click(within(group).getByRole("radio", { name: copy.settings.themeSystem }));
    expect(document.documentElement.hasAttribute("data-theme")).toBe(false);
  });

  it("colour presets: six swatches, ink chosen, a tap applies at once", async () => {
    serve();
    renderWithProviders(<Settings />, { route: "/settings/" });
    const user = userEvent.setup();
    const group = await screen.findByRole("radiogroup", { name: copy.settings.palette });
    const radios = within(group).getAllByRole("radio");
    expect(radios.map((r) => r.textContent)).toEqual(PALETTES.map((p) => copy.settings.palettes[p]));
    // Each swatch draws its own palette (data-palette on the swatch, colours from tokens.css).
    expect(radios.map((r) => r.querySelector("[data-palette]")?.getAttribute("data-palette"))).toEqual([...PALETTES]);
    expect(within(group).getByRole("radio", { name: copy.settings.palettes.ink })).toHaveAttribute("aria-checked", "true");
    expect(radios.filter((r) => r.getAttribute("aria-checked") === "true")).toHaveLength(1);

    await user.click(within(group).getByRole("radio", { name: copy.settings.palettes.forest }));
    expect(document.documentElement.dataset.palette).toBe("forest");
    expect(localStorage.getItem("mp.palette")).toBe("forest");
    expect(within(group).getByRole("radio", { name: copy.settings.palettes.forest })).toHaveAttribute("aria-checked", "true");
    expect(within(group).getByRole("radio", { name: copy.settings.palettes.ink })).toHaveAttribute("aria-checked", "false");

    // One tab stop; arrow keys move the choice.
    expect(radios.filter((r) => r.tabIndex === 0)).toEqual([within(group).getByRole("radio", { name: copy.settings.palettes.forest })]);
    await user.keyboard("{ArrowRight}");
    expect(document.documentElement.dataset.palette).toBe("sea");
    expect(within(group).getByRole("radio", { name: copy.settings.palettes.sea })).toHaveFocus();
    await user.keyboard("{End}");
    expect(document.documentElement.dataset.palette).toBe("lavender");
    await user.keyboard("{Home}");
    expect(document.documentElement.hasAttribute("data-palette")).toBe(false);
    expect(within(group).getByRole("radio", { name: copy.settings.palettes.ink })).toHaveAttribute("aria-checked", "true");
  });

  it("the saved palette shows as chosen", async () => {
    localStorage.setItem("mp.palette", "lavender");
    serve();
    renderWithProviders(<Settings />, { route: "/settings/" });
    const group = await screen.findByRole("radiogroup", { name: copy.settings.palette });
    await waitFor(() => expect(within(group).getByRole("radio", { name: copy.settings.palettes.lavender })).toHaveAttribute("aria-checked", "true"));
  });

  it("about shows app, BE and catalog versions", async () => {
    serve();
    renderWithProviders(<Settings />, { route: "/settings/" });
    const group = (await screen.findByRole("heading", { name: copy.settings.about })).closest("section") as HTMLElement;
    expect(within(group).getByText("0.1.0")).toBeInTheDocument();
    expect(await within(group).findByText("0.2.0")).toBeInTheDocument();
    expect(within(group).getByText("2026-10-24.4")).toBeInTheDocument();
  });

  it("no chat launcher", async () => {
    serve();
    renderWithProviders(<Settings />, { route: "/settings/" });
    await screen.findByRole("heading", { name: copy.settings.about });
    expect(screen.queryByRole("button", { name: copy.chat.launcher })).not.toBeInTheDocument();
    expect(screen.queryByText(copy.chat.launcher)).not.toBeInTheDocument();
  });

  it("writes are off while offline", async () => {
    serve();
    renderWithProviders(<Settings />, { route: "/settings/", conn: "offline" });
    expect(await screen.findByText(copy.status.offline)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: copy.settings.pauseRow })).toBeDisabled();
  });
});
