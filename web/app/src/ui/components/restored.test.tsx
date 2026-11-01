import { screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import userEvent from "@testing-library/user-event";
import type { ReactElement } from "react";
import { describe, expect, it, vi } from "vitest";
import { copy } from "../../lib/copy";
import { SUGGESTION } from "../../test/panel";
import { makeCtx, makeHabit, makeTodo, serveActions } from "../../test/parts";
import { renderWithProviders } from "../../test/render";
import { BASE, server } from "../../test/server";
import { forgetProposed, PanelSuggestion } from "./PanelSuggestion";
import { ChapterDraft } from "./ChapterDraft";
import { Choice } from "./Choice";
import { HabitCheck } from "./HabitList";
import { MeasureConfirm, type MeasureConfirmProps } from "./MeasureConfirm";
import { MilestoneDraft } from "./MilestoneDraft";
import { TodoDraft } from "./TodoDraft";

const MEASURES: MeasureConfirmProps = { rows: [{ metric: "weight_kg", label: "몸무게", value: 70, unit: "kg", measured_on: "2026-10-01" }, { metric: "cert", label: "자격", value: "toeic:900", unit: null, measured_on: "2026-10-01" }], source_kind: "manual", source_ref: null };

// A part restored from the device after a reload (4.6) holds rows as they were then: it writes nothing.
const ctx = makeCtx({ restored: true, onChoose: vi.fn() });

const cases: [string, ReactElement, string][] = [
  ["TodoDraft", <TodoDraft key="a" props={{ task_ids: [1] }} data={{ todos: [makeTodo(1, "빨래", "draft")] }} ctx={ctx} />, "빨래"],
  ["MilestoneDraft", <MilestoneDraft key="b" props={{ milestone_ids: [1] }} data={{ milestones: [{ id: 1, title: "사건", date: "2020-01" }] }} ctx={ctx} />, "사건"],
  ["ChapterDraft", <ChapterDraft key="c" props={{ chapter_ids: [1] }} data={{ chapters: [{ id: 1, title: "챕터", start_month: "2020-01", end_month: null }] }} ctx={ctx} />, "챕터"],
  ["MeasureConfirm", <MeasureConfirm key="d" props={MEASURES} ctx={ctx} />, "몸무게"],
];

describe("restored parts", () => {
  it.each(cases)("%s shows its rows without action buttons", (_name, el, title) => {
    renderWithProviders(el);
    expect(screen.getByText(title)).toBeInTheDocument();
    expect(screen.queryAllByRole("button")).toEqual([]);
  });

  it("MeasureConfirm fields are off and nothing is written", () => {
    renderWithProviders(<MeasureConfirm props={MEASURES} ctx={ctx} />);
    for (const f of screen.getAllByLabelText(/몸무게|자격/)) expect(f).toBeDisabled();
    expect(screen.queryByText(copy.offline.writeLater)).toBeNull();
  });

  it("Choice pills are off: a stale choice must not go into the current conversation", () => {
    renderWithProviders(<Choice props={{ question: "q", options: [{ id: "a", label: "가" }, { id: "b", label: "나" }] }} ctx={ctx} />);
    for (const b of screen.getAllByRole("button")) expect(b).toBeDisabled();
  });

  it("HabitCheck rows are drawn, not pressable: the habits may have been checked elsewhere since", async () => {
    const bodies = serveActions();
    renderWithProviders(<HabitCheck props={{ date: "2026-10-24" }} data={{ habits: [makeHabit(1, "물 마시기"), makeHabit(2, "운동", { checked: true })] }} ctx={ctx} />);
    expect(screen.getByText("물 마시기")).toBeInTheDocument();
    expect(screen.queryAllByRole("button")).toEqual([]);
    const boxes = screen.getAllByRole("checkbox");
    expect(boxes).toHaveLength(2);
    for (const b of boxes) expect(b).toBeDisabled();
    await userEvent.click(boxes[0]);
    expect(bodies).toHaveLength(0);
    // Online: no "연결되면" reason under a restored card.
    expect(screen.queryByText(copy.offline.writeLater)).toBeNull();
  });

  // Review Focus 2 (SP15): a restored suggestion keeps its buttons while the BE still has it proposed.
  describe("PanelSuggestion", () => {
    const serveProposed = (ids: number[]) => {
      const hits: (string | null)[] = [];
      server.use(
        http.get(`${BASE}/panel/suggestions`, ({ request }) => {
          hits.push(new URL(request.url).searchParams.get("state"));
          return HttpResponse.json({ items: ids.map((id) => ({ ...SUGGESTION, id })) });
        }),
      );
      return hits;
    };

    it("restored suggestion keeps buttons while proposed; two cards share one request", async () => {
      forgetProposed();
      const hits = serveProposed([31]);
      renderWithProviders(
        <>
          <PanelSuggestion props={{ suggestion_id: 31 }} data={{ suggestion: SUGGESTION }} ctx={ctx} />
          <PanelSuggestion props={{ suggestion_id: 32 }} data={{ suggestion: { ...SUGGESTION, id: 32, title: "가짜 둘째" } }} ctx={ctx} />
        </>,
      );
      expect(await screen.findByRole("button", { name: "받기" })).toBeEnabled();
      expect(screen.getAllByRole("button", { name: "받기" })).toHaveLength(1); // 32 is not proposed any more
      expect(screen.getByText("가짜 둘째")).toBeInTheDocument();
      expect(hits).toEqual(["proposed"]);
    });

    it("a restored suggestion no longer proposed is read-only", async () => {
      forgetProposed();
      const hits = serveProposed([]);
      renderWithProviders(<PanelSuggestion props={{ suggestion_id: 31 }} data={{ suggestion: SUGGESTION }} ctx={ctx} />);
      await waitFor(() => expect(hits).toEqual(["proposed"]));
      expect(screen.getByText("가짜 산책 습관")).toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "받기" })).toBeNull();
      expect(screen.queryByRole("button", { name: "버리기" })).toBeNull();
    });
  });
});
