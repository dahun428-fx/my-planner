import { act, render, screen, waitFor } from "@testing-library/react";
import { RouterContext } from "next/dist/shared/lib/router-context.shared-runtime";
import { http, HttpResponse } from "msw";
import { useEffect } from "react";
import { describe, expect, it, vi } from "vitest";
import { apiFetch } from "../api/client";
import { mockRouter } from "../test/render";
import { BASE, server } from "../test/server";
import { ConnectionProvider, useConnection } from "./ConnectionProvider";
import { saveConn } from "./connection";

function Probe({ onReconnect }: { onReconnect?: () => void }) {
  const { state, onReconnect: sub, recheck } = useConnection();
  useEffect(() => (onReconnect ? sub(onReconnect) : undefined), [onReconnect, sub]);
  return (
    <>
      <output>{state?.kind ?? "none"}</output>
      <button type="button" onClick={() => void recheck()}>
        recheck
      </button>
    </>
  );
}

function mount(onReconnect?: () => void) {
  saveConn({ beUrl: "https://gp76.example.ts.net", token: "t" });
  return render(
    <RouterContext.Provider value={mockRouter("/")}>
      <ConnectionProvider>
        <Probe onReconnect={onReconnect} />
      </ConnectionProvider>
    </RouterContext.Provider>,
  );
}

describe("ConnectionProvider", () => {
  it("goes online from /health", async () => {
    mount();
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("online"));
  });

  it("a failed request flips to offline at once, and coming back calls onReconnect", async () => {
    const onReconnect = vi.fn();
    mount(onReconnect);
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("online"));
    server.use(http.get(`${BASE}/today`, () => HttpResponse.error()), http.get(`${BASE}/health`, () => HttpResponse.error()));
    await act(async () => void (await apiFetch("GET", "/today")));
    expect(screen.getByRole("status")).toHaveTextContent("offline");
    expect(onReconnect).not.toHaveBeenCalled();
    server.resetHandlers();
    await act(async () => screen.getByRole("button", { name: "recheck" }).click());
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("online"));
    expect(onReconnect).toHaveBeenCalledTimes(1);
  });

  it("401 and safe_mode from any request change the state", async () => {
    mount();
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("online"));
    server.use(http.get(`${BASE}/today`, () => HttpResponse.json({ error: { code: "unauthorized", message: "x" } }, { status: 401 })));
    await act(async () => void (await apiFetch("GET", "/today")));
    expect(screen.getByRole("status")).toHaveTextContent("unauthorized");
    server.use(http.get(`${BASE}/week`, () => HttpResponse.json({ error: { code: "safe_mode", message: "x" } }, { status: 503 })));
    await act(async () => void (await apiFetch("GET", "/week")));
    expect(screen.getByRole("status")).toHaveTextContent("safe_mode");
  });

  it("health 200 safe_mode is safe_mode", async () => {
    server.use(http.get(`${BASE}/health`, () => HttpResponse.json({ status: "safe_mode", now: "2026-10-24T08:00:05Z", version: { app: "0.2.0", api: "v1", schema: 10, ui_catalog: "2026-10-24.2" } })));
    mount();
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("safe_mode"));
  });

  it("three health errors in a row go offline; one error then ok stays online", async () => {
    mount();
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("online"));
    const recheck = () => act(async () => screen.getByRole("button", { name: "recheck" }).click());
    const bad = http.get(`${BASE}/health`, () => HttpResponse.json({ error: { code: "internal", message: "x" } }, { status: 500 }));
    server.use(bad);
    await recheck();
    await recheck();
    expect(screen.getByRole("status")).toHaveTextContent("online");
    server.resetHandlers();
    await recheck(); // an answer resets the streak
    server.use(bad);
    await recheck();
    await recheck();
    expect(screen.getByRole("status")).toHaveTextContent("online");
    await recheck();
    expect(screen.getByRole("status")).toHaveTextContent("offline");
  });

  it("a late answer from the old connection does not change the state", async () => {
    mount();
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("online"));
    let release: () => void = () => {};
    const gate = new Promise<void>((res) => (release = res));
    server.use(
      http.get(`${BASE}/today`, async () => {
        await gate;
        return HttpResponse.error();
      }),
    );
    const late = apiFetch("GET", "/today"); // sent with connection A
    await act(async () => saveConn({ beUrl: "https://gp76.example.ts.net", token: "other-key" })); // now B
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("online"));
    await act(async () => {
      release();
      await late;
    });
    expect(screen.getByRole("status")).toHaveTextContent("online");
  });
});
