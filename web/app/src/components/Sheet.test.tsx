import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { Sheet } from "./Sheet";

// Review: a sheet opened on top of another (ConfirmSheet in the chat or the date sheet) owns the keys.
function Nested({ onOuter, onInner, innerAtStart = false }: { onOuter(): void; onInner(): void; innerAtStart?: boolean }) {
  const [inner, setInner] = useState(innerAtStart);
  return (
    <Sheet open onClose={onOuter} ariaLabel="outer">
      <button type="button">outer a</button>
      <button type="button" onClick={() => setInner(true)}>
        open inner
      </button>
      {inner && (
        <Sheet open onClose={() => (onInner(), setInner(false))} ariaLabel="inner">
          <button type="button">inner a</button>
          <button type="button">inner b</button>
        </Sheet>
      )}
    </Sheet>
  );
}

describe("Sheet", () => {
  it("holds the page still while any sheet is open", () => {
    const { rerender, unmount } = render(<Nested onOuter={() => {}} onInner={() => {}} />);
    const html = document.documentElement;
    expect(html.dataset.sheetOpen).toBe("");
    fireEvent.click(screen.getByRole("button", { name: "open inner" }));
    fireEvent.keyDown(document, { key: "Escape" }); // the inner one goes, the outer one stays
    expect(html.dataset.sheetOpen).toBe("");
    rerender(<div />);
    expect(html.dataset.sheetOpen).toBeUndefined();
    unmount();
  });

  it("escape in nested sheets closes only the inner one", () => {
    const onOuter = vi.fn();
    const onInner = vi.fn();
    render(<Nested onOuter={onOuter} onInner={onInner} />);
    fireEvent.click(screen.getByRole("button", { name: "open inner" }));
    expect(screen.getByRole("dialog", { name: "inner" })).toBeInTheDocument();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(onInner).toHaveBeenCalledTimes(1);
    expect(onOuter).not.toHaveBeenCalled();
    expect(screen.queryByRole("dialog", { name: "inner" })).toBeNull();
    // With the inner one gone, the outer sheet has the keys again.
    fireEvent.keyDown(document, { key: "Escape" });
    expect(onOuter).toHaveBeenCalledTimes(1);
  });

  it("an inner sheet open from the start is still the top one", () => {
    const onOuter = vi.fn();
    const onInner = vi.fn();
    render(<Nested onOuter={onOuter} onInner={onInner} innerAtStart />);
    expect(screen.getByRole("button", { name: "inner a" })).toHaveFocus();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(onInner).toHaveBeenCalledTimes(1);
    expect(onOuter).not.toHaveBeenCalled();
  });

  it("tab stays trapped in the inner sheet", () => {
    render(<Nested onOuter={vi.fn()} onInner={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "open inner" }));
    const a = screen.getByRole("button", { name: "inner a" });
    const b = screen.getByRole("button", { name: "inner b" });
    expect(a).toHaveFocus();
    b.focus();
    fireEvent.keyDown(document, { key: "Tab" });
    expect(a).toHaveFocus();
    fireEvent.keyDown(document, { key: "Tab", shiftKey: true });
    expect(b).toHaveFocus();
  });
});
