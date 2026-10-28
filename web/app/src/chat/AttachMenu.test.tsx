import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { copy } from "../lib/copy";
import { AttachMenu } from "./AttachMenu";

describe("AttachMenu", () => {
  it("closes when it goes off (offline, the sheet loading) while open", async () => {
    const items = [{ key: "a", label: "카메라", icon: "camera" as const, onSelect: vi.fn() }];
    const { rerender } = render(<AttachMenu items={items} />);
    await userEvent.click(screen.getByRole("button", { name: copy.chat.attach }));
    expect(screen.getByRole("menu")).toBeInTheDocument();
    rerender(<AttachMenu items={items} disabled />);
    expect(screen.queryByRole("menu")).toBeNull();
    expect(screen.getByRole("button", { name: copy.chat.attach })).toBeDisabled();
  });

  it("an item that is off does nothing and keeps the menu open", async () => {
    const onSelect = vi.fn();
    render(<AttachMenu items={[{ key: "a", label: "카메라", icon: "camera", disabled: true, onSelect }]} />);
    await userEvent.click(screen.getByRole("button", { name: copy.chat.attach }));
    await userEvent.click(screen.getByRole("menuitem", { name: "카메라" }));
    expect(onSelect).not.toHaveBeenCalled();
    expect(screen.getByRole("menu")).toBeInTheDocument();
  });
});
