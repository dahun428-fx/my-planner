import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { copy } from "../lib/copy";
import { markdownChunk } from "../components/Markdown";
import { renderWithProviders } from "../test/render";
import { MessageView } from "./MessageView";

const answer = { id: "m-1-1", role: "assistant" as const, parts: [] };

describe("MessageView", () => {
  it("the undo in a confirmation box is off while the sheet is read-only", () => {
    renderWithProviders(<MessageView message={answer} parts={[{ kind: "activity", confirmation: "추가했어요", undoIds: [3] }]} readOnly />);
    expect(screen.getByRole("button", { name: copy.chat.undo })).toBeDisabled();
  });

  it("the secretary's text is Markdown; my own stays plain", async () => {
    await markdownChunk.load();
    const mine = { id: "m-1-0", role: "user" as const, parts: [{ type: "text" as const, text: "**내 말** <b>x</b>" }] };
    const { container } = renderWithProviders(
      <>
        <MessageView message={mine} parts={[]} />
        <MessageView message={answer} parts={[{ kind: "text", text: "**비서 말** [링크](https://example.com)" }]} />
      </>,
    );
    expect(screen.getByText("**내 말** <b>x</b>")).toBeInTheDocument();
    expect(container.querySelector('[data-message="m-1-0"] strong, [data-message="m-1-0"] b')).toBeNull();
    expect(container.querySelector('[data-message="m-1-1"] strong')).toHaveTextContent("비서 말");
    expect(screen.getByRole("link", { name: "링크" })).toHaveAttribute("target", "_blank");
  });
});
