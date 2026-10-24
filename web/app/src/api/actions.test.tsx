import { act, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { saveConn } from "../lib/connection";
import { renderWithProviders, TEST_BE_URL, TEST_TOKEN } from "../test/render";
import { BASE, server } from "../test/server";
import { runAction, undoActivity, useAction } from "./actions";

const UUID4 = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const applied = { status: "applied", activity_id: 913, undo_id: 913, result: { id: 12 }, confirmation: "✓ 완료: 운동", xp: { gained: 10, level_up: null } };

function record(answer: () => Response | Promise<Response>) {
  const bodies: Record<string, unknown>[] = [];
  server.use(
    http.post(`${BASE}/actions`, async ({ request }) => {
      bodies.push((await request.json()) as Record<string, unknown>);
      return answer();
    }),
  );
  return bodies;
}

describe("runAction", () => {
  it("sends client_msg_id per action", async () => {
    saveConn({ beUrl: TEST_BE_URL, token: TEST_TOKEN });
    const bodies = record(() => HttpResponse.json(applied));
    await runAction("complete_task", { id: 12 });
    await runAction("complete_task", { id: 13 });
    expect(bodies).toHaveLength(2);
    expect(bodies[0].client_msg_id).toMatch(UUID4);
    expect(bodies[1].client_msg_id).toMatch(UUID4);
    expect(bodies[0].client_msg_id).not.toBe(bodies[1].client_msg_id);
    expect(bodies[0]).toMatchObject({ action: "complete_task", args: { id: 12 }, confirm_token: null });
  });

  it("retries once with same id on network error", async () => {
    saveConn({ beUrl: TEST_BE_URL, token: TEST_TOKEN });
    let n = 0;
    const bodies = record(() => (++n === 1 ? HttpResponse.error() : HttpResponse.json(applied)));
    const out = await runAction("complete_task", { id: 12 });
    expect(out.kind).toBe("applied");
    expect(bodies).toHaveLength(2);
    expect(bodies[1].client_msg_id).toBe(bodies[0].client_msg_id);
  });

  it("does not send a third request", async () => {
    saveConn({ beUrl: TEST_BE_URL, token: TEST_TOKEN });
    const bodies = record(() => HttpResponse.error());
    const out = await runAction("complete_task", { id: 12 });
    expect(bodies).toHaveLength(2);
    expect(out).toEqual({ kind: "failed", result: { kind: "offline" } });
  });

  it("maps applied/needs_confirm/rejected/conflict", async () => {
    saveConn({ beUrl: TEST_BE_URL, token: TEST_TOKEN });
    record(() => HttpResponse.json(applied));
    expect(await runAction("complete_task", { id: 12 })).toEqual({
      kind: "applied",
      activityId: 913,
      undoId: 913,
      confirmation: "✓ 완료: 운동",
      result: { id: 12 },
    });

    server.use(http.post(`${BASE}/actions`, () => HttpResponse.json({ status: "applied", activity_id: 5, result: {}, confirmation: "x" })));
    expect(await runAction("drop_task", { id: 1 })).toMatchObject({ kind: "applied", undoId: null });

    server.use(
      http.post(`${BASE}/actions`, () =>
        HttpResponse.json({ status: "needs_confirm", confirm_token: "ct_1", summary: "이번 분기 우선순위 3개를 바꿔요", expires_at: "2026-10-24T09:10:00Z" }),
      ),
    );
    expect(await runAction("drop_task", { id: 1 })).toEqual({
      kind: "needs_confirm",
      confirmToken: "ct_1",
      summary: "이번 분기 우선순위 3개를 바꿔요",
      expiresAt: "2026-10-24T09:10:00Z",
    });

    server.use(
      http.post(`${BASE}/actions`, () =>
        HttpResponse.json({ status: "rejected", activity_id: null, error: { code: "rejected", message: "우선순위는 3개까지예요" } }, { status: 422 }),
      ),
    );
    expect(await runAction("set_priorities", {})).toEqual({ kind: "rejected", message: "우선순위는 3개까지예요" });

    server.use(http.post(`${BASE}/actions`, () => HttpResponse.json({ error: { code: "conflict", message: "x" } }, { status: 409 })));
    expect(await runAction("confirm_tasks", { ids: [1] })).toEqual({ kind: "conflict" });

    server.use(http.post(`${BASE}/actions`, () => HttpResponse.json({ error: { code: "internal", message: "x" } }, { status: 500 })));
    expect(await runAction("confirm_tasks", { ids: [1] })).toMatchObject({ kind: "failed", result: { kind: "error", status: 500 } });
  });

  it("confirm uses new id and token", async () => {
    saveConn({ beUrl: TEST_BE_URL, token: TEST_TOKEN });
    let n = 0;
    const bodies = record(() =>
      ++n === 1
        ? HttpResponse.json({ status: "needs_confirm", confirm_token: "ct_9", summary: "s", expires_at: "2026-10-24T09:10:00Z" })
        : HttpResponse.json(applied),
    );
    const first = await runAction("drop_task", { id: 12 });
    expect(first.kind).toBe("needs_confirm");
    const second = await runAction("drop_task", { id: 12 }, { confirmToken: "ct_9" });
    expect(second.kind).toBe("applied");
    expect(bodies[1].confirm_token).toBe("ct_9");
    expect(bodies[1].client_msg_id).not.toBe(bodies[0].client_msg_id);
    expect(bodies[1].args).toEqual({ id: 12 });
  });
});

describe("undoActivity", () => {
  const undo = (status: number, body: Record<string, unknown>) =>
    server.use(http.post(`${BASE}/activity/913/undo`, () => HttpResponse.json(body, { status })));

  it("undo outcomes", async () => {
    saveConn({ beUrl: TEST_BE_URL, token: TEST_TOKEN });
    undo(200, { status: "undone", activity_id: 920, undone: 913, confirmation: "↩ 되돌림: 운동 완료" });
    expect(await undoActivity(913)).toEqual({ kind: "undone", confirmation: "↩ 되돌림: 운동 완료" });
    undo(200, { status: "already_undone", activity_id: 920 });
    expect(await undoActivity(913)).toEqual({ kind: "already_undone" });
    undo(409, { error: { code: "superseded", message: "x" } });
    expect(await undoActivity(913)).toEqual({ kind: "blocked", reason: "superseded" });
    undo(409, { error: { code: "undo_expired", message: "x" } });
    expect(await undoActivity(913)).toEqual({ kind: "blocked", reason: "undo_expired" });
    undo(422, { error: { code: "not_undoable", message: "x" } });
    expect(await undoActivity(913)).toEqual({ kind: "blocked", reason: "not_undoable" });
    undo(500, { error: { code: "internal", message: "x" } });
    expect(await undoActivity(913)).toMatchObject({ kind: "failed" });
  });

  it("retries once with same id on network error", async () => {
    saveConn({ beUrl: TEST_BE_URL, token: TEST_TOKEN });
    const ids: unknown[] = [];
    server.use(
      http.post(`${BASE}/activity/913/undo`, async ({ request }) => {
        ids.push(((await request.json()) as { client_msg_id: string }).client_msg_id);
        return ids.length === 1 ? HttpResponse.error() : HttpResponse.json({ status: "undone", activity_id: 920, undone: 913, confirmation: "c" });
      }),
    );
    expect((await undoActivity(913)).kind).toBe("undone");
    expect(ids).toHaveLength(2);
    expect(ids[1]).toBe(ids[0]);
    expect(ids[0]).toMatch(UUID4);
  });
});

function Rows() {
  const { run, isPending } = useAction();
  return (
    <>
      <button type="button" onClick={() => void run("complete_task", { id: 1 })}>
        row1
      </button>
      <button type="button" onClick={() => void run("complete_task", { id: 2 })}>
        row2
      </button>
      <output>{isPending("complete_task", { id: 1 }) ? "pending" : "idle"}</output>
    </>
  );
}

describe("useAction", () => {
  it("double tap sends one request", async () => {
    let release!: () => void;
    const gate = new Promise<void>((r) => (release = r));
    const bodies = record(async () => {
      await gate;
      return HttpResponse.json(applied);
    });
    let results: unknown[] = [];
    function Probe() {
      const { run } = useAction();
      return (
        <button
          type="button"
          onClick={() => {
            const a = run("complete_task", { id: 1 });
            const b = run("complete_task", { id: 1 });
            void Promise.all([a, b]).then((r) => (results = r));
          }}
        >
          go
        </button>
      );
    }
    renderWithProviders(<Probe />);
    await userEvent.click(screen.getByText("go"));
    release();
    await waitFor(() => expect(results).toHaveLength(2));
    expect(bodies).toHaveLength(1);
    expect(results[0]).toMatchObject({ kind: "applied" });
    expect(results[1]).toBeNull();
  });

  it("different rows are not blocked", async () => {
    let release!: () => void;
    const gate = new Promise<void>((r) => (release = r));
    const bodies = record(async () => {
      await gate;
      return HttpResponse.json(applied);
    });
    renderWithProviders(<Rows />);
    await userEvent.click(screen.getByText("row1"));
    await userEvent.click(screen.getByText("row2"));
    await waitFor(() => expect(bodies).toHaveLength(2));
    expect(screen.getByText("pending")).toBeInTheDocument();
    await act(async () => release());
    await waitFor(() => expect(screen.getByText("idle")).toBeInTheDocument());
  });

  it("shows the confirmation in the toast with an undo button", async () => {
    record(() => HttpResponse.json(applied));
    renderWithProviders(<Rows />);
    await userEvent.click(screen.getByText("row1"));
    expect(await screen.findByText("✓ 완료: 운동")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "되돌리기" })).toBeInTheDocument();
  });

  it("shows the rejection message and the offline text", async () => {
    record(() => HttpResponse.json({ status: "rejected", activity_id: null, error: { code: "rejected", message: "우선순위는 3개까지예요" } }, { status: 422 }));
    renderWithProviders(<Rows />);
    await userEvent.click(screen.getByText("row1"));
    expect(await screen.findByText("우선순위는 3개까지예요")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "되돌리기" })).toBeNull();
  });
});
