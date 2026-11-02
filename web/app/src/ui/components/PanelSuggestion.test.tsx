import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";
import { SUGGESTION } from "../../test/panel";
import { makeCtx, serveActions } from "../../test/parts";
import { renderWithProviders } from "../../test/render";
import { forgetProposed, PanelSuggestion } from "./PanelSuggestion";

const BANNED = [
  "연속",
  "스트릭",
  "달성률",
  "실패",
  "남음",
  "%",
  "못 했",
  "뒤처졌",
];

beforeEach(() => forgetProposed());

describe("PanelSuggestion (SP15 1장 3·6, 11장)", () => {
  it("shows the title, area dot, size, times a week and the experts", () => {
    renderWithProviders(
      <PanelSuggestion
        props={{ suggestion_id: 31 }}
        data={{ suggestion: SUGGESTION }}
        ctx={makeCtx()}
      />,
    );
    expect(
      screen.getByRole("heading", { name: "가짜 산책 습관" }),
    ).toBeInTheDocument();
    expect(
      document.querySelector('.area-dot[data-area="health"]'),
    ).not.toBeNull();
    expect(screen.getByText(/약 20분/)).toBeInTheDocument();
    expect(screen.getByText(/주 3번/)).toBeInTheDocument();
    expect(screen.getByText(/건강 전문의, 심리 코치/)).toBeInTheDocument();
    const text = document.body.textContent ?? "";
    expect(BANNED.filter((w) => text.includes(w))).toEqual([]);
  });

  it("받기 accepts the suggestion, then says so without buttons", async () => {
    const bodies = serveActions();
    const user = userEvent.setup();
    const ctx = makeCtx();
    renderWithProviders(
      <PanelSuggestion
        props={{ suggestion_id: 31 }}
        data={{ suggestion: SUGGESTION }}
        ctx={ctx}
      />,
    );
    await user.click(screen.getByRole("button", { name: "받기" }));
    expect(await screen.findByText("받았어요")).toBeInTheDocument();
    expect(bodies).toHaveLength(1);
    expect(bodies[0]).toMatchObject({
      action: "accept_suggestion",
      args: { id: 31 },
    });
    expect(screen.queryByRole("button", { name: "받기" })).toBeNull();
    expect(screen.queryByRole("button", { name: "버리기" })).toBeNull();
    expect(ctx.onAfterAction).toHaveBeenCalled();
  });

  it("버리기 asks why with five chips and sends the reason", async () => {
    const bodies = serveActions();
    const user = userEvent.setup();
    renderWithProviders(
      <PanelSuggestion
        props={{ suggestion_id: 31 }}
        data={{ suggestion: SUGGESTION }}
        ctx={makeCtx()}
      />,
    );
    await user.click(screen.getByRole("button", { name: "버리기" }));
    const sheet = await screen.findByRole("dialog", { name: "버리는 이유" });
    expect(
      within(sheet)
        .getAllByRole("button")
        .map((b) => b.textContent)
        .filter((t) => t !== "" && t !== "닫기"),
    ).toEqual(
      expect.arrayContaining([
        "시간 없음",
        "관심 없음",
        "이미 하는 중",
        "너무 큼",
        "그냥",
      ]),
    );
    expect(bodies).toHaveLength(0);
    await user.click(within(sheet).getByRole("button", { name: "너무 큼" }));
    expect(await screen.findByText("버렸어요")).toBeInTheDocument();
    expect(bodies).toHaveLength(1);
    expect(bodies[0]).toMatchObject({
      action: "dismiss_suggestion",
      args: { id: 31, reason: "too_big" },
    });
    expect(screen.queryByRole("button", { name: "받기" })).toBeNull();
  });

  it("근거 보기 opens the three groups; a row with an address is a link, a bench row is text", async () => {
    const user = userEvent.setup();
    renderWithProviders(
      <PanelSuggestion
        props={{ suggestion_id: 31 }}
        data={{ suggestion: SUGGESTION }}
        ctx={makeCtx()}
      />,
    );
    await user.click(screen.getByText("근거 보기"));
    for (const g of ["내 기록", "내가 한 말", "외부 기준"])
      expect(screen.getByText(g)).toBeVisible();
    expect(
      screen.getByRole("link", { name: "가짜 할 일 기록" }),
    ).toHaveAttribute("href", "/todos/");
    expect(screen.getByRole("link", { name: "가짜로 한 말" })).toHaveAttribute(
      "href",
      "/more/statements/",
    );
    expect(screen.queryByRole("link", { name: "가짜 외부 기준" })).toBeNull();
    expect(screen.getByText("가짜 외부 기준")).toBeInTheDocument();
  });

  it("an evidence link inside the chat opens the app screen through the sheet", async () => {
    const user = userEvent.setup();
    const opened: string[] = [];
    renderWithProviders(
      <PanelSuggestion
        props={{ suggestion_id: 31 }}
        data={{ suggestion: SUGGESTION }}
        ctx={makeCtx({ onOpenPath: (p) => opened.push(p) })}
      />,
    );
    await user.click(screen.getByText("근거 보기"));
    await user.click(screen.getByRole("link", { name: "가짜 할 일 기록" }));
    await waitFor(() => expect(opened).toEqual(["/todos/"]));
  });

  it("read-only (offline): the buttons are off", () => {
    renderWithProviders(
      <PanelSuggestion
        props={{ suggestion_id: 31 }}
        data={{ suggestion: SUGGESTION }}
        ctx={makeCtx({ readOnly: true })}
      />,
    );
    expect(screen.getByRole("button", { name: "받기" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "버리기" })).toBeDisabled();
  });
});
