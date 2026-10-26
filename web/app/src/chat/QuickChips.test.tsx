import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { copy } from "../lib/copy";
import { FIXED_CHIPS, type Chip } from "./quickChips";
import { QuickChips } from "./QuickChips";

const checkin: Chip = { key: "checkin", label: copy.chat.chips.checkin.label, text: copy.chat.chips.checkin.text, icon: "check", mode: "send", checkinId: 341 };

describe("QuickChips", () => {
  it("the fixed four in 9.5 order, the front chip first", () => {
    const { rerender } = render(<QuickChips chips={FIXED_CHIPS} disabled={false} onPress={() => {}} />);
    const row = screen.getByRole("group", { name: copy.chat.chipsLabel });
    expect(within(row).getAllByRole("button").map((b) => b.textContent)).toEqual(["할 일 추가", "일정 추가", "메모하기", "오늘 정리해줘"]);
    rerender(<QuickChips chips={[checkin, ...FIXED_CHIPS]} disabled={false} onPress={() => {}} />);
    expect(within(row).getAllByRole("button").map((b) => b.textContent)).toEqual(["체크인 하기", "할 일 추가", "일정 추가", "메모하기", "오늘 정리해줘"]);
  });

  it("a press hands up the chip (its sentence, and the run for the check-in chip)", async () => {
    const onPress = vi.fn();
    const user = userEvent.setup();
    render(<QuickChips chips={[checkin, ...FIXED_CHIPS]} disabled={false} onPress={onPress} />);
    await user.click(screen.getByRole("button", { name: "일정 추가" }));
    expect(onPress).toHaveBeenLastCalledWith(expect.objectContaining({ text: "일정 하나 추가할래요" }));
    await user.click(screen.getByRole("button", { name: "체크인 하기" }));
    expect(onPress).toHaveBeenLastCalledWith(expect.objectContaining({ text: "체크인 할게요", checkinId: 341 }));
  });

  // SP9c 3: while a one-line write is open, its indicator sits where the row was (icon, label, close button).
  it("a one-line write shows its indicator instead of the row; the close button hands up the close", async () => {
    const onClose = vi.fn();
    const user = userEvent.setup();
    const event = FIXED_CHIPS[1];
    render(<QuickChips chips={FIXED_CHIPS} disabled={false} writing={event} onPress={() => {}} onCloseWrite={onClose} />);
    expect(screen.queryByRole("group", { name: copy.chat.chipsLabel })).toBeNull();
    expect(screen.getByText("일정 추가")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "한 줄 쓰기 닫기" }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("the memo write is labelled 메모, as its bubble label", () => {
    render(<QuickChips chips={FIXED_CHIPS} disabled={false} writing={FIXED_CHIPS[2]} onPress={() => {}} onCloseWrite={() => {}} />);
    expect(screen.getByText("메모")).toBeInTheDocument();
    expect(screen.queryByText("메모하기")).toBeNull();
  });

  it("read-only: every chip is dimmed and cannot be pressed", async () => {
    const onPress = vi.fn();
    const user = userEvent.setup();
    render(<QuickChips chips={FIXED_CHIPS} disabled onPress={onPress} />);
    const buttons = screen.getAllByRole("button");
    expect(buttons.every((b) => (b as HTMLButtonElement).disabled)).toBe(true);
    await user.click(buttons[0]);
    expect(onPress).not.toHaveBeenCalled();
  });
});
