import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { SwipeRow } from "./SwipeRow";

const actions = (a: () => void, b: () => void) => [
  { label: "내일로", tone: "neutral" as const, onPress: a },
  { label: "빼기", tone: "negative" as const, onPress: b },
];

function swipe(el: HTMLElement, dx: number) {
  fireEvent.pointerDown(el, { pointerId: 1, clientX: 300, clientY: 10, pointerType: "touch" });
  fireEvent.pointerMove(el, { pointerId: 1, clientX: 300 + dx, clientY: 12, pointerType: "touch" });
  fireEvent.pointerUp(el, { pointerId: 1, clientX: 300 + dx, clientY: 12, pointerType: "touch" });
}

afterEach(() => vi.useRealTimers());

describe("SwipeRow", () => {
  it("swipe reveals tomorrow and drop", async () => {
    const tomorrow = vi.fn();
    const drop = vi.fn();
    render(
      <SwipeRow actions={actions(tomorrow, drop)} disabled={false}>
        <span>운동</span>
      </SwipeRow>,
    );
    expect(screen.queryByRole("button", { name: "빼기" })).toBeNull();
    const surface = screen.getByText("운동").parentElement as HTMLElement;
    swipe(surface, -120);
    expect(surface.style.transform).toMatch(/translateX\(-/);
    fireEvent.click(screen.getByRole("button", { name: "내일로" }));
    expect(tomorrow).toHaveBeenCalledTimes(1);
    // The buttons stay while the row slides back, then go.
    expect(surface.style.transform).toBe("translateX(0)");
    await waitFor(() => expect(screen.queryByRole("button", { name: "빼기" })).toBeNull());
  });

  it("small or vertical drags do not reveal", async () => {
    render(
      <SwipeRow actions={actions(vi.fn(), vi.fn())} disabled={false}>
        <span>운동</span>
      </SwipeRow>,
    );
    const surface = screen.getByText("운동").parentElement as HTMLElement;
    swipe(surface, -10);
    expect(surface.style.transform).toBe("translateX(0)");
    await waitFor(() => expect(screen.queryByRole("button", { name: "빼기" })).toBeNull());
  });

  it("long press offers same actions", () => {
    vi.useFakeTimers();
    const drop = vi.fn();
    render(
      <SwipeRow actions={actions(vi.fn(), drop)} disabled={false} menuTitle="운동">
        <span>운동</span>
      </SwipeRow>,
    );
    const surface = screen.getByText("운동").parentElement as HTMLElement;
    fireEvent.pointerDown(surface, { pointerId: 1, clientX: 300, clientY: 10, pointerType: "touch" });
    act(() => {
      vi.advanceTimersByTime(600);
    });
    const dialog = screen.getByRole("dialog");
    expect(dialog).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "빼기" }));
    expect(drop).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("resting position matches the root font size", () => {
    document.documentElement.style.fontSize = "20px";
    try {
      render(
        <SwipeRow actions={actions(vi.fn(), vi.fn())} disabled={false}>
          <span>운동</span>
        </SwipeRow>,
      );
      const surface = screen.getByText("운동").parentElement as HTMLElement;
      swipe(surface, -400);
      // 2 buttons x 5rem x 20px: the drag is capped at the same distance the row rests at.
      expect(surface.style.transform).toBe("translateX(-200px)");
    } finally {
      document.documentElement.style.fontSize = "";
    }
  });

  it("keyboard button opens the same menu", () => {
    const tomorrow = vi.fn();
    render(
      <SwipeRow actions={actions(tomorrow, vi.fn())} disabled={false} moreLabel="운동 더 보기">
        <span>운동</span>
      </SwipeRow>,
    );
    fireEvent.click(screen.getByRole("button", { name: "운동 더 보기" }));
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "내일로" }));
    expect(tomorrow).toHaveBeenCalledTimes(1);
  });

  it("moving cancels a long press", () => {
    vi.useFakeTimers();
    render(
      <SwipeRow actions={actions(vi.fn(), vi.fn())} disabled={false}>
        <span>운동</span>
      </SwipeRow>,
    );
    const surface = screen.getByText("운동").parentElement as HTMLElement;
    fireEvent.pointerDown(surface, { pointerId: 1, clientX: 300, clientY: 10, pointerType: "touch" });
    fireEvent.pointerMove(surface, { pointerId: 1, clientX: 280, clientY: 10, pointerType: "touch" });
    act(() => {
      vi.advanceTimersByTime(600);
    });
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("disabled when offline", async () => {
    const drop = vi.fn();
    render(
      <SwipeRow actions={actions(vi.fn(), drop)} disabled>
        <span>운동</span>
      </SwipeRow>,
    );
    const surface = screen.getByText("운동").parentElement as HTMLElement;
    swipe(surface, -120);
    fireEvent.contextMenu(surface);
    expect(screen.queryByRole("button", { name: "빼기" })).toBeNull();
    expect(screen.queryByRole("dialog")).toBeNull();
    await userEvent.setup().click(surface);
    expect(drop).not.toHaveBeenCalled();
  });
});
