import { render, type RenderOptions } from "@testing-library/react";
import { RouterContext } from "next/dist/shared/lib/router-context.shared-runtime";
import type { NextRouter } from "next/router";
import type { ReactElement, ReactNode } from "react";
import { vi } from "vitest";
import { ToastProvider } from "../components/Toast";
import { ConnectionProvider } from "../lib/ConnectionProvider";
import { CatalogProvider } from "../ui/CatalogProvider";
import { saveConn } from "../lib/connection";
import { saveSnap, type SnapKey } from "../lib/snapshot";
import { healthAnswers } from "./handlers";
import { server } from "./server";

/** "none" = nothing saved on the device (first-connect screen); the others are a saved connection whose /health answers that way. */
export type TestConn = "online" | "offline" | "unauthorized" | "safe_mode" | "none";

export const TEST_BE_URL = "https://gp76.example.ts.net";
export const TEST_TOKEN = "test-token-not-real";

export interface ProviderOptions extends Omit<RenderOptions, "wrapper"> {
  /** Connection state for screens; the real ConnectionProvider runs against MSW answers for it. */
  conn?: TestConn;
  /** Current route, e.g. "/todos/?tab=week". */
  route?: string;
  /** Wrap in CatalogProvider (loads GET /ui/catalog) for tests that draw `ui_*` parts through UiPart. */
  catalog?: boolean;
}

/** A snapshot kept on the device for `beUrl`, as a good answer from it leaves one (it is saved only while connected there). */
export async function seedSnap(key: SnapKey, data: unknown, beUrl = TEST_BE_URL): Promise<void> {
  saveConn({ beUrl, token: TEST_TOKEN });
  await saveSnap(key, data, beUrl);
}

export function mockRouter(route = "/"): NextRouter {
  const url = new URL(route, "https://app.test");
  const query = Object.fromEntries(url.searchParams.entries());
  return {
    route: url.pathname,
    pathname: url.pathname,
    asPath: route,
    basePath: "",
    query,
    isLocaleDomain: false,
    isReady: true,
    isPreview: false,
    isFallback: false,
    push: vi.fn(async () => true),
    replace: vi.fn(async () => true),
    reload: vi.fn(),
    back: vi.fn(),
    forward: vi.fn(),
    prefetch: vi.fn(async () => undefined),
    beforePopState: vi.fn(),
    events: { on: vi.fn(), off: vi.fn(), emit: vi.fn() },
  };
}

export function renderWithProviders(ui: ReactElement, options: ProviderOptions = {}) {
  const { conn = "online", route = "/", catalog = false, ...rest } = options;
  const router = mockRouter(route);
  if (conn !== "none") saveConn({ beUrl: TEST_BE_URL, token: TEST_TOKEN });
  if (conn === "offline") server.use(healthAnswers.unreachable());
  if (conn === "unauthorized") server.use(healthAnswers.unauthorized());
  if (conn === "safe_mode") server.use(healthAnswers.safeMode());
  const Wrapper = ({ children }: { children: ReactNode }) => (
    <RouterContext.Provider value={router}>
      <ConnectionProvider>
        <ToastProvider>{catalog ? <CatalogProvider>{children}</CatalogProvider> : children}</ToastProvider>
      </ConnectionProvider>
    </RouterContext.Provider>
  );
  return { router, ...render(ui, { wrapper: Wrapper, ...rest }) };
}
