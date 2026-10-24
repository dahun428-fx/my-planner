import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { copy } from "../../lib/copy";
import { makeCtx, serveActions } from "../../test/parts";
import { renderWithProviders } from "../../test/render";
import { ConditionPicker } from "./ConditionPicker";

describe("ConditionPicker", () => {
  it("records score then note", async () => {
    const bodies = serveActions();
    renderWithProviders(<ConditionPicker props={{ date: "2026-10-24" }} ctx={makeCtx()} />);
    await userEvent.click(screen.getByRole("button", { name: copy.today.conditionScore(4) }));
    await waitFor(() => expect(bodies).toHaveLength(1));
    expect(bodies[0]).toMatchObject({ action: "record_condition", args: { date: "2026-10-24", score: 4 } });
    expect((bodies[0].args as Record<string, unknown>).note).toBeUndefined();

    await userEvent.type(screen.getByRole("textbox", { name: copy.parts.noteLabel }), "잠을 못 잤어요");
    await userEvent.tab();
    await waitFor(() => expect(bodies).toHaveLength(2));
    expect(bodies[1]).toMatchObject({ action: "record_condition", args: { date: "2026-10-24", score: 4, note: "잠을 못 잤어요" } });
    expect(bodies[1].client_msg_id).not.toBe(bodies[0].client_msg_id);
  });

  it("does not send an empty note", async () => {
    const bodies = serveActions();
    renderWithProviders(<ConditionPicker props={{ date: "2026-10-24" }} ctx={makeCtx()} />);
    await userEvent.click(screen.getByRole("button", { name: copy.today.conditionScore(2) }));
    await waitFor(() => expect(bodies).toHaveLength(1));
    await userEvent.click(screen.getByRole("textbox", { name: copy.parts.noteLabel }));
    await userEvent.tab();
    expect(bodies).toHaveLength(1);
  });
});
