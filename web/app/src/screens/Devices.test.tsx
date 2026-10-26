import "fake-indexeddb/auto";
import { cleanup, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { DeviceItem, PairStatus } from "../api/types.gen";
import { saveConn } from "../lib/connection";
import { copy } from "../lib/copy";
import { hardReplace } from "../lib/nav";
import { renderWithProviders, TEST_BE_URL } from "../test/render";
import { BASE, server } from "../test/server";
import DevicesPage from "../pages/devices";
import { Devices } from "./Devices";

vi.mock("../lib/nav", () => ({ hardReplace: vi.fn() }));
// The real QR library, with the text each QR was made from noted (the page itself keeps it nowhere).
const qrTexts = vi.hoisted(() => [] as string[]);
vi.mock("qrcode-generator", async (importOriginal) => {
  const real = ((await importOriginal()) as { default: (t: number, e: string) => { addData(d: string, m?: string): void } }).default;
  return {
    default: (t: number, e: string) => {
      const qr = real(t, e);
      const add = qr.addData.bind(qr);
      qr.addData = (d: string, m?: string) => {
        qrTexts.push(d);
        add(d, m);
      };
      return qr;
    },
  };
});
const lastQr = () => qrTexts[qrTexts.length - 1];
const BE_ENC = encodeURIComponent(TEST_BE_URL);

afterEach(() => {
  qrTexts.length = 0;
  vi.mocked(hardReplace).mockClear();
  vi.unstubAllEnvs();
});

// Device pairing spec 5.1, 5.2, 9장 (app).
const THIS: DeviceItem = { id: 7, label: "iPhone · 앱", client: "app", created_at: "2026-10-20T01:00:00Z", last_used_at: new Date().toISOString(), this_device: true };
const LAPTOP: DeviceItem = { id: 8, label: "Windows · 대시보드", client: "dashboard", created_at: "2026-10-21T01:00:00Z", last_used_at: "2026-10-25T03:00:00Z", this_device: false };
const TABLET: DeviceItem = { id: 9, label: "Android · 앱", client: "app", created_at: "2026-10-24T01:00:00Z", last_used_at: null, this_device: false };

function serve(devices: DeviceItem[] = [THIS, LAPTOP, TABLET], states: PairStatus[] = [{ state: "waiting" }]) {
  const calls = { lists: 0, deleted: [] as string[], made: 0, polls: 0 };
  let live = [...devices];
  server.use(
    http.get(`${BASE}/devices`, () => {
      calls.lists += 1;
      return HttpResponse.json({ devices: live });
    }),
    http.delete(`${BASE}/devices/:id`, ({ params }) => {
      calls.deleted.push(String(params.id));
      live = live.filter((d) => String(d.id) !== params.id);
      return new HttpResponse(null, { status: 204 });
    }),
    http.post(`${BASE}/devices/pair`, () => {
      calls.made += 1;
      const expires = new Date(Date.now() + 5 * 60_000).toISOString();
      return HttpResponse.json({ code: calls.made === 1 ? "482913" : "105377", expires_at: expires }, { status: 201 });
    }),
    http.get(`${BASE}/devices/pair`, () => {
      const s = states[Math.min(calls.polls, states.length - 1)];
      calls.polls += 1;
      return HttpResponse.json(s);
    }),
  );
  return calls;
}

const row = (label: string) => screen.getByRole("button", { name: new RegExp(label) });

describe("Devices", () => {
  it("lists label, last use (or connect day) and this device, with the key note under it", async () => {
    serve();
    renderWithProviders(<Devices />, { route: "/devices/" });
    expect(await screen.findByText("Windows · 대시보드")).toBeInTheDocument();
    expect(within(row("iPhone")).getByText(copy.devices.lastUsed(copy.devices.today))).toBeInTheDocument();
    expect(within(row("iPhone")).getByText(copy.devices.thisDevice)).toBeInTheDocument();
    expect(within(row("Windows")).getByText(copy.devices.lastUsed("10월 25일"))).toBeInTheDocument();
    expect(within(row("Android")).getByText(copy.devices.connectedOn("10월 24일"))).toBeInTheDocument();
    expect(within(row("Windows")).queryByText(copy.devices.thisDevice)).toBeNull();
    expect(screen.getByText(copy.devices.keyNote)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: copy.devices.back })).toHaveAttribute("href", "/more/");
  });

  it("the page shows the tab bar", async () => {
    serve();
    renderWithProviders(<DevicesPage />, { route: "/devices/" });
    expect(await screen.findByText("Windows · 대시보드")).toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: copy.tabs.navLabel })).toBeInTheDocument();
  });

  it("cuts another device after one confirmation and reads the list again", async () => {
    const calls = serve();
    renderWithProviders(<Devices />, { route: "/devices/" });
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: /Windows/ }));
    const sheet = await screen.findByRole("dialog");
    expect(within(sheet).getByText(copy.devices.revokeSummary)).toBeInTheDocument();
    await user.click(within(sheet).getByRole("button", { name: copy.devices.cancel }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(calls.deleted).toEqual([]);

    await user.click(row("Windows"));
    await user.click(within(await screen.findByRole("dialog")).getByRole("button", { name: copy.devices.revoke }));
    await waitFor(() => expect(screen.queryByText("Windows · 대시보드")).toBeNull());
    expect(calls.deleted).toEqual(["8"]);
    expect(calls.lists).toBe(2);
    expect(hardReplace).not.toHaveBeenCalled();
  });

  it("cutting this device clears the connection and goes to the connect screen", async () => {
    const calls = serve();
    renderWithProviders(<Devices />, { route: "/devices/" });
    saveConn({ beUrl: TEST_BE_URL, token: "device-token" }, { id: 7 });
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: /iPhone/ }));
    await user.click(within(await screen.findByRole("dialog")).getByRole("button", { name: copy.devices.revoke }));
    await waitFor(() => expect(hardReplace).toHaveBeenCalledWith("/connect/"));
    expect(calls.deleted).toEqual(["7"]);
    for (const k of ["mp.beUrl", "mp.token", "mp.tokenKind", "mp.deviceId"]) expect(localStorage.getItem(k)).toBeNull();
  });

  it("cuts every other device, never this one", async () => {
    const calls = serve();
    renderWithProviders(<Devices />, { route: "/devices/" });
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: copy.devices.revokeOthers }));
    const sheet = await screen.findByRole("dialog");
    expect(within(sheet).getByText(copy.devices.revokeOthersSummary)).toBeInTheDocument();
    await user.click(within(sheet).getByRole("button", { name: copy.devices.revokeOthers }));
    await waitFor(() => expect(screen.queryByText("Android · 앱")).toBeNull());
    expect([...calls.deleted].sort()).toEqual(["8", "9"]);
    expect(screen.getByText("iPhone · 앱")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: copy.devices.revokeOthers })).toBeNull();
    expect(hardReplace).not.toHaveBeenCalled();
  });
});

describe("New device sheet", () => {
  async function openSheet(states?: PairStatus[]) {
    const calls = serve(undefined, states);
    renderWithProviders(<Devices pollMs={20} />, { route: "/devices/" });
    const user = userEvent.setup();
    await screen.findByText("Windows · 대시보드");
    await user.click(screen.getByRole("button", { name: copy.devices.add }));
    const sheet = await screen.findByRole("dialog", { name: copy.devices.sheetTitle });
    return { calls, user, sheet };
  }

  it("shows the code in 3 + 3, the time left, the app address and a QR for /connect/; no dashboard row without its address", async () => {
    const { sheet } = await openSheet();
    expect(await within(sheet).findByText("482 913")).toBeInTheDocument();
    expect(within(sheet).getByText(/^남은 시간 [45]:\d\d$/)).toBeInTheDocument();
    expect(within(sheet).getByText(copy.devices.appAddress)).toBeInTheDocument();
    expect(within(sheet).queryByText(copy.devices.dashboardAddress)).toBeNull();
    expect(within(sheet).queryByRole("radiogroup")).toBeNull();
    const qr = within(sheet).getByRole("img", { name: copy.devices.qrLabel });
    expect(qr.hasAttribute("data-qr")).toBe(false);
    expect(lastQr()).toBe(`${window.location.origin}/connect/#be=${BE_ENC}&code=482913`);
    expect(qr.querySelector("path")?.getAttribute("d")).toMatch(/^M\d/);
  });

  it("with NEXT_PUBLIC_DASHBOARD_URL: its row, and a QR for the dashboard's settings", async () => {
    vi.stubEnv("NEXT_PUBLIC_DASHBOARD_URL", "https://dash.example.app/");
    const { sheet, user } = await openSheet();
    await within(sheet).findByText("482 913");
    expect(within(sheet).getByText(copy.devices.dashboardAddress)).toBeInTheDocument();
    expect(within(sheet).getByText("dash.example.app")).toBeInTheDocument();
    await user.click(within(sheet).getByRole("radio", { name: copy.devices.qrDashboard }));
    expect(within(sheet).getByRole("img", { name: copy.devices.qrLabel })).toBeInTheDocument();
    expect(lastQr()).toBe(`https://dash.example.app/settings/#be=${BE_ENC}&code=482913`);
  });

  it("used: says which device and reads the list again", async () => {
    const { sheet, calls } = await openSheet([{ state: "waiting" }, { state: "used", device: { id: 10, label: "Windows · 대시보드" } }]);
    expect(await within(sheet).findByText(copy.devices.used("Windows · 대시보드"))).toBeInTheDocument();
    await waitFor(() => expect(calls.lists).toBe(2));
    expect(within(sheet).queryByText("482 913")).toBeNull();
  });

  it("expired: says so, and 다시 만들기 makes a new code", async () => {
    const { sheet, calls, user } = await openSheet([{ state: "expired" }]);
    expect(await within(sheet).findByText(copy.devices.expired, { exact: false })).toBeInTheDocument();
    await user.click(within(sheet).getByRole("button", { name: copy.devices.makeAgain }));
    expect(await within(sheet).findByText("105 377")).toBeInTheDocument();
    expect(calls.made).toBe(2);
  });

  it("stops asking on 401, 429 or safe mode and says so", async () => {
    for (const answer of [
      HttpResponse.json({ error: { code: "unauthorized", message: "x" } }, { status: 401 }),
      HttpResponse.json({ error: { code: "too_many_auth_failures", message: "x" } }, { status: 429 }),
      HttpResponse.json({ error: { code: "safe_mode", message: "x" } }, { status: 503 }),
    ]) {
      const { sheet, user } = await openSheet();
      let polls = 0;
      server.use(
        http.get(`${BASE}/devices/pair`, () => {
          polls += 1;
          return answer.clone();
        }),
      );
      expect(await within(sheet).findByText(/^코드를 만들지 못했어요/)).toBeInTheDocument();
      await new Promise((r) => setTimeout(r, 120));
      expect(polls).toBe(1);
      await user.keyboard("{Escape}");
      cleanup();
      server.resetHandlers();
    }
  });

  it("코드 다시 만들기 replaces the code; closing stops asking", async () => {
    const { sheet, calls, user } = await openSheet();
    await within(sheet).findByText("482 913");
    await user.click(within(sheet).getByRole("button", { name: copy.devices.remake }));
    expect(await within(sheet).findByText("105 377")).toBeInTheDocument();
    await waitFor(() => expect(calls.polls).toBeGreaterThan(0));
    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    const after = calls.polls;
    await new Promise((r) => setTimeout(r, 120));
    expect(calls.polls).toBe(after);
  });
});
