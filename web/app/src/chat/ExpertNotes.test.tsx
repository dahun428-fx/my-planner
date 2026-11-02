import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { UIMessage } from "ai";
import { describe, expect, it } from "vitest";
import { renderWithProviders } from "../test/render";
import { ExpertNotes } from "./ExpertNotes";
import { MessageView } from "./MessageView";
import { toViewParts } from "./parts";

const NOTES = [
  { expert: "career", text: "가짜 **커리어** 소견" },
  { expert: "relationship", text: "가짜 관계 소견" },
];

describe("ExpertNotes (SP15 1장 2)", () => {
  it("is one folded line; opened, each expert's name and note", async () => {
    const user = userEvent.setup();
    renderWithProviders(<ExpertNotes notes={NOTES} />);
    const line = screen.getByText("전문가 소견 2개");
    expect(line.closest("details")).not.toHaveAttribute("open");
    await user.click(line);
    expect(line.closest("details")).toHaveAttribute("open");
    expect(
      screen.getByText("커리어 전략가", { selector: "strong" }),
    ).toBeVisible();
    expect(screen.getByText("관계 코치", { selector: "strong" })).toBeVisible();
    expect(
      await screen.findByText("커리어", { selector: "strong" }),
    ).toBeInTheDocument(); // the note is Markdown
    expect(screen.getByText("가짜 관계 소견")).toBeInTheDocument();
  });

  it("draws nothing without notes", () => {
    renderWithProviders(<ExpertNotes notes={[]} />);
    expect(screen.queryByText(/전문가 소견/)).toBeNull();
    expect(document.querySelector("details")).toBeNull();
  });

  it("an answer read again from the history has the same line, under its text", async () => {
    // As history.ts rebuilds a life manager line with `expert_notes`.
    const m: UIMessage = {
      id: "m-12-2",
      role: "assistant",
      parts: [
        { type: "text", text: "가짜 답" },
        { type: "data-expert-notes", data: { notes: NOTES } },
      ] as UIMessage["parts"],
    };
    renderWithProviders(
      <MessageView
        message={m}
        parts={toViewParts(m)}
        speakerName="라이프 매니저"
      />,
    );
    const line = await screen.findByText("전문가 소견 2개");
    const answer = await screen.findByText("가짜 답");
    expect(
      answer.compareDocumentPosition(line) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });
});
