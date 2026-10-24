import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { copy } from "../../lib/copy";
import { makeCtx, serveActions } from "../../test/parts";
import { renderWithProviders } from "../../test/render";
import { LadderPicker } from "./LadderPicker";

describe("LadderPicker", () => {
  it("records now field", async () => {
    const bodies = serveActions();
    const ctx = makeCtx();
    renderWithProviders(<LadderPicker props={{ period: "2026-10", field: "now" }} ctx={ctx} />);
    expect(screen.getAllByRole("button")).toHaveLength(11);
    await userEvent.click(screen.getByRole("button", { name: copy.parts.ladderScore(7) }));
    await waitFor(() => expect(bodies).toHaveLength(1));
    expect(bodies[0]).toMatchObject({ action: "record_ladder_score", args: { period: "2026-10", now: 7 } });
    await waitFor(() => expect(ctx.onAfterAction).toHaveBeenCalled());
  });

  it("records future field", async () => {
    const bodies = serveActions();
    renderWithProviders(<LadderPicker props={{ period: "2026-10", field: "future" }} ctx={makeCtx()} />);
    await userEvent.click(screen.getByRole("button", { name: copy.parts.ladderScore(0) }));
    await waitFor(() => expect(bodies).toHaveLength(1));
    expect(bodies[0]).toMatchObject({ args: { period: "2026-10", future: 0 } });
  });
});
