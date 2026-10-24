import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { copy } from "../lib/copy";
import { renderWithProviders } from "../test/render";
import { MessageView } from "./MessageView";

const answer = { id: "m-1-1", role: "assistant" as const, parts: [] };

describe("MessageView", () => {
  it("the undo in a confirmation box is off while the sheet is read-only", () => {
    renderWithProviders(<MessageView message={answer} parts={[{ kind: "activity", confirmation: "추가했어요", undoIds: [3] }]} readOnly />);
    expect(screen.getByRole("button", { name: copy.chat.undo })).toBeDisabled();
  });
});
