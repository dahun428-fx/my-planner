import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { copy } from "../../lib/copy";
import { makeCtx, serveActions } from "../../test/parts";
import { renderWithProviders } from "../../test/render";
import { MeasureConfirm, type MeasureConfirmProps } from "./MeasureConfirm";

// The fake person of the SP13 plan (Task 3): an inbody sheet read from a photo.
const props: MeasureConfirmProps = {
  rows: [
    { metric: "weight_kg", label: "몸무게", value: 72.4, unit: "kg", measured_on: "2026-10-30" },
    { metric: "body_fat_pct", label: "체지방률", value: 19.0, unit: "%", measured_on: "2026-10-30" },
    { metric: "smoking", label: "흡연", value: "quit", unit: null, measured_on: "2026-10-30" },
  ],
  source_kind: "photo",
  source_ref: "photo:12",
};
const saved = "✓ 측정값 2개 저장 · 건강 위치 70→72"; // taste-skill-ignore: BE confirmation prefix, not UI

describe("MeasureConfirm (SP13 6.5)", () => {
  it("edits a value, drops a row and saves the rest", async () => {
    const bodies = serveActions(() => HttpResponse.json({ status: "applied", activity_id: 40, undo_id: 40, result: { ids: [1, 2] }, confirmation: saved }));
    const ctx = makeCtx();
    renderWithProviders(<MeasureConfirm props={props} ctx={ctx} />);
    expect(screen.getByRole("heading", { name: "측정값 확인" })).toBeInTheDocument();
    const weight = screen.getByRole("spinbutton", { name: "몸무게 값" });
    await userEvent.clear(weight);
    await userEvent.type(weight, "71.8");
    await userEvent.click(screen.getByRole("button", { name: "체지방률 빼기" }));
    expect(screen.queryByRole("spinbutton", { name: "체지방률 값" })).toBeNull();
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "흡연 값" }), "none");
    await userEvent.click(screen.getByRole("button", { name: copy.parts.save }));
    await waitFor(() => expect(bodies).toHaveLength(1));
    expect(bodies[0]).toMatchObject({
      action: "save_measures",
      args: {
        rows: [
          { metric: "weight_kg", value: 71.8, measured_on: "2026-10-30" },
          { metric: "smoking", value: "none", measured_on: "2026-10-30" },
        ],
        source_kind: "photo",
        source_ref: "photo:12",
      },
    });
    // After: the confirmation in the card, everything read-only (as ui_confirm once done).
    expect(await screen.findAllByText(saved)).not.toHaveLength(0);
    await waitFor(() => expect(ctx.onAfterAction).toHaveBeenCalled());
    expect(screen.getByRole("button", { name: copy.parts.save })).toBeDisabled();
    expect(screen.getByRole("spinbutton", { name: "몸무게 값" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "몸무게 빼기" })).toBeDisabled();
  });

  it("the date can be changed", async () => {
    const bodies = serveActions();
    renderWithProviders(<MeasureConfirm props={{ ...props, rows: props.rows.slice(0, 1) }} ctx={makeCtx()} />);
    const date = screen.getByLabelText("몸무게 측정일");
    await userEvent.clear(date);
    await userEvent.type(date, "2026-10-29");
    await userEvent.click(screen.getByRole("button", { name: copy.parts.save }));
    await waitFor(() => expect(bodies).toHaveLength(1));
    expect((bodies[0].args as { rows: object[] }).rows).toEqual([{ metric: "weight_kg", value: 72.4, measured_on: "2026-10-29" }]);
  });

  it("no rows left: save is off", async () => {
    renderWithProviders(<MeasureConfirm props={{ ...props, rows: props.rows.slice(0, 1) }} ctx={makeCtx()} />);
    expect(screen.getByRole("button", { name: copy.parts.save })).toBeEnabled();
    await userEvent.click(screen.getByRole("button", { name: "몸무게 빼기" }));
    expect(screen.getByRole("button", { name: copy.parts.save })).toBeDisabled();
  });

  it("an empty number turns save off", async () => {
    renderWithProviders(<MeasureConfirm props={{ ...props, rows: props.rows.slice(0, 1) }} ctx={makeCtx()} />);
    await userEvent.clear(screen.getByRole("spinbutton", { name: "몸무게 값" }));
    expect(screen.getByRole("button", { name: copy.parts.save })).toBeDisabled();
  });

  it("a face score row carries the ±10 note", () => {
    const face = { metric: "face_rating", label: "얼굴 평가(참고)", value: 55, unit: "점", measured_on: "2026-10-30" };
    renderWithProviders(<MeasureConfirm props={{ ...props, rows: [...props.rows, face] }} ctx={makeCtx()} />);
    expect(screen.getByText("얼굴 점수는 조명·각도·취향에 따라 ±10 흔들려요.")).toBeInTheDocument();
  });

  it("no face score: no note", () => {
    renderWithProviders(<MeasureConfirm props={props} ctx={makeCtx()} />);
    expect(screen.queryByText(/얼굴 점수는/)).toBeNull();
  });

  it("money rows show 만 원 under the input", () => {
    const salary = { metric: "salary_krw", label: "연봉(세전)", value: 55_000_000, unit: "원", measured_on: "2026-10-30" };
    renderWithProviders(<MeasureConfirm props={{ ...props, rows: [salary] }} ctx={makeCtx()} />);
    expect(screen.getByText("5,500만 원")).toBeInTheDocument();
  });

  it("read only disables every control", () => {
    renderWithProviders(<MeasureConfirm props={props} ctx={makeCtx({ readOnly: true })} />);
    for (const el of [...screen.getAllByRole("button"), ...screen.getAllByRole("spinbutton"), screen.getByRole("combobox")]) expect(el).toBeDisabled();
    expect(screen.getByText(copy.offline.writeLater)).toBeInTheDocument();
  });
});
