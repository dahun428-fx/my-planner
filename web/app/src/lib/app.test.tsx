import { render, waitFor } from "@testing-library/react";
import { RouterContext } from "next/dist/shared/lib/router-context.shared-runtime";
import type { AppProps } from "next/app";
import { describe, expect, it } from "vitest";
import { saveConn } from "./connection";
import { mockRouter } from "../test/render";
import App from "../pages/_app";

function mount(route: string) {
  const router = mockRouter(route);
  const Page = () => <p>page</p>;
  render(
    <RouterContext.Provider value={router}>
      <App {...({ Component: Page, pageProps: {}, router } as unknown as AppProps)} />
    </RouterContext.Provider>,
  );
  return router;
}

describe("_app", () => {
  it("redirects to connect without conn", async () => {
    const router = mount("/todos/");
    await waitFor(() => expect(router.replace).toHaveBeenCalledWith("/connect/"));
  });

  it("does not redirect from the connect screen", async () => {
    const router = mount("/connect/");
    await new Promise((r) => setTimeout(r, 20));
    expect(router.replace).not.toHaveBeenCalled();
  });

  it("stays put with a saved connection", async () => {
    saveConn({ beUrl: "https://gp76.example.ts.net", token: "t" });
    const router = mount("/todos/");
    await new Promise((r) => setTimeout(r, 20));
    expect(router.replace).not.toHaveBeenCalled();
  });
});
