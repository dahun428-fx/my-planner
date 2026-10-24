import { fireEvent, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { copy } from "../lib/copy";
import { makeTodo } from "../test/parts";
import { renderWithProviders } from "../test/render";
import { EditTodoSheet } from "./EditTodoSheet";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("EditTodoSheet", () => {
  it("keeps the last edit drawn while it slides out", () => {
    vi.stubGlobal("matchMedia", (q: string) => ({ matches: false, media: q, addEventListener() {}, removeEventListener() {} }));
    const props = { onClose: () => {}, onDone: async () => {}, guard: async () => {} };
    const { rerender } = renderWithProviders(<EditTodoSheet edit={{ kind: "title", todo: makeTodo(3, "장보기") }} {...props} />, { conn: "none" });
    expect(screen.getByRole("dialog", { name: copy.todos.editTitle })).toBeInTheDocument();
    rerender(<EditTodoSheet edit={null} {...props} />);
    const leaving = screen.getByRole("dialog", { hidden: true });
    expect(leaving.className).toContain("closing");
    expect(screen.getByDisplayValue("장보기")).toBeInTheDocument();
    fireEvent.animationEnd(leaving);
    expect(screen.queryByRole("dialog", { hidden: true })).toBeNull();
  });
});
