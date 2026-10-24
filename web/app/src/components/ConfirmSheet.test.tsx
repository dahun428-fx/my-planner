import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ConfirmSheet } from "./ConfirmSheet";

describe("ConfirmSheet", () => {
  it("keep and change buttons", async () => {
    const onKeep = vi.fn();
    const onChange = vi.fn();
    render(<ConfirmSheet summary="이번 분기 우선순위 3개를 바꿔요" onKeep={onKeep} onChange={onChange} busy={false} />);
    expect(screen.getByText("이번 분기 우선순위 3개를 바꿔요")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "바꾸기" }));
    expect(onChange).toHaveBeenCalledTimes(1);
    await userEvent.click(screen.getByRole("button", { name: "그대로 두기" }));
    expect(onKeep).toHaveBeenCalledTimes(1);
  });

  it("busy disables both", async () => {
    const onKeep = vi.fn();
    const onChange = vi.fn();
    render(<ConfirmSheet summary="s" onKeep={onKeep} onChange={onChange} busy />);
    expect(screen.getByRole("button", { name: "바꾸기" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "그대로 두기" })).toBeDisabled();
    await userEvent.keyboard("{Escape}");
    expect(onKeep).not.toHaveBeenCalled();
  });
});
