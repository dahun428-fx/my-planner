import { vi } from "vitest";

/** The one `next/router` stand-in of the screens' tests: `vi.mock("next/router", async () => (await import("./router")).routerModule)`. */
export const router = { isReady: true, query: {} as Record<string, string>, replace: vi.fn(async () => true) };
export const routerModule = { useRouter: () => router };

export function resetRouter() {
  router.isReady = true;
  router.query = {};
  router.replace.mockClear();
}
