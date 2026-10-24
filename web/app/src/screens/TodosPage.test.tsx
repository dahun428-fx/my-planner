import "fake-indexeddb/auto";
import { screen } from "@testing-library/react";
import { clear } from "idb-keyval";
import { http, HttpResponse } from "msw";
import { afterEach, describe, expect, it } from "vitest";
import { copy } from "../lib/copy";
import today from "../test/fixtures/today.json";
import week from "../test/fixtures/week.json";
import { renderWithProviders } from "../test/render";
import { BASE, server } from "../test/server";
import Page from "../pages/todos";

afterEach(async () => {
  await clear();
});

function serve() {
  server.use(
    http.get(`${BASE}/today`, () => HttpResponse.json(today)),
    http.get(`${BASE}/week`, () => HttpResponse.json(week)),
    http.get(`${BASE}/drafts`, () => HttpResponse.json({ items: [] })),
    http.get(`${BASE}/priorities`, () => HttpResponse.json({ cadence: "quarter", period: "2026-Q4", items: [] })),
  );
}

describe("todos page", () => {
  it.each([
    ["/todos/?tab=quarter", copy.todos.periods.quarter],
    ["/todos/?tab=day", copy.todos.periods.today],
    ["/todos/", copy.todos.periods.week],
    ["/todos/?tab=nonsense", copy.todos.periods.week],
  ])("%s selects %s", async (route, label) => {
    serve();
    renderWithProviders(<Page />, { route });
    expect(await screen.findByRole("radio", { name: label })).toHaveAttribute("aria-checked", "true");
  });
});
