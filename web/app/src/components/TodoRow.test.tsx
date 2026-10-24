import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { Todo } from "../api/types.gen";
import { copy } from "../lib/copy";
import { formatKst } from "../lib/time";
import { TodoRow } from "./TodoRow";

const open: Todo = { id: 12, title: "운동 30분", status: "open", planned_for: "2026-10-24", scheduled_at: null, parent_id: null, areas: [], note: "", priority: null, completed_at: null };
const done: Todo = { ...open, id: 15, title: "빨래 널기", status: "done", completed_at: "2026-10-24T00:40:00Z" };
const noop = () => {};

describe("TodoRow", () => {
  it("done row shows time not count", () => {
    render(<TodoRow todo={done} readOnly={false} onToggle={noop} onTomorrow={noop} onDrop={noop} />);
    expect(screen.getByText(copy.today.completedAt(formatKst(done.completed_at as string, "HH:mm")))).toBeInTheDocument();
    expect(screen.getByText("빨래 널기")).toHaveClass("done");
    expect(screen.getByRole("checkbox")).toBeChecked();
  });

  it("check calls onToggle and shows priority in grey text", () => {
    const onToggle = vi.fn();
    const todo: Todo = { ...open, priority: { cadence: "day", period: "2026-10-24", rank: 1 } };
    render(<TodoRow todo={todo} readOnly={false} onToggle={onToggle} onTomorrow={noop} onDrop={noop} />);
    expect(screen.getByText(copy.today.priority)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("checkbox", { name: copy.today.checkLabel("운동 30분") }));
    expect(onToggle).toHaveBeenCalledTimes(1);
  });

  it("read-only shows an empty circle and no checkbox", () => {
    render(<TodoRow todo={open} readOnly onToggle={noop} onTomorrow={noop} onDrop={noop} />);
    expect(screen.queryByRole("checkbox")).toBeNull();
    expect(screen.getByText("운동 30분")).toBeInTheDocument();
  });

  it("long press menu runs tomorrow and drop", () => {
    const onTomorrow = vi.fn();
    const onDrop = vi.fn();
    render(<TodoRow todo={open} readOnly={false} onToggle={noop} onTomorrow={onTomorrow} onDrop={onDrop} />);
    fireEvent.contextMenu(screen.getByText("운동 30분"));
    fireEvent.click(screen.getByRole("button", { name: copy.todos.tomorrow }));
    expect(onTomorrow).toHaveBeenCalledTimes(1);
  });
});
