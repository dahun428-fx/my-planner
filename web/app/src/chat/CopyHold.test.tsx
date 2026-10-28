import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ToastApi } from "../components/Toast";
import { CopyHold, HOLD_MS } from "./CopyHold";

const shown: string[] = [];
vi.mock("../components/Toast", () => ({
  useToast: (): ToastApi => ({ show: (t) => void shown.push(t.text), showFor: () => {}, onUndone: () => () => {} }),
}));

function setup() {
  return render(
    <CopyHold side="theirs" data-message="m1">
      <div data-copy="">
        <p>첫 줄</p>
      </div>
      <button type="button">카드 버튼</button>
      <p>✓ 바꿨어요</p>
      <div data-copy="">
        <p>둘째 문단</p>
      </div>
    </CopyHold>,
  );
}

let writeText: ReturnType<typeof vi.fn>;
beforeEach(() => {
  vi.useFakeTimers();
  shown.length = 0;
  writeText = vi.fn(async () => {});
  Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
});
afterEach(() => {
  vi.useRealTimers();
});

const hold = (el: Element, ms = HOLD_MS) => {
  fireEvent.pointerDown(el, { button: 0, clientX: 10, clientY: 10 });
  act(() => void vi.advanceTimersByTime(ms));
};

describe("CopyHold", () => {
  it("opens the copy menu after a hold and copies only the message's text", async () => {
    setup();
    hold(screen.getByText("첫 줄"));
    const item = screen.getByRole("menuitem", { name: "복사" });
    await act(async () => fireEvent.click(item));
    expect(writeText).toHaveBeenCalledWith("첫 줄\n\n둘째 문단");
    expect(shown).toEqual(["복사했어요"]);
    expect(screen.queryByRole("menu")).toBeNull();
  });

  it("does nothing for a short tap, a scroll or a hold on a card's button", () => {
    setup();
    hold(screen.getByText("첫 줄"), HOLD_MS - 50);
    fireEvent.pointerUp(screen.getByText("첫 줄"));
    act(() => void vi.advanceTimersByTime(HOLD_MS));
    expect(screen.queryByRole("menu")).toBeNull();

    fireEvent.pointerDown(screen.getByText("첫 줄"), { button: 0, clientX: 10, clientY: 10 });
    fireEvent.pointerMove(screen.getByText("첫 줄"), { clientX: 10, clientY: 40 });
    act(() => void vi.advanceTimersByTime(HOLD_MS));
    expect(screen.queryByRole("menu")).toBeNull();

    hold(screen.getByRole("button", { name: "카드 버튼" }));
    expect(screen.queryByRole("menu")).toBeNull();
  });

  it("opens on a right-click (the browser's own menu gives way) and closes on a tap elsewhere", () => {
    setup();
    const notPrevented = fireEvent.contextMenu(screen.getByText("첫 줄"));
    expect(notPrevented).toBe(false);
    expect(screen.getByRole("menu")).toBeInTheDocument();
    fireEvent.pointerDown(document.body);
    expect(screen.queryByRole("menu")).toBeNull();
  });

  it("says so when the clipboard refuses", async () => {
    writeText.mockRejectedValueOnce(new Error("denied"));
    setup();
    hold(screen.getByText("첫 줄"));
    await act(async () => fireEvent.click(screen.getByRole("menuitem")));
    expect(shown).toEqual(["복사하지 못했어요"]);
  });
});
