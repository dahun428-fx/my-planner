import { readFileSync } from "node:fs";
import { join } from "node:path";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { copy } from "../../lib/copy";
import { makeCtx } from "../../test/parts";
import { renderWithProviders } from "../../test/render";
import { BASE, server } from "../../test/server";
import type { PartTodo, ResultChange, ResultItem, TodoSnap } from "../types";
import { Result } from "./Result";

// SP6 6.3. Today is 2026-10-24 (Sat).
const snap = (over: Partial<TodoSnap> = {}): TodoSnap => ({ status: null, planned_for: null, scheduled_at: null, title: null, ...over });
const todo = (id: number, title: string, over: Partial<PartTodo> = {}): PartTodo => ({ id, title, status: "open", planned_for: "2026-10-27", scheduled_at: null, ...over });
function item(change: ResultChange, over: Partial<ResultItem> = {}): ResultItem {
  return {
    todo: todo(53, "치과 예약"),
    change,
    before: snap({ planned_for: "2026-10-25" }),
    after: snap({ status: "open", planned_for: "2026-10-27" }),
    activity_ids: [931],
    undo_id: null,
    ...over,
  };
}
const card = () => within(document.querySelector("section")!);

function serveUndo(answer: () => Response) {
  const hits: string[] = [];
  server.use(
    http.post(`${BASE}/activity/:id/undo`, ({ params }) => {
      hits.push(String(params.id));
      return answer();
    }),
  );
  return hits;
}

describe("Result", () => {
  it("change rows per kind", () => {
    const items: ResultItem[] = [
      item("moved"),
      item("added", { todo: todo(54, "장보기", { planned_for: null }), before: null, after: snap({ status: "open" }) }),
      item("added", { todo: todo(55, "회의"), before: null, after: snap({ status: "open", planned_for: "2026-10-27", scheduled_at: "2026-10-27T05:00:00Z" }) }),
      item("updated", { todo: todo(56, "치과 진료"), before: snap({ title: "치과" }), after: snap({ title: "치과 진료" }) }),
      item("updated", { todo: todo(57, "운동"), before: snap({ scheduled_at: "2026-10-24T05:00:00Z" }), after: snap({ scheduled_at: "2026-10-24T07:00:00Z" }) }),
      item("updated", { todo: todo(58, "독서"), before: snap({ planned_for: "2026-10-25" }), after: snap({ planned_for: "2026-10-27" }) }),
      item("updated", { todo: todo(59, "빨래"), before: snap(), after: snap() }),
      item("confirmed", { todo: todo(60, "청소"), before: snap({ status: "draft" }) }),
      item("completed", { todo: todo(61, "산책", { status: "done" }) }),
      item("dropped", { todo: todo(62, "정리", { status: "dropped" }) }),
      item("reopened", { todo: todo(63, "편지") }),
    ];
    renderWithProviders(<Result props={{ task_ids: [53] }} data={{ today: "2026-10-24", items }} ctx={makeCtx()} />);
    const chips = [...document.querySelectorAll(".changeChip")].map((c) => c.textContent);
    expect(chips).toEqual(["옮김", "추가", "추가", "고침", "고침", "고침", "고침", "확정", "완료", "뺌", "다시 엶"]);

    const moved = screen.getAllByRole("img", { name: "이전 10월 25일 (일), 지금 10월 27일 (화)" });
    expect(moved).toHaveLength(2); // moved, and updated with only the date (gap 4)
    expect(moved[0]).toHaveTextContent("10월 25일 (일) → 10월 27일 (화)");
    expect(moved[0]).toHaveAttribute("aria-label", "이전 10월 25일 (일), 지금 10월 27일 (화)");
    expect(screen.getByText(copy.parts.noDate)).toBeInTheDocument();
    expect(screen.getByText("10월 27일 (화) 14:00")).toBeInTheDocument();
    expect(screen.getByText("이전 제목: 치과")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "이전 14:00, 지금 16:00" })).toHaveTextContent("14:00 → 16:00");
    expect(screen.getByText(copy.parts.editedOnly)).toBeInTheDocument();
    expect(screen.getByText(copy.parts.confirmedDraft)).toBeInTheDocument();
    expect(screen.getByText("산책")).toHaveClass("struck");
    expect(screen.getByText("정리")).toHaveClass("struck");
    expect(screen.getByText("편지")).not.toHaveClass("struck");
    // Dividers between the items, not before the first or after the last.
    expect(document.querySelectorAll("hr")).toHaveLength(items.length - 1);
  });

  it("undo only with undo_id", () => {
    const items = [item("moved", { undo_id: 931 }), item("moved", { todo: todo(54, "장보기"), activity_ids: [932, 933] })];
    renderWithProviders(<Result props={{ task_ids: [53, 54] }} data={{ today: "2026-10-24", items }} ctx={makeCtx()} />);
    expect(card().getAllByRole("button", { name: copy.chat.undo })).toHaveLength(1);
  });

  it("undo sends and shows done", async () => {
    const hits = serveUndo(() => HttpResponse.json({ status: "undone", activity_id: 940, undone: 931, confirmation: "되돌렸어요: 치과 예약" }));
    const ctx = makeCtx();
    renderWithProviders(<Result props={{ task_ids: [53] }} data={{ today: "2026-10-24", items: [item("moved", { undo_id: 931 })] }} ctx={ctx} />);
    await userEvent.click(card().getByRole("button", { name: copy.chat.undo }));
    await waitFor(() => expect(card().getByText(copy.chat.undone)).toBeInTheDocument());
    expect(hits).toEqual(["931"]);
    expect(card().queryByRole("button", { name: copy.chat.undo })).toBeNull();
    expect(ctx.onAfterAction).toHaveBeenCalledTimes(1);
  });

  it("already undone shows done", async () => {
    serveUndo(() => HttpResponse.json({ status: "already_undone" }));
    renderWithProviders(<Result props={{ task_ids: [53] }} data={{ today: "2026-10-24", items: [item("moved", { undo_id: 931 })] }} ctx={makeCtx()} />);
    await userEvent.click(card().getByRole("button", { name: copy.chat.undo }));
    expect(await card().findByText(copy.chat.undone)).toBeInTheDocument();
  });

  it("undo blocked shows reason", async () => {
    serveUndo(() => HttpResponse.json({ error: { code: "superseded", message: "x" } }, { status: 409 }));
    const { unmount } = renderWithProviders(<Result props={{ task_ids: [53] }} data={{ today: "2026-10-24", items: [item("moved", { undo_id: 931 })] }} ctx={makeCtx()} />);
    await userEvent.click(card().getByRole("button", { name: copy.chat.undo }));
    expect(await card().findByText(copy.activity.undoBlocked.superseded)).toBeInTheDocument();
    unmount();
    serveUndo(() => HttpResponse.json({ error: { code: "not_undoable", message: "x" } }, { status: 422 }));
    renderWithProviders(<Result props={{ task_ids: [53] }} data={{ today: "2026-10-24", items: [item("moved", { undo_id: 931 })] }} ctx={makeCtx()} />);
    await userEvent.click(card().getByRole("button", { name: copy.chat.undo }));
    expect(await card().findByText(copy.activity.undoBlocked.not_undoable)).toBeInTheDocument();
  });

  it("read only disables undo", () => {
    renderWithProviders(<Result props={{ task_ids: [53] }} data={{ today: "2026-10-24", items: [item("moved", { undo_id: 931 })] }} ctx={makeCtx({ readOnly: true })} />);
    expect(card().getByRole("button", { name: copy.chat.undo })).toBeDisabled();
    expect(card().getByText(copy.offline.writeLater)).toBeInTheDocument();
  });

  it("restored has no undo", () => {
    renderWithProviders(<Result props={{ task_ids: [53] }} data={{ today: "2026-10-24", items: [item("moved", { undo_id: 931 })] }} ctx={makeCtx({ restored: true })} />);
    expect(card().queryByRole("button")).toBeNull();
    expect(screen.getByText("치과 예약")).toBeInTheDocument();
  });

  it("no data shows count", () => {
    renderWithProviders(<Result props={{ task_ids: [53, 54] }} ctx={makeCtx()} />);
    expect(screen.getByText("바뀐 할 일 2개")).toBeInTheDocument();
  });

  it("chips use hue class only", () => {
    renderWithProviders(<Result props={{ task_ids: [53] }} data={{ today: "2026-10-24", items: [item("moved", { undo_id: 931 })] }} ctx={makeCtx()} />);
    const chip = screen.getByText("옮김");
    expect(chip.className).toBe("changeChip");
    const css = readFileSync(join(__dirname, "cards.module.css"), "utf8").replace(/\/\*[\s\S]*?\*\//g, "");
    const withHue = [...css.matchAll(/([^{}]+)\{([^{}]*)\}/g)].filter(([, , body]) => body.includes("var(--hue)")).map(([, sel]) => sel.trim());
    expect(withHue).toEqual([".changeChip"]);
  });
});
