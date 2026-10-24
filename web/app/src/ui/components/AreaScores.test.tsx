import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { copy } from "../../lib/copy";
import { makeCtx, serveActions } from "../../test/parts";
import { renderWithProviders } from "../../test/render";
import { AreaScores } from "./AreaScores";

describe("AreaScores", () => {
  it("saves chosen areas only", async () => {
    const bodies = serveActions();
    const ctx = makeCtx();
    renderWithProviders(<AreaScores props={{ period: "2026-Q4", previous: { career: 6, health: 4 } }} ctx={ctx} />);
    expect(screen.getAllByRole("radiogroup")).toHaveLength(6);
    expect(screen.getByText(copy.parts.previous(6))).toBeInTheDocument();
    expect(screen.getByRole("button", { name: copy.parts.save })).toBeDisabled();

    const career = screen.getByRole("radiogroup", { name: copy.parts.areaLabel(copy.areas.career) });
    await userEvent.click(within(career).getByRole("radio", { name: "7" }));
    const learning = screen.getByRole("radiogroup", { name: copy.parts.areaLabel(copy.areas.learning) });
    await userEvent.click(within(learning).getByRole("radio", { name: "3" }));
    await userEvent.click(screen.getByRole("button", { name: copy.parts.save }));
    await waitFor(() => expect(bodies).toHaveLength(1));
    expect(bodies[0]).toMatchObject({ action: "record_area_scores", args: { period: "2026-Q4", scores: { career: 7, learning: 3 } } });
    expect(Object.keys((bodies[0].args as { scores: object }).scores)).toEqual(["career", "learning"]);
    await waitFor(() => expect(ctx.onAfterAction).toHaveBeenCalled());
  });
});
