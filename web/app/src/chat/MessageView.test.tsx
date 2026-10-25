import "fake-indexeddb/auto";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { copy } from "../lib/copy";
import { markdownChunk } from "../components/Markdown";
import { renderWithProviders } from "../test/render";
import { MessageView } from "./MessageView";
import type { ViewPart } from "./parts";

const answer = { id: "m-1-1", role: "assistant" as const, parts: [] };
const result = (restored: boolean): ViewPart => ({
  kind: "ui",
  toolCallId: "c1",
  name: "ui_result",
  restored,
  props: { task_ids: [53] },
  data: {
    today: "2026-10-24",
    items: [
      {
        todo: { id: 53, title: "치과 예약", status: "open", planned_for: "2026-10-27", scheduled_at: null },
        change: "moved",
        before: { status: null, planned_for: "2026-10-25", scheduled_at: null, title: null },
        after: { status: "open", planned_for: "2026-10-27", scheduled_at: null, title: null },
        activity_ids: [931],
        undo_id: 931,
      },
    ],
  },
});

describe("MessageView", () => {
  it("a change is one line, with no button (SP9 9.6)", () => {
    const confirmation = "✓ 할 일 3개를 내일로 옮겼어요"; // taste-skill-ignore: BE confirmation prefix (R4b), not UI
    renderWithProviders(<MessageView message={answer} parts={[{ kind: "activity", confirmation, undoIds: [3], activityIds: [3] }]} />);
    const line = document.querySelector("[data-activity]")!;
    expect(line).toHaveTextContent(confirmation);
    expect(line.tagName).toBe("P");
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("before R4b (no confirmation, only undo ids) the change is still one line of text", () => {
    renderWithProviders(<MessageView message={answer} parts={[{ kind: "activity", confirmation: null, undoIds: [3], activityIds: [3] }]} />);
    expect(document.querySelector("[data-activity]")).toHaveTextContent(copy.chat.changed);
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("no confirmation and nothing to undo draws nothing", () => {
    renderWithProviders(<MessageView message={answer} parts={[{ kind: "activity", confirmation: null, undoIds: [], activityIds: [1] }]} />);
    expect(document.querySelector("[data-activity]")).toBeNull();
  });

  it("the secretary's text is Markdown; my own stays plain", async () => {
    await markdownChunk.load();
    const mine = { id: "m-1-0", role: "user" as const, parts: [{ type: "text" as const, text: "**내 말** <b>x</b>" }] };
    const { container } = renderWithProviders(
      <>
        <MessageView message={mine} parts={[]} />
        <MessageView message={answer} parts={[{ kind: "text", text: "**비서 말** [링크](https://example.com)" }]} />
      </>,
    );
    expect(screen.getByText("**내 말** <b>x</b>")).toBeInTheDocument();
    expect(container.querySelector('[data-message="m-1-0"] strong, [data-message="m-1-0"] b')).toBeNull();
    expect(container.querySelector('[data-message="m-1-1"] strong')).toHaveTextContent("비서 말");
    expect(screen.getByRole("link", { name: "링크" })).toHaveAttribute("target", "_blank");
  });

  it("hides the line a ui_result shows, also for an item without undo_id", async () => {
    const r = result(false) as Extract<ViewPart, { kind: "ui" }>;
    const items = (r.data!.items as { undo_id: number | null }[]).map((it) => ({ ...it, undo_id: null }));
    renderWithProviders(<MessageView message={answer} parts={[{ ...r, data: { ...r.data!, items } } as ViewPart, { kind: "activity", confirmation: "옮겼어요", undoIds: [], activityIds: [931] }]} />);
    expect(await screen.findByText("치과 예약")).toBeInTheDocument();
    expect(document.querySelector("[data-activity]")).toBeNull();
  });

  it("hides a confirmation box its ui_result covers", async () => {
    renderWithProviders(<MessageView message={answer} parts={[result(false), { kind: "activity", confirmation: "옮겼어요", undoIds: [931], activityIds: [931] }]} />);
    expect(await screen.findByText("치과 예약")).toBeInTheDocument();
    expect(document.querySelector("[data-activity]")).toBeNull();
  });

  it("restored message keeps", async () => {
    renderWithProviders(<MessageView message={answer} parts={[result(true), { kind: "activity", confirmation: "옮겼어요", undoIds: [931], activityIds: [931] }]} />);
    expect(await screen.findByText("치과 예약")).toBeInTheDocument();
    expect(document.querySelector("[data-activity]")).toHaveTextContent("옮겼어요");
  });

  it("an open button moves through onOpen", async () => {
    const onOpen = vi.fn();
    const part: ViewPart = { kind: "ui", toolCallId: "c2", name: "ui_period_list", props: { day: "2026-10-24" }, data: { today: "2026-10-24", days: [{ date: "2026-10-24", weekday: "토", is_today: true, todos: [] }], outside: [] } };
    renderWithProviders(<MessageView message={answer} parts={[part]} onOpen={onOpen} />);
    await userEvent.click(await screen.findByRole("button", { name: copy.parts.openTodos }));
    expect(onOpen).toHaveBeenCalledWith("todos_day");
  });

  it("a result that fails the catalog keeps the box", async () => {
    const bad = { ...result(false), props: { task_ids: [53, 53] } } as ViewPart; // not unique: the schema refuses it
    renderWithProviders(<MessageView message={answer} parts={[bad, { kind: "activity", confirmation: "옮겼어요", undoIds: [931], activityIds: [931] }]} />);
    expect(await screen.findByText(copy.parts.unknown)).toBeInTheDocument();
    expect(document.querySelector("[data-activity]")).toHaveTextContent("옮겼어요");
  });
});
