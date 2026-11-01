import { describe, expect, it } from "vitest";
import { registryNames } from "./registry";

// SP6 11.2: with only registry.tsx loaded (the first screen), the chat bundle's four are not there.
// Every test file has its own modules, so another file's registerChatParts() does not reach here.
describe("first-screen registry", () => {
  it("first-screen registry stays eleven", () => {
    expect(registryNames()).toHaveLength(11);
    for (const name of ["ui_date_choice", "ui_result", "ui_period_list", "ui_block", "ui_events", "ui_measure_confirm", "ui_panel_suggestion", "ui_full_diagnosis_chip"]) expect(registryNames()).not.toContain(name);
  });
});
