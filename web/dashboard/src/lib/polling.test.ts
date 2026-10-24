import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ApiResult } from "./api";
import { usePolling } from "./polling";

let visibility: DocumentVisibilityState = "visible";

function setVisible(v: DocumentVisibilityState) {
  visibility = v;
  document.dispatchEvent(new Event("visibilitychange"));
}

const ok: ApiResult<number> = { kind: "ok", data: 1 };

describe("usePolling", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    visibility = "visible";
    vi.spyOn(document, "visibilityState", "get").mockImplementation(() => visibility);
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("loads on open and every 60 seconds while visible", async () => {
    const load = vi.fn(async () => ok);
    const { result } = renderHook(() => usePolling(load));
    await act(async () => {});
    expect(load).toHaveBeenCalledTimes(1);
    expect(result.current.result).toEqual(ok);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(59_999);
    });
    expect(load).toHaveBeenCalledTimes(1);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
    });
    expect(load).toHaveBeenCalledTimes(2);
  });

  it("skips hidden tabs and loads once when the tab comes back", async () => {
    const load = vi.fn(async () => ok);
    renderHook(() => usePolling(load));
    await act(async () => {});
    act(() => setVisible("hidden"));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(180_000);
    });
    expect(load).toHaveBeenCalledTimes(1);
    await act(async () => setVisible("visible"));
    expect(load).toHaveBeenCalledTimes(2);
  });

  it("does not load in a tab opened hidden until it is shown", async () => {
    visibility = "hidden";
    const load = vi.fn(async () => ok);
    renderHook(() => usePolling(load));
    await act(async () => {});
    expect(load).not.toHaveBeenCalled();
    await act(async () => setVisible("visible"));
    expect(load).toHaveBeenCalledTimes(1);
  });

  it("stops after unauthorized until the key changes", async () => {
    const load = vi.fn(async (): Promise<ApiResult<number>> => ({ kind: "unauthorized" }));
    const { result, rerender } = renderHook(({ k }) => usePolling(load, 60_000, k), { initialProps: { k: "a" } });
    await act(async () => {});
    expect(result.current.result).toEqual({ kind: "unauthorized" });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(300_000);
    });
    await act(async () => setVisible("visible"));
    expect(load).toHaveBeenCalledTimes(1);
    load.mockImplementation(async () => ok);
    rerender({ k: "b" });
    await act(async () => {});
    expect(load).toHaveBeenCalledTimes(2);
    expect(result.current.result).toEqual(ok);
  });

  it("refresh loads now, even after unauthorized", async () => {
    const load = vi.fn(async (): Promise<ApiResult<number>> => ({ kind: "unauthorized" }));
    const { result } = renderHook(() => usePolling(load));
    await act(async () => {});
    load.mockImplementation(async () => ok);
    await act(async () => {
      await result.current.refresh();
    });
    expect(load).toHaveBeenCalledTimes(2);
    expect(result.current.result).toEqual(ok);
  });
});
