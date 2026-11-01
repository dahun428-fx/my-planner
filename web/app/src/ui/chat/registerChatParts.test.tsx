import "fake-indexeddb/auto";
import { screen } from "@testing-library/react";
import { clear } from "idb-keyval";
import { afterEach, describe, expect, it } from "vitest";
import { copy } from "../../lib/copy";
import { makeCtx } from "../../test/parts";
import { renderWithProviders } from "../../test/render";
import { UnknownPart } from "../components/UnknownPart";
import { registerParts, registryNames, UiPart } from "../registry";
import { CHAT_PARTS_MARKER, registerChatParts } from "./registerChatParts";

// SP6 11.2, Review Focus 5. The tests run in order: the first one is before the chat bundle loads.
afterEach(async () => {
  await clear();
});

const block = { title: "이번 주 운동", children: [{ type: "stat", label: "이번 주", value: "3회" }] };

describe("registerChatParts", () => {
  it("new names are unknown before chat loads", async () => {
    expect(registryNames()).not.toContain("ui_block");
    renderWithProviders(<UiPart name="ui_block" props={block} data={{ today: "2026-10-24" }} ctx={makeCtx({ where: "today" })} />);
    expect(await screen.findByText(copy.parts.unknown)).toBeInTheDocument();
    expect(screen.getByText("이번 주 운동")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { level: 3 })).toBeNull();
  });

  it("drawn after register", async () => {
    registerChatParts();
    expect(registryNames()).toEqual(expect.arrayContaining(["ui_date_choice", "ui_result", "ui_period_list", "ui_block", "ui_measure_confirm"]));
    renderWithProviders(<UiPart name="ui_block" props={block} data={{ today: "2026-10-24" }} ctx={makeCtx()} />);
    expect(await screen.findByRole("heading", { level: 3, name: "이번 주 운동" })).toBeInTheDocument();
    expect(screen.getByRole("group", { name: "이번 주 3회" })).toBeInTheDocument();
    expect(screen.queryByText(copy.parts.unknown)).toBeNull();
  });

  it("double register throws in dev", () => {
    expect(() => registerChatParts()).not.toThrow(); // once only: a second call does nothing
    expect(() => registerParts({ ui_block: UnknownPart }, CHAT_PARTS_MARKER)).toThrow(/sp6-chat-parts: ui_block/);
    expect(() => registerParts({ ui_todo_list: UnknownPart })).toThrow(/ui_todo_list/);
  });

  it("a block that fails checkBlock is still unknown", async () => {
    const bad = { title: "구분선만", children: [{ type: "divider" }, { type: "text", md: "글" }] };
    renderWithProviders(<UiPart name="ui_block" props={bad} ctx={makeCtx()} />);
    expect(await screen.findByText(copy.parts.unknown)).toBeInTheDocument();
    expect(screen.getByText("구분선만")).toBeInTheDocument();
  });
});
