import { render, type RenderOptions } from "@testing-library/react";
import { RouterContext } from "next/dist/shared/lib/router-context.shared-runtime";
import type { NextRouter } from "next/router";
import type { ReactElement, ReactNode } from "react";
import { vi } from "vitest";

export type TestConn = "online" | "offline" | "unauthorized" | "safe_mode";

export interface ProviderOptions extends Omit<RenderOptions, "wrapper"> {
  /** Connection state for screens. ConnectionProvider (A01) reads this; A00 has no provider yet. */
  conn?: TestConn;
  /** Current route, e.g. "/todos/?tab=week". */
  route?: string;
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
  const { conn: _conn = "online", route = "/", ...rest } = options;
  const router = mockRouter(route);
  const Wrapper = ({ children }: { children: ReactNode }) => (
    <RouterContext.Provider value={router}>{children}</RouterContext.Provider>
  );
  return { router, ...render(ui, { wrapper: Wrapper, ...rest }) };
}
