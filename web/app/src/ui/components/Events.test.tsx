import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { copy } from "../../lib/copy";
import { ev } from "../../test/events";
import { makeCtx } from "../../test/parts";
import { renderWithProviders } from "../../test/render";
import { registerChatParts } from "../chat/registerChatParts";
import { registryNames, UiPart } from "../registry";
import { Events } from "./Events";

const items = [
  ev(2, "2026-10-27", null, { title: "엄마 생신" }),
  ev(3, "2026-10-27", "09:30", { title: "팀 회의", repeat: "weekly", area: "career" }),
  ev(4, "2026-10-28", "14:00", { title: "치과", area: "health" }),
];

describe("ui_events (SP9 9.8)", () => {
  it("rows under each day: time, title, area dot, repeat mark", () => {
    renderWithProviders(<Events props={{ items }} ctx={makeCtx()} />);
    const day1 = screen.getByRole("list", { name: copy.parts.dayLabel(10, 27, "화") });
    const rows = within(day1).getAllByRole("listitem");
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveTextContent(`${copy.schedule.allDay}엄마 생신`);
    expect(rows[1]).toHaveTextContent("09:30");
    expect(within(rows[1]).getByRole("img", { name: copy.schedule.repeating })).toBeInTheDocument();
    expect(rows[1].querySelector('.area-dot[data-area="career"]')).not.toBeNull();
    expect(within(screen.getByRole("list", { name: copy.parts.dayLabel(10, 28, "수") })).getByText("치과")).toBeInTheDocument();
  });

  it("a tap opens the schedule tab on that day (the sheet closes, SP6 8)", async () => {
    const onOpenPath = vi.fn();
    renderWithProviders(<Events props={{ items }} ctx={makeCtx({ onOpenPath })} />);
    await userEvent.click(screen.getByRole("button", { name: /치과/ }));
    expect(onOpenPath).toHaveBeenCalledWith("/schedule/?date=2026-10-28");
  });

  it("with nowhere to open (a check-in), the rows are plain", () => {
    renderWithProviders(<Events props={{ items }} ctx={makeCtx()} />);
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("joins the registry with the chat bundle, checked against the catalog", async () => {
    expect(registryNames()).not.toContain("ui_events");
    registerChatParts();
    expect(registryNames()).toContain("ui_events");
    renderWithProviders(<UiPart name="ui_events" props={{ items: [items[2]] }} ctx={makeCtx()} />);
    expect(await screen.findByText("치과")).toBeInTheDocument();
    renderWithProviders(<UiPart name="ui_events" props={{ items: [] }} ctx={makeCtx()} />);
    expect(await screen.findByText(copy.parts.unknown)).toBeInTheDocument(); // 1~10 items (catalog)
  });
});
