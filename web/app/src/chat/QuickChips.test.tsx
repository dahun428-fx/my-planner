import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { copy } from "../lib/copy";
import { FIXED_CHIPS, type Chip } from "./quickChips";
import { QuickChips } from "./QuickChips";

const checkin: Chip = { key: "checkin", label: copy.chat.chips.checkin.label, text: copy.chat.chips.checkin.text, icon: "check", checkinId: 341 };

describe("QuickChips", () => {
  it("the fixed four in 9.5 order, the front chip first", () => {
    const { rerender } = render(<QuickChips chips={FIXED_CHIPS} disabled={false} onSend={() => {}} />);
    const row = screen.getByRole("group", { name: copy.chat.chipsLabel });
    expect(within(row).getAllByRole("button").map((b) => b.textContent)).toEqual(["할 일 추가", "일정 추가", "메모하기", "오늘 정리해줘"]);
    rerender(<QuickChips chips={[checkin, ...FIXED_CHIPS]} disabled={false} onSend={() => {}} />);
    expect(within(row).getAllByRole("button").map((b) => b.textContent)).toEqual(["체크인 하기", "할 일 추가", "일정 추가", "메모하기", "오늘 정리해줘"]);
  });

  it("a press hands up the chip (its sentence, and the run for the check-in chip)", async () => {
    const onSend = vi.fn();
    const user = userEvent.setup();
    render(<QuickChips chips={[checkin, ...FIXED_CHIPS]} disabled={false} onSend={onSend} />);
    await user.click(screen.getByRole("button", { name: "일정 추가" }));
    expect(onSend).toHaveBeenLastCalledWith(expect.objectContaining({ text: "일정 하나 추가할래요" }));
    await user.click(screen.getByRole("button", { name: "체크인 하기" }));
    expect(onSend).toHaveBeenLastCalledWith(expect.objectContaining({ text: "체크인 할게요", checkinId: 341 }));
  });

  it("read-only: every chip is dimmed and cannot be pressed", async () => {
    const onSend = vi.fn();
    const user = userEvent.setup();
    render(<QuickChips chips={FIXED_CHIPS} disabled onSend={onSend} />);
    const buttons = screen.getAllByRole("button");
    expect(buttons.every((b) => (b as HTMLButtonElement).disabled)).toBe(true);
    await user.click(buttons[0]);
    expect(onSend).not.toHaveBeenCalled();
  });
});
