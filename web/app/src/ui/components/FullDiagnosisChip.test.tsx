import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";
import healthJson from "../../test/fixtures/health.json";
import { makeCtx } from "../../test/parts";
import { renderWithProviders } from "../../test/render";
import { BASE, server } from "../../test/server";
import { FullDiagnosisChip } from "./FullDiagnosisChip";

// SP15 10장, D3: the chip after a quarterly review. It runs only on a press: no POST /chat before.
function serve({
  features = ["mate", "manager"],
  ok = true,
}: { features?: string[]; ok?: boolean } = {}) {
  const seen = { chat: 0, budget: 0 };
  server.use(
    http.get(`${BASE}/health`, () =>
      HttpResponse.json({ ...healthJson, features }),
    ),
    http.get(`${BASE}/panel/budget`, () => {
      seen.budget += 1;
      return HttpResponse.json({ remaining: 1, full_diagnosis_ok: ok });
    }),
    http.post(`${BASE}/chat`, () => {
      seen.chat += 1;
      return HttpResponse.json({});
    }),
  );
  return seen;
}

const props = { period: "2026-Q3" };

describe("FullDiagnosisChip (SP15 10장)", () => {
  it("a press turns the sheet to the life manager with the full diagnosis chip, once", async () => {
    const seen = serve();
    const switchAgent = vi.fn(() => true);
    const user = userEvent.setup();
    renderWithProviders(
      <FullDiagnosisChip props={props} ctx={makeCtx({ switchAgent })} />,
    );
    const button = await screen.findByRole("button", {
      name: "전체 진단 해 볼까요?",
    });
    await waitFor(() => expect(seen.budget).toBe(1));
    expect(seen.chat).toBe(0); // nothing runs by itself
    expect(switchAgent).not.toHaveBeenCalled();
    await user.click(button);
    await user.click(button);
    expect(switchAgent).toHaveBeenCalledTimes(1);
    expect(switchAgent).toHaveBeenCalledWith("manager", "manager_full");
    expect(seen.chat).toBe(0); // the sheet sends it, not the card
  });

  it("a press the sheet does not take (an answer still coming) leaves the card pressable", async () => {
    serve();
    const switchAgent = vi.fn(() => false);
    const user = userEvent.setup();
    renderWithProviders(
      <FullDiagnosisChip props={props} ctx={makeCtx({ switchAgent })} />,
    );
    const button = await screen.findByRole("button", {
      name: "전체 진단 해 볼까요?",
    });
    await user.click(button);
    expect(button).toBeEnabled();
    switchAgent.mockReturnValue(true);
    await user.click(button);
    expect(button).toBeDisabled();
    expect(switchAgent).toHaveBeenCalledTimes(2);
  });

  it("already done today: says so and cannot be pressed", async () => {
    serve({ ok: false });
    const switchAgent = vi.fn();
    const user = userEvent.setup();
    renderWithProviders(
      <FullDiagnosisChip props={props} ctx={makeCtx({ switchAgent })} />,
    );
    const button = await screen.findByRole("button", {
      name: "오늘은 이미 했어요",
    });
    expect(button).toBeDisabled();
    await user.click(button);
    expect(switchAgent).not.toHaveBeenCalled();
  });

  it("without switchAgent (the check-in screen) it is text, no button", async () => {
    serve();
    renderWithProviders(
      <FullDiagnosisChip props={props} ctx={makeCtx({ where: "checkin" })} />,
    );
    expect(await screen.findByText("전체 진단 해 볼까요?")).toBeInTheDocument();
    expect(screen.queryByRole("button")).toBeNull();
  });

  it.each([
    ["a BE without the life manager", { features: ["mate"] }, {}],
    ["a restored card", {}, { restored: true }],
  ])("read-only for %s", async (_name, opts, over) => {
    serve(opts);
    const switchAgent = vi.fn();
    renderWithProviders(
      <FullDiagnosisChip
        props={props}
        ctx={makeCtx({ switchAgent, ...over })}
      />,
    );
    expect(await screen.findByText("전체 진단 해 볼까요?")).toBeInTheDocument();
    await new Promise((r) => setTimeout(r, 50));
    expect(screen.queryByRole("button")).toBeNull();
  });
});
