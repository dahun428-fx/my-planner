import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { afterEach, describe, expect, it, vi } from "vitest";
import { copy } from "../lib/copy";
import { saveConn } from "../lib/connection";
import { TEST_BE_URL, TEST_TOKEN } from "../test/render";
import { BASE, server } from "../test/server";
import { ConnectionContext } from "../lib/ConnectionProvider";
import { ToastProvider, useToast } from "./Toast";

afterEach(() => vi.useRealTimers());

function Harness({ undoId = 913, onUndone }: { undoId?: number | null; onUndone?: () => void }) {
  const toast = useToast();
  return (
    <>
      <button type="button" onClick={() => toast.show({ text: "✓ 완료: 운동", undoId })}>
        first
      </button>
      <button type="button" onClick={() => toast.show({ text: "→ 내일로: 책 읽기" })}>
        second
      </button>
      <button type="button" onClick={() => onUndone && toast.onUndone(onUndone)}>
        sub
      </button>
    </>
  );
}

const mount = (ui = <Harness />) => {
  saveConn({ beUrl: TEST_BE_URL, token: TEST_TOKEN });
  return render(<ToastProvider>{ui}</ToastProvider>);
};
const press = (name: string) => act(async () => screen.getByText(name).click());

describe("Toast", () => {
  it("shows confirmation for 4s", async () => {
    vi.useFakeTimers();
    mount();
    await press("first");
    expect(screen.getByRole("status")).toHaveTextContent("✓ 완료: 운동");
    act(() => void vi.advanceTimersByTime(3900));
    expect(screen.getByRole("status")).toHaveTextContent("✓ 완료: 운동");
    act(() => void vi.advanceTimersByTime(200));
    expect(screen.getByRole("status")).not.toHaveTextContent("✓ 완료: 운동");
  });

  it("undo calls endpoint and shows undo confirmation", async () => {
    let body: unknown;
    server.use(
      http.post(`${BASE}/activity/913/undo`, async ({ request }) => {
        body = await request.json();
        return HttpResponse.json({ status: "undone", activity_id: 920, undone: 913, confirmation: "↩ 되돌림: 운동 완료" });
      }),
    );
    const onUndone = vi.fn();
    mount(<Harness onUndone={onUndone} />);
    await userEvent.click(screen.getByText("sub"));
    await userEvent.click(screen.getByText("first"));
    await userEvent.click(screen.getByRole("button", { name: "되돌리기" }));
    expect(await screen.findByText("↩ 되돌림: 운동 완료")).toBeInTheDocument();
    expect(body).toMatchObject({ client_msg_id: expect.any(String) });
    expect(screen.queryByRole("button", { name: "되돌리기" })).toBeNull();
    expect(onUndone).toHaveBeenCalledTimes(1);
  });

  it("blocked undo shows reason", async () => {
    server.use(http.post(`${BASE}/activity/913/undo`, () => HttpResponse.json({ error: { code: "superseded", message: "x" } }, { status: 409 })));
    mount();
    await userEvent.click(screen.getByText("first"));
    await userEvent.click(screen.getByRole("button", { name: "되돌리기" }));
    expect(await screen.findByText("뒤에 또 바뀌어서 못 되돌려요")).toBeInTheDocument();
  });

  it("failed undo uses the 5.4 text for a refused key", async () => {
    server.use(http.post(`${BASE}/activity/913/undo`, () => HttpResponse.json({ error: { code: "unauthorized", message: "x" } }, { status: 401 })));
    mount();
    await userEvent.click(screen.getByText("first"));
    await userEvent.click(screen.getByRole("button", { name: "되돌리기" }));
    expect(await screen.findByText(copy.status.unauthorized)).toBeInTheDocument();
  });

  it("undo in flight does not disable a newer toast's undo and cannot double send", async () => {
    let release!: () => void;
    const gate = new Promise<void>((r) => (release = r));
    let calls = 0;
    server.use(
      http.post(`${BASE}/activity/913/undo`, async () => {
        calls += 1;
        await gate;
        return HttpResponse.json({ status: "undone", activity_id: 920, undone: 913, confirmation: "c" });
      }),
    );
    function Two() {
      const toast = useToast();
      return (
        <>
          <button type="button" onClick={() => toast.show({ text: "A", undoId: 913 })}>
            a
          </button>
          <button type="button" onClick={() => toast.show({ text: "B", undoId: 914 })}>
            b
          </button>
        </>
      );
    }
    mount(<Two />);
    await userEvent.click(screen.getByText("a"));
    const btn = screen.getByRole("button", { name: "되돌리기" });
    await userEvent.click(btn);
    await userEvent.click(btn);
    expect(btn).toBeDisabled();
    await userEvent.click(screen.getByText("b"));
    expect(screen.getByRole("button", { name: "되돌리기" })).toBeEnabled();
    await act(async () => release());
    expect(calls).toBe(1);
  });

  it("new toast replaces old", async () => {
    mount();
    await userEvent.click(screen.getByText("first"));
    await userEvent.click(screen.getByText("second"));
    const status = screen.getByRole("status");
    expect(status).toHaveTextContent("→ 내일로: 책 읽기");
    expect(status).not.toHaveTextContent("✓ 완료: 운동");
    expect(screen.queryByRole("button", { name: "되돌리기" })).toBeNull();
  });

  it("reconnected toast for 2s", async () => {
    vi.useFakeTimers();
    let fire = () => {};
    const value = {
      state: null,
      conn: null,
      ready: true,
      recheck: async () => {},
      onReconnect: (cb: () => void) => {
        fire = cb;
        return () => {};
      },
    };
    render(
      <ConnectionContext.Provider value={value}>
        <ToastProvider>
          <span />
        </ToastProvider>
      </ConnectionContext.Provider>,
    );
    act(() => fire());
    expect(screen.getByRole("status")).toHaveTextContent("다시 연결됐어요");
    act(() => void vi.advanceTimersByTime(1900));
    expect(screen.getByRole("status")).toHaveTextContent("다시 연결됐어요");
    act(() => void vi.advanceTimersByTime(200));
    expect(screen.getByRole("status")).not.toHaveTextContent("다시 연결됐어요");
  });
});
