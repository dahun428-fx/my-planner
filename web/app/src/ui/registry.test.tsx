import "fake-indexeddb/auto";
import { screen, waitFor } from "@testing-library/react";
import { clear } from "idb-keyval";
import { http, HttpResponse } from "msw";
import { afterEach, describe, expect, it } from "vitest";
import { copy } from "../lib/copy";
import { makeCtx } from "../test/parts";
import { renderWithProviders } from "../test/render";
import { BASE, server } from "../test/server";
import { UiPart } from "./registry";

afterEach(async () => {
  await clear();
});

const choice = { question: "무엇부터 할까요?", options: [{ id: "a", label: "운동" }, { id: "b", label: "독서" }] };

describe("UiPart", () => {
  it("unknown name renders UnknownPart with title", async () => {
    renderWithProviders(<UiPart name="ui_week_strip" props={{ title: "이번 주 운동" }} ctx={makeCtx()} />);
    expect(await screen.findByText(copy.parts.unknown)).toBeInTheDocument();
    expect(screen.getByText("이번 주 운동")).toBeInTheDocument();
  });

  it("invalid props render UnknownPart", async () => {
    renderWithProviders(<UiPart name="ui_choice" props={{ question: "하나뿐?", options: [{ id: "a", label: "운동" }] }} ctx={makeCtx()} />);
    expect(await screen.findByText(copy.parts.unknown)).toBeInTheDocument();
    expect(screen.getByText("하나뿐?")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "운동" })).toBeNull();
  });

  it("valid props render the part", async () => {
    renderWithProviders(<UiPart name="ui_choice" props={choice} ctx={makeCtx()} />);
    expect(await screen.findByRole("button", { name: "독서" })).toBeInTheDocument();
    expect(screen.queryByText(copy.parts.unknown)).toBeNull();
  });

  it("settles in every connection state", async () => {
    server.use(http.get(`${BASE}/ui/catalog`, () => HttpResponse.json({ error: { code: "unauthorized", message: "x" } }, { status: 401 })));
    renderWithProviders(<UiPart name="ui_choice" props={choice} ctx={makeCtx()} />, { conn: "unauthorized" });
    expect(await screen.findByText(copy.parts.unknown)).toBeInTheDocument();
  });

  it("same component in three contexts", async () => {
    const trees: string[] = [];
    for (const where of ["chat", "today", "checkin"] as const) {
      const { container, unmount } = renderWithProviders(<UiPart name="ui_choice" props={choice} ctx={makeCtx({ where })} />);
      await waitFor(() => expect(screen.getByRole("button", { name: "독서" })).toBeInTheDocument());
      trees.push(container.innerHTML);
      unmount();
    }
    expect(trees[1]).toBe(trees[0]);
    expect(trees[2]).toBe(trees[0]);
  });
});
