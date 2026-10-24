import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { copy } from "../../lib/copy";
import { makeCtx, serveActions } from "../../test/parts";
import { renderWithProviders } from "../../test/render";
import type { PartData, PartTodo } from "../types";
import { Block, type BlockProps } from "./Block";

// SP6 7.1 as written.
const example: BlockProps = {
  title: "이번 주 운동",
  children: [
    {
      type: "group",
      layout: "row",
      children: [
        { type: "stat", label: "이번 주", value: "3회", delta: { text: "1회", trend: "up" } },
        { type: "stat", label: "지난주", value: "2회" },
      ],
    },
    { type: "progress", label: "이번 주 목표", value: 3, max: 4 },
    { type: "text", md: "**목요일** 오후가 비어 있어요." },
    { type: "todo_rows", task_ids: [61] },
    { type: "buttons", items: [{ label: "운동 끝났어", do: { kind: "complete", task_id: 61 } }] },
  ],
};
const todo = (over: Partial<PartTodo> = {}): PartTodo => ({ id: 61, title: "운동 30분", status: "open", planned_for: "2026-10-24", scheduled_at: null, ...over });
const data = (over: Partial<PartTodo> = {}): PartData => ({ today: "2026-10-24", todos: [todo(over)] });
const withButtons: BlockProps = {
  title: "다음 할 일",
  children: [
    { type: "todo_rows", task_ids: [61] },
    {
      type: "buttons",
      items: [
        { label: "운동 끝났어", do: { kind: "complete", task_id: 61 } },
        { label: "다음 주도 알려 줘", do: { kind: "send" } },
        { label: "이번 주 할 일 보기", do: { kind: "open", screen: "todos_week" } },
      ],
    },
  ],
};
const card = () => within(document.querySelector("section")!);

describe("Block", () => {
  it("draws 7.1 in order", () => {
    renderWithProviders(<Block props={example} data={data()} ctx={makeCtx()} />);
    expect(screen.getByRole("heading", { level: 3, name: "이번 주 운동" })).toBeInTheDocument();
    const stats = screen.getAllByRole("group");
    expect(stats.map((g) => g.getAttribute("aria-label"))).toEqual(["이번 주 3회, 지난번보다 올라감 1회", "지난주 2회"]);
    expect(screen.getByRole("progressbar", { name: "이번 주 목표 3/4" })).toHaveAttribute("value", "3");
    expect(screen.getByText("목요일").tagName).toBe("STRONG");
    expect(screen.getAllByRole("checkbox")).toHaveLength(1);
    expect(card().getAllByRole("button", { name: "운동 끝났어" })).toHaveLength(1);
    // In the order of `children`: the row group, the bar, the text, the rows, the buttons.
    const body = document.querySelector(".block")!;
    expect([...body.children].map((c) => c.className.split(" ")[0] || c.tagName)).toEqual(["row", "progress", "text", "checkRows", "buttons"]);
  });

  it("complete button completes row", async () => {
    const bodies = serveActions();
    const ctx = makeCtx();
    renderWithProviders(<Block props={example} data={data()} ctx={ctx} />);
    await userEvent.click(card().getByRole("button", { name: "운동 끝났어" }));
    await waitFor(() => expect(bodies).toHaveLength(1));
    expect(bodies[0]).toMatchObject({ action: "complete_task", args: { id: 61 } });
    await waitFor(() => expect(ctx.onAfterAction).toHaveBeenCalledTimes(1));
    expect(screen.getByRole("checkbox", { name: copy.parts.checkLabel("운동 30분") })).toBeChecked();
    expect(card().getByRole("button", { name: "운동 끝났어" })).toHaveAttribute("aria-pressed", "true");
  });

  it("complete disabled when row not open", () => {
    renderWithProviders(<Block props={example} data={data({ status: "done" })} ctx={makeCtx()} />);
    expect(card().getByRole("button", { name: "운동 끝났어" })).toBeDisabled();
  });

  it("failing checkBlock renders UnknownPart with title", () => {
    const bad: BlockProps = { ...example, children: [{ type: "divider" }, ...example.children] };
    renderWithProviders(<Block props={bad} data={data()} ctx={makeCtx()} />);
    expect(screen.getByText(copy.parts.unknown)).toBeInTheDocument();
    expect(screen.getByText("이번 주 운동")).toBeInTheDocument();
    expect(screen.queryByRole("checkbox")).toBeNull();
  });

  it("read only", () => {
    renderWithProviders(<Block props={withButtons} data={data()} ctx={makeCtx({ readOnly: true, onChoose: vi.fn(), onOpen: vi.fn() })} />);
    expect(card().getByRole("button", { name: "운동 끝났어" })).toBeDisabled();
    expect(card().getByRole("button", { name: "다음 주도 알려 줘" })).toBeDisabled();
    expect(card().getByRole("button", { name: "이번 주 할 일 보기" })).toBeEnabled();
    expect(screen.getByRole("checkbox")).toBeDisabled();
    expect(screen.getByText(copy.offline.writeLater)).toBeInTheDocument();
  });

  it("restored", async () => {
    const onOpen = vi.fn();
    renderWithProviders(<Block props={withButtons} data={data()} ctx={makeCtx({ restored: true, onChoose: vi.fn(), onOpen })} />);
    expect(card().queryByRole("button", { name: "운동 끝났어" })).toBeNull();
    expect(card().queryByRole("button", { name: "다음 주도 알려 줘" })).toBeNull();
    await userEvent.click(card().getByRole("button", { name: "이번 주 할 일 보기" }));
    expect(onOpen).toHaveBeenCalledWith("todos_week");
    expect(screen.getByRole("checkbox")).toBeDisabled();
  });

  it("send and open buttons", async () => {
    const onChoose = vi.fn();
    const onOpen = vi.fn();
    renderWithProviders(<Block props={withButtons} data={data()} ctx={makeCtx({ onChoose, onOpen })} />);
    await userEvent.click(card().getByRole("button", { name: "이번 주 할 일 보기" }));
    await userEvent.click(card().getByRole("button", { name: "이번 주 할 일 보기" }));
    expect(onOpen).toHaveBeenCalledTimes(2);
    await userEvent.click(card().getByRole("button", { name: "다음 주도 알려 줘" }));
    expect(onChoose).toHaveBeenCalledWith("다음 주도 알려 줘");
    expect(card().getByRole("button", { name: "운동 끝났어" })).toBeDisabled();
  });

  it("no onOpen no open button", () => {
    renderWithProviders(<Block props={withButtons} data={data()} ctx={makeCtx({ onChoose: vi.fn() })} />);
    expect(card().queryByRole("button", { name: "이번 주 할 일 보기" })).toBeNull();
    expect(card().getByRole("button", { name: "다음 주도 알려 줘" })).toBeEnabled();
  });

  it("no data", () => {
    renderWithProviders(<Block props={example} ctx={makeCtx()} />);
    expect(screen.getByText(copy.parts.todoCount(1))).toBeInTheDocument();
    expect(screen.queryByRole("checkbox")).toBeNull();
    expect(screen.getAllByRole("group")).toHaveLength(2);
    expect(screen.getByRole("progressbar")).toBeInTheDocument();
    expect(card().getByRole("button", { name: "운동 끝났어" })).toBeDisabled();
  });
});
