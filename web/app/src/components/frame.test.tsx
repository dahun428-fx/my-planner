import { act, fireEvent, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useRef, useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { copy } from "../lib/copy";
import { renderWithProviders } from "../test/render";
import { BlockError } from "./BlockError";
import { Row } from "./Row";
import { Segmented } from "./Segmented";
import { Sheet } from "./Sheet";

function SheetHarness() {
  const [open, setOpen] = useState(false);
  const opener = useRef<HTMLButtonElement>(null);
  return (
    <>
      <button ref={opener} type="button" onClick={() => setOpen(true)}>
        open
      </button>
      <Sheet open={open} onClose={() => setOpen(false)} title="sheet" returnFocusTo={opener}>
        <button type="button">inside</button>
      </Sheet>
    </>
  );
}

describe("common frame", () => {
  it("sheet moves focus inside and back", async () => {
    const user = userEvent.setup();
    renderWithProviders(<SheetHarness />);
    await user.click(screen.getByRole("button", { name: "open" }));
    expect(screen.getByRole("dialog", { name: "sheet" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "inside" })).toHaveFocus();
    act(() => {
      fireEvent.keyDown(document, { key: "Escape" });
    });
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.getByRole("button", { name: "open" })).toHaveFocus();
  });

  it("row is a link with href and a button with onPress", () => {
    const onPress = vi.fn();
    renderWithProviders(
      <>
        <Row title="to settings" href="/settings/" />
        <Row title="act" onPress={onPress} />
      </>,
    );
    expect(screen.getByRole("link", { name: "to settings" })).toHaveAttribute("href", "/settings/");
    fireEvent.click(screen.getByRole("button", { name: "act" }));
    expect(onPress).toHaveBeenCalledOnce();
  });

  it("segmented is a radio group", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    renderWithProviders(
      <Segmented
        ariaLabel="period"
        value="week"
        onChange={onChange}
        options={[
          { value: "today", label: "a" },
          { value: "week", label: "b" },
        ]}
      />,
    );
    expect(screen.getByRole("radiogroup", { name: "period" })).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "b" })).toHaveAttribute("aria-checked", "true");
    await user.click(screen.getByRole("radio", { name: "a" }));
    expect(onChange).toHaveBeenCalledWith("today");
  });

  it("block error shows code and retries", () => {
    const onRetry = vi.fn();
    renderWithProviders(<BlockError code="shape" onRetry={onRetry} />);
    expect(screen.getByText(copy.errors.block("shape"))).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: copy.errors.retry }));
    expect(onRetry).toHaveBeenCalledOnce();
  });
});
