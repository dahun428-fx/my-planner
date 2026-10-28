import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { copy } from "../lib/copy";
import { DoneFold } from "./DoneFold";

describe("DoneFold", () => {
  it("draws nothing when nothing is done", () => {
    const { container } = render(<DoneFold count={0}><p>row</p></DoneFold>);
    expect(container).toBeEmptyDOMElement();
  });

  it("starts closed and opens on press", async () => {
    render(<DoneFold count={2}><p>row</p></DoneFold>);
    const button = screen.getByRole("button", { name: copy.today.doneFold(2) });
    const panel = document.getElementById(button.getAttribute("aria-controls")!)!;
    expect(button).toHaveAttribute("aria-expanded", "false");
    expect(panel).not.toBeVisible();
    expect(screen.queryByText("row")).toBeNull();
    await userEvent.setup().click(button);
    expect(button).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("row")).toBeVisible();
  });

  it("closes again once nothing is done", async () => {
    const { rerender } = render(<DoneFold count={1}><p>row</p></DoneFold>);
    await userEvent.setup().click(screen.getByRole("button"));
    rerender(<DoneFold count={0}><p>row</p></DoneFold>);
    rerender(<DoneFold count={1}><p>row</p></DoneFold>);
    expect(screen.getByRole("button")).toHaveAttribute("aria-expanded", "false");
  });

  it("takes the focus a moved row dropped", () => {
    const { rerender } = render(<DoneFold count={1}><p>row</p></DoneFold>);
    (document.activeElement as HTMLElement | null)?.blur();
    rerender(<DoneFold count={2}><p>row</p></DoneFold>);
    expect(screen.getByRole("button", { name: copy.today.doneFold(2) })).toHaveFocus();
  });
});
