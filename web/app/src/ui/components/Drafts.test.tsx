import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { copy } from "../../lib/copy";
import { makeCtx, serveActions } from "../../test/parts";
import { renderWithProviders } from "../../test/render";
import { ChapterDraft } from "./ChapterDraft";
import { MilestoneDraft } from "./MilestoneDraft";

const milestones = [
  { id: 3, title: "첫 직장 입사", date: "2019-03", area: "career", sensitive: false },
  { id: 4, title: "이사", date: "2022-08-15", area: "quality_of_life", sensitive: false },
];
const chapters = [
  { id: 8, title: "회사 다니던 때", start_month: "2019-03", end_month: "2024-02" },
  { id: 9, title: "다시 배우는 때", start_month: "2024-03", end_month: null },
];

describe("MilestoneDraft", () => {
  it("confirm and drop per row", async () => {
    const bodies = serveActions();
    const ctx = makeCtx();
    renderWithProviders(<MilestoneDraft props={{ milestone_ids: [3, 4] }} data={{ milestones }} ctx={ctx} />);
    expect(screen.getByText(copy.parts.yearMonth(2019, 3))).toBeInTheDocument();
    const rows = screen.getAllByRole("listitem");
    await userEvent.click(within(rows[0]).getByRole("button", { name: copy.parts.confirmOne }));
    await waitFor(() => expect(bodies).toHaveLength(1));
    expect(bodies[0]).toMatchObject({ action: "confirm_milestones", args: { ids: [3] } });
    await userEvent.click(within(screen.getAllByRole("listitem")[screen.getAllByRole("listitem").length - 1]).getByRole("button", { name: copy.parts.drop }));
    await waitFor(() => expect(bodies).toHaveLength(2));
    expect(bodies[1]).toMatchObject({ action: "drop_milestone", args: { id: 4 } });
    await waitFor(() => expect(ctx.onAfterAction).toHaveBeenCalledTimes(2));
  });

  it("fallback without data", () => {
    renderWithProviders(<MilestoneDraft props={{ milestone_ids: [3, 4, 5] }} ctx={makeCtx()} />);
    expect(screen.getByText(copy.parts.milestoneCount(3))).toBeInTheDocument();
    expect(screen.queryByRole("button")).toBeNull();
  });
});

describe("ChapterDraft", () => {
  it("confirm and drop per row", async () => {
    const bodies = serveActions();
    renderWithProviders(<ChapterDraft props={{ chapter_ids: [8, 9] }} data={{ chapters }} ctx={makeCtx()} />);
    expect(screen.getByText(copy.parts.period(copy.parts.yearMonth(2024, 3), null))).toBeInTheDocument();
    const rows = screen.getAllByRole("listitem");
    await userEvent.click(within(rows[1]).getByRole("button", { name: copy.parts.confirmOne }));
    await waitFor(() => expect(bodies).toHaveLength(1));
    expect(bodies[0]).toMatchObject({ action: "confirm_chapters", args: { ids: [9] } });
    await userEvent.click(within(screen.getAllByRole("listitem")[0]).getByRole("button", { name: copy.parts.drop }));
    await waitFor(() => expect(bodies).toHaveLength(2));
    expect(bodies[1]).toMatchObject({ action: "drop_chapter", args: { id: 8 } });
  });

  it("fallback without data", () => {
    renderWithProviders(<ChapterDraft props={{ chapter_ids: [8] }} ctx={makeCtx()} />);
    expect(screen.getByText(copy.parts.chapterCount(1))).toBeInTheDocument();
  });
});
