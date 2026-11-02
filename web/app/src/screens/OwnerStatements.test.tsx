import { readFileSync } from "node:fs";
import { join } from "node:path";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { copy } from "../lib/copy";
import { copyPanel } from "../lib/copyPanel";
import { serveStatements, STATEMENTS } from "../test/panel";
import { serveActions } from "../test/parts";
import { renderWithProviders } from "../test/render";
import { BASE, server } from "../test/server";
import { OwnerStatements } from "./OwnerStatements";

describe("OwnerStatements (SP15 5.4)", () => {
  it("lists kind, area, text and date", async () => {
    serveStatements();
    renderWithProviders(<OwnerStatements />, { route: "/more/" });
    const first = (await screen.findByText(STATEMENTS[0].text)).closest("li")!;
    expect(within(first).getByText(`${copyPanel.statements.kinds.decision} · ${copy.areas.career} · 10/30`)).toBeInTheDocument();
    const second = screen.getByText(STATEMENTS[1].text).closest("li")!;
    expect(within(second).getByText(`${copyPanel.statements.kinds.preference} · 10/12`)).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: copyPanel.statements.retire })).toHaveLength(2);
  });

  it("지우기 sends retire_statement, the line goes, the undo toast shows", async () => {
    const be = serveStatements();
    const bodies = serveActions(() => {
      be.drop(5);
      return HttpResponse.json({ status: "applied", activity_id: 81, undo_id: 81, result: { ok: true }, confirmation: "내가 한 말 지움" });
    });
    renderWithProviders(<OwnerStatements />, { route: "/more/" });
    const first = (await screen.findByText(STATEMENTS[0].text)).closest("li")!;
    await userEvent.click(within(first).getByRole("button", { name: copyPanel.statements.retire }));
    await waitFor(() => expect(bodies).toHaveLength(1));
    expect(bodies[0].action).toBe("retire_statement");
    expect(bodies[0].args).toEqual({ id: 5 });
    await waitFor(() => expect(screen.queryByText(STATEMENTS[0].text)).toBeNull());
    expect(screen.getByText(STATEMENTS[1].text)).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: copy.activity.undo })).toBeInTheDocument();
  });

  it("says so when there are none", async () => {
    serveStatements([]);
    renderWithProviders(<OwnerStatements />, { route: "/more/" });
    expect(await screen.findByText(copyPanel.statements.empty)).toBeInTheDocument();
  });

  it("a failed read offers a retry", async () => {
    server.use(http.get(`${BASE}/owner-statements`, () => HttpResponse.json({ error: { code: "boom", message: "x" } }, { status: 500 })));
    renderWithProviders(<OwnerStatements />, { route: "/more/" });
    expect(await screen.findByRole("button", { name: copy.errors.retry })).toBeInTheDocument();
  });

  it("its stylesheet is not imported by _app (it ships with its own chunk)", () => {
    const app = readFileSync(join(__dirname, "../pages/_app.tsx"), "utf8");
    expect(app).not.toMatch(/OwnerStatements/);
    expect(app).not.toMatch(/LifeReport/);
  });
});
