import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ConnectionProvider } from "../lib/ConnectionProvider";
import { ORIGIN } from "./handlers";

const router = { asPath: "/", pathname: "/", replace: vi.fn(async () => true) };
vi.mock("next/router", () => ({ useRouter: () => router }));

const { Shell } = await import("../pages/_app");

function renderShell(path: string) {
  router.asPath = path;
  return render(
    <ConnectionProvider>
      <Shell>
        <p>화면 내용</p>
      </Shell>
    </ConnectionProvider>,
  );
}

describe("shell", () => {
  beforeEach(() => router.replace.mockClear());

  it("sends a browser without a connection to settings", async () => {
    renderShell("/");
    await waitFor(() => expect(router.replace).toHaveBeenCalledWith("/settings/"));
    expect(screen.queryByText("화면 내용")).toBeNull();
  });

  it("stays on settings without a connection", async () => {
    renderShell("/settings/");
    expect(await screen.findByText("화면 내용")).toBeInTheDocument();
    expect(router.replace).not.toHaveBeenCalled();
  });

  it("puts the band and the nav above every screen", async () => {
    localStorage.setItem("mp.connection", JSON.stringify({ beUrl: ORIGIN, token: "fake-token-abc" }));
    renderShell("/");
    expect(await screen.findByText("BE 켜짐 · 17:00:05 응답")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "비서 상태" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByText("화면 내용")).toBeInTheDocument();
    expect(router.replace).not.toHaveBeenCalled();
  });

  it("links every screen in the nav, marking the open one", async () => {
    localStorage.setItem("mp.connection", JSON.stringify({ beUrl: ORIGIN, token: "fake-token-abc" }));
    renderShell("/tasks/");
    await screen.findByText("화면 내용");
    const nav = screen.getByRole("navigation", { name: "화면" });
    const links = Array.from(nav.querySelectorAll("ul a")).map((a) => [a.textContent, a.getAttribute("href")]);
    expect(links).toEqual([
      ["비서 상태", "/"],
      ["할 일", "/tasks/"],
      ["인생곡선", "/curve/"],
      ["상태창", "/status/"],
      ["설정", "/settings/"],
    ]);
    expect(screen.getByRole("link", { name: "할 일" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: "상태창" })).not.toHaveAttribute("aria-current");
  });

  it("nav_links_have_pictograms_hidden_from_screen_readers", async () => {
    localStorage.setItem("mp.connection", JSON.stringify({ beUrl: ORIGIN, token: "fake-token-abc" }));
    renderShell("/tasks/");
    await screen.findByText("화면 내용");
    const nav = screen.getByRole("navigation", { name: "화면" });
    const icons = Array.from(nav.querySelectorAll("ul a")).map((a) => {
      const svg = a.querySelector("svg.pictogram");
      return [a.getAttribute("href"), svg?.querySelector("use")?.getAttribute("href"), svg?.getAttribute("aria-hidden")];
    });
    expect(icons).toEqual([
      ["/", "#p-home", "true"],
      ["/tasks/", "#p-todo", "true"],
      ["/curve/", "#p-curve", "true"],
      ["/status/", "#p-status", "true"],
      ["/settings/", "#p-settings", "true"],
    ]);
    // The names stay words: a link's accessible name is its label alone.
    expect(screen.getByRole("link", { name: "상태창" })).toBeInTheDocument();
  });
});
