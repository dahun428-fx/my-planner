import { act, renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ApiResult } from "../api/client";
import { ConnectionContext, type ConnectionValue } from "./ConnectionProvider";
import { usePolling } from "./polling";

let visibility: "visible" | "hidden" = "visible";
const reconnectListeners = new Set<() => void>();
let value: ConnectionValue = {
  state: null,
  conn: null,
  ready: true,
  recheck: async () => {},
  onReconnect: (cb) => {
    reconnectListeners.add(cb);
    return () => reconnectListeners.delete(cb);
  },
};
const wrapper = ({ children }: { children: ReactNode }) => (
  <ConnectionContext.Provider value={value}>{children}</ConnectionContext.Provider>
);

function setVisibility(v: "visible" | "hidden") {
  visibility = v;
  document.dispatchEvent(new Event("visibilitychange"));
}

const okResult = (n: number): ApiResult<number> => ({ kind: "ok", data: n });

beforeEach(() => {
  vi.useFakeTimers();
  visibility = "visible";
  reconnectListeners.clear();
  Object.defineProperty(document, "visibilityState", { configurable: true, get: () => visibility });
});
afterEach(() => vi.useRealTimers());

function setup(load: () => Promise<ApiResult<number>>, interval?: number) {
  return renderHook(() => usePolling(load, interval), { wrapper });
}

describe("usePolling", () => {
  it("polls only when visible", async () => {
    const load = vi.fn(async () => okResult(1));
    const { result } = setup(load);
    await act(async () => {});
    expect(load).toHaveBeenCalledTimes(1);
    expect(result.current.result).toEqual(okResult(1));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(60_000);
    });
    expect(load).toHaveBeenCalledTimes(2);
    visibility = "hidden";
    await act(async () => {
      await vi.advanceTimersByTimeAsync(180_000);
    });
    expect(load).toHaveBeenCalledTimes(2);
  });

  it("refreshes on visibility", async () => {
    const load = vi.fn(async () => okResult(1));
    setup(load);
    await act(async () => {});
    act(() => setVisibility("hidden"));
    expect(load).toHaveBeenCalledTimes(1);
    await act(async () => setVisibility("visible"));
    expect(load).toHaveBeenCalledTimes(2);
  });

  it("stops on unauthorized", async () => {
    const load = vi.fn(async (): Promise<ApiResult<number>> => ({ kind: "unauthorized" }));
    const { result } = setup(load);
    await act(async () => {});
    expect(result.current.result).toEqual({ kind: "unauthorized" });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(300_000);
      setVisibility("hidden");
      setVisibility("visible");
      reconnectListeners.forEach((l) => l());
    });
    expect(load).toHaveBeenCalledTimes(1);
  });

  it("refreshes on reconnect", async () => {
    const load = vi.fn(async () => okResult(1));
    setup(load);
    await act(async () => {});
    await act(async () => reconnectListeners.forEach((l) => l()));
    expect(load).toHaveBeenCalledTimes(2);
  });

  it("refresh() loads now, and a slow old answer does not overwrite a newer one", async () => {
    let resolveFirst: (r: ApiResult<number>) => void = () => {};
    const load = vi
      .fn<() => Promise<ApiResult<number>>>()
      .mockImplementationOnce(() => new Promise((res) => (resolveFirst = res)))
      .mockImplementation(async () => okResult(2));
    const { result } = setup(load);
    await act(async () => {
      await result.current.refresh();
    });
    expect(result.current.result).toEqual(okResult(2));
    await act(async () => resolveFirst(okResult(1)));
    expect(result.current.result).toEqual(okResult(2));
  });

  it("does not start when hidden, and loads once it shows", async () => {
    visibility = "hidden";
    const load = vi.fn(async () => okResult(1));
    setup(load);
    await act(async () => {});
    expect(load).not.toHaveBeenCalled();
    await act(async () => setVisibility("visible"));
    expect(load).toHaveBeenCalledTimes(1);
  });

  it("resumes after a 401 when the connection changes", async () => {
    const load = vi
      .fn<() => Promise<ApiResult<number>>>()
      .mockResolvedValueOnce({ kind: "unauthorized" })
      .mockResolvedValue(okResult(7));
    const conn = (token: string) => ({ beUrl: "https://gp76.example.ts.net", token });
    value = { ...value, conn: conn("old") };
    const { result, rerender } = setup(load);
    await act(async () => {});
    await act(async () => {
      await vi.advanceTimersByTimeAsync(120_000);
    });
    expect(load).toHaveBeenCalledTimes(1);
    value = { ...value, conn: conn("new") };
    rerender();
    await act(async () => {});
    expect(load).toHaveBeenCalledTimes(2);
    expect(result.current.result).toEqual(okResult(7));
  });
});
