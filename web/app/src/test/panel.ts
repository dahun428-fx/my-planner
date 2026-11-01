import type { PanelSuggestionOut } from "../api/types.gen";

// Made-up values (global constraints): no real record.
export const SUGGESTION: PanelSuggestionOut = {
  id: 31,
  kind: "habit",
  title: "가짜 산책 습관",
  area: "health",
  size_min: 20,
  per_week: 3,
  due_hint: null,
  experts: ["health", "psych"],
  evidence: [
    { type: "record", ref: "task:7", note: "가짜 할 일 기록", href: "/todos/" },
    {
      type: "statement",
      ref: "statement:2",
      note: "가짜로 한 말",
      href: "/more/statements/",
    },
    {
      type: "external",
      ref: "bench:health.steps",
      note: "가짜 외부 기준",
      href: null,
    },
  ],
  state: "proposed",
  week: "2026-W44",
  created_at: "2026-10-27T01:00:00Z",
};
