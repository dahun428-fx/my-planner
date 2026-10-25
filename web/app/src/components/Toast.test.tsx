import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { afterEach, describe, expect, it, vi } from "vitest";
import { copy } from "../lib/copy";
import { saveConn } from "../lib/connection";
import { TEST_BE_URL, TEST_TOKEN } from "../test/render";
import { BASE, server } from "../test/server";
import { ConnectionContext } from "../lib/ConnectionProvider";
import { chatActivityToast } from "../chat/activityToast";
import type { ViewPart } from "../chat/parts";
import { CHAT_ACTIVITY_MS, ToastProvider, useToast } from "./Toast";

afterEach(() => vi.useRealTimers());

function Harness({ undoId = 913, onUndone }: { undoId?: number | null; onUndone?: () => void }) {
  const toast = useToast();
  return (
    <>
      <button type="button" onClick={() => toast.show({ text: "✓ 완료: 운동", undoId })}> {/* taste-skill-ignore: BE confirmation prefix (R4b), not UI */}
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
    expect(screen.getByRole("status")).toHaveTextContent("✓ 완료: 운동"); // taste-skill-ignore: BE confirmation prefix (R4b), not UI
    act(() => void vi.advanceTimersByTime(3900));
    expect(screen.getByRole("status")).toHaveTextContent("✓ 완료: 운동"); // taste-skill-ignore: BE confirmation prefix (R4b), not UI
    act(() => void vi.advanceTimersByTime(200));
    expect(screen.getByRole("status")).not.toHaveTextContent("✓ 완료: 운동"); // taste-skill-ignore: BE confirmation prefix (R4b), not UI
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
    expect(status).not.toHaveTextContent("✓ 완료: 운동"); // taste-skill-ignore: BE confirmation prefix (R4b), not UI
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

  describe("chat activity (SP9 9.6)", () => {
    const change = (id: number, confirmation: string): ViewPart => ({ kind: "activity", confirmation, undoIds: [id], activityIds: [id] });
    function Chat({ parts }: { parts: ViewPart[] }) {
      const toast = useToast();
      return (
        <>
          <button type="button" onClick={() => toast.showFor(chatActivityToast(parts)!, CHAT_ACTIVITY_MS)}>
            chat
          </button>
          <button type="button" onClick={() => toast.show({ text: "→ 내일로: 책 읽기", undoId: 7 })}>
            screen
          </button>
        </>
      );
    }

    it("a chat activity toast stays 6 s with its undo; another toast keeps 4 s", async () => {
      expect(CHAT_ACTIVITY_MS).toBe(6000);
      vi.useFakeTimers();
      mount(<Chat parts={[change(913, "✓ 할 일 3개를 내일로 옮겼어요")]} />); // taste-skill-ignore: BE confirmation prefix (R4b), not UI
      await press("chat");
      expect(screen.getByRole("status")).toHaveTextContent("✓ 할 일 3개를 내일로 옮겼어요"); // taste-skill-ignore: BE confirmation prefix (R4b), not UI
      act_(5900);
      expect(screen.getByRole("button", { name: copy.chat.undo })).toBeInTheDocument();
      act_(200);
      expect(screen.queryByRole("button", { name: copy.chat.undo })).toBeNull();
      await press("screen");
      act_(3900);
      expect(screen.getByRole("status")).toHaveTextContent("→ 내일로: 책 읽기");
      act_(200);
      expect(screen.getByRole("status")).not.toHaveTextContent("→ 내일로: 책 읽기");
    });

    it("three changes in one answer: one toast, the count", async () => {
      mount(<Chat parts={[change(911, "✓ 추가: 치과"), change(912, "✓ 추가: 장보기"), change(913, "✓ 추가: 운동")]} />); // taste-skill-ignore: BE confirmation prefix (R4b), not UI
      await press("chat");
      expect(screen.getByRole("status")).toHaveTextContent(/^✓ 3개를 바꿨어요되돌리기$/); // taste-skill-ignore: BE confirmation prefix (R4b), not UI
      expect(screen.getAllByRole("button", { name: copy.chat.undo })).toHaveLength(1);
    });

    function serveUndos(blocked: number | null) {
      const hits: number[] = [];
      server.use(
        http.post(`${BASE}/activity/:id/undo`, ({ params }) => {
          const id = Number(params.id);
          hits.push(id);
          if (id === blocked) return HttpResponse.json({ error: { code: "superseded", message: "x" } }, { status: 409 });
          return HttpResponse.json({ status: "undone", activity_id: 990 + id, undone: id, confirmation: `↩ 되돌림 ${id}` });
        }),
      );
      return hits;
    }
    const three = [change(911, "a"), change(912, "b"), change(913, "c")];

    it("undo undoes all of them, newest first", async () => {
      const hits = serveUndos(null);
      const onUndone = vi.fn();
      function WithSub() {
        const toast = useToast();
        return (
          <>
            <Chat parts={three} />
            <button type="button" onClick={() => toast.onUndone(onUndone)}>
              sub
            </button>
          </>
        );
      }
      mount(<WithSub />);
      await userEvent.click(screen.getByText("sub"));
      await userEvent.click(screen.getByText("chat"));
      await userEvent.click(screen.getByRole("button", { name: copy.chat.undo }));
      expect(await screen.findByText(copy.chat.undone)).toBeInTheDocument();
      expect(hits).toEqual([913, 912, 911]);
      expect(screen.queryByRole("button", { name: copy.chat.undo })).toBeNull();
      expect(onUndone).toHaveBeenCalledTimes(1);
    });

    it("the second refused: stops there and says how many", async () => {
      const hits = serveUndos(912);
      mount(<Chat parts={three} />);
      await userEvent.click(screen.getByText("chat"));
      await userEvent.click(screen.getByRole("button", { name: copy.chat.undo }));
      expect(await screen.findByText("1개만 되돌렸어요")).toBeInTheDocument();
      expect(hits).toEqual([913, 912]);
    });

    it("the first refused: the reason, as for one", async () => {
      serveUndos(913);
      mount(<Chat parts={three} />);
      await userEvent.click(screen.getByText("chat"));
      await userEvent.click(screen.getByRole("button", { name: copy.chat.undo }));
      expect(await screen.findByText(copy.activity.undoBlocked.superseded)).toBeInTheDocument();
    });

    it("a second press while undoing sends nothing more", async () => {
      const hits = serveUndos(null);
      mount(<Chat parts={three} />);
      await userEvent.click(screen.getByText("chat"));
      const btn = screen.getByRole("button", { name: copy.chat.undo });
      await act(async () => {
        btn.click();
        btn.click();
      });
      expect(await screen.findByText(copy.chat.undone)).toBeInTheDocument();
      expect(hits).toEqual([913, 912, 911]);
    });

    it("nothing to undo: no toast", () => {
      expect(chatActivityToast([{ kind: "activity", confirmation: "✓ 초안", undoIds: [], activityIds: [1] }])).toBeNull(); // taste-skill-ignore: BE confirmation prefix (R4b), not UI
      expect(chatActivityToast([{ kind: "activity", confirmation: null, undoIds: [5], activityIds: [5] }])).toEqual({ text: copy.chat.changed, undoIds: [5] });
    });
  });
});
const act_ = (ms: number) => act(() => void vi.advanceTimersByTime(ms));
