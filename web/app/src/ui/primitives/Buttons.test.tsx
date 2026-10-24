import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { Buttons } from "./Buttons";
import type { ButtonItem } from "./types";

const items: ButtonItem[] = [
  { label: "이번 주 할 일 보기", do: { kind: "open", screen: "todos_week" } },
  { label: "다음 주도 알려 줘", do: { kind: "send" } },
  { label: "운동 끝났어", do: { kind: "complete", task_id: 61 } },
];
const btn = (name: string) => screen.getByRole("button", { name });

describe("Buttons", () => {
  it("send disables all and marks pressed", async () => {
    const onPress = vi.fn(() => true);
    render(<Buttons items={items} isDisabled={() => false} onPress={onPress} />);
    expect(btn("다음 주도 알려 줘")).toHaveAttribute("aria-pressed", "false");
    await userEvent.click(btn("다음 주도 알려 줘"));
    expect(onPress).toHaveBeenCalledExactlyOnceWith(items[1]);
    expect(btn("다음 주도 알려 줘")).toBeDisabled();
    expect(btn("다음 주도 알려 줘")).toHaveAttribute("aria-pressed", "true");
    expect(btn("운동 끝났어")).toBeDisabled();
    expect(btn("운동 끝났어")).toHaveAttribute("aria-pressed", "false");
    // Opening a screen is not a write: it stays on.
    expect(btn("이번 주 할 일 보기")).toBeEnabled();
    await userEvent.click(btn("운동 끝났어"));
    expect(onPress).toHaveBeenCalledTimes(1);
  });

  it("open stays enabled after press", async () => {
    const onPress = vi.fn(() => true);
    render(<Buttons items={items} isDisabled={() => false} onPress={onPress} />);
    await userEvent.click(btn("이번 주 할 일 보기"));
    await userEvent.click(btn("이번 주 할 일 보기"));
    expect(onPress).toHaveBeenCalledTimes(2);
    expect(btn("이번 주 할 일 보기")).toBeEnabled();
    expect(btn("이번 주 할 일 보기")).not.toHaveAttribute("aria-pressed");
    expect(btn("다음 주도 알려 줘")).toBeEnabled();
  });

  it("isDisabled respected", async () => {
    const onPress = vi.fn(() => true);
    render(<Buttons items={items} isDisabled={(i) => i.do.kind !== "open"} onPress={onPress} />);
    expect(btn("다음 주도 알려 줘")).toBeDisabled();
    expect(btn("운동 끝났어")).toBeDisabled();
    expect(btn("이번 주 할 일 보기")).toBeEnabled();
    await userEvent.click(btn("운동 끝났어"));
    expect(onPress).not.toHaveBeenCalled();
  });

  it("failed press keeps buttons on", async () => {
    const onPress = vi.fn(async () => false);
    render(<Buttons items={items} isDisabled={() => false} onPress={onPress} />);
    await userEvent.click(btn("운동 끝났어"));
    await waitFor(() => expect(onPress).toHaveBeenCalledTimes(1));
    for (const b of screen.getAllByRole("button")) expect(b).toBeEnabled();
    expect(btn("운동 끝났어")).toHaveAttribute("aria-pressed", "false");
  });

  it("a second press while the first is in flight is ignored", async () => {
    let finish: (ok: boolean) => void = () => {};
    const onPress = vi.fn(() => new Promise<boolean>((r) => (finish = r)));
    render(<Buttons items={items} isDisabled={() => false} onPress={onPress} />);
    await userEvent.click(btn("운동 끝났어"));
    await userEvent.click(btn("다음 주도 알려 줘"));
    expect(onPress).toHaveBeenCalledTimes(1);
    finish(true);
    await waitFor(() => expect(btn("운동 끝났어")).toHaveAttribute("aria-pressed", "true"));
  });
});
