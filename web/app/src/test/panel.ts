import { http, HttpResponse } from "msw";
import type { OwnerStatementOut, PanelSuggestionOut } from "../api/types.gen";
import { BASE, server } from "./server";

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

// SP15 5.4: the more screen's "내가 한 말" list (made-up values only).
export const STATEMENTS: OwnerStatementOut[] = [
  { id: 5, kind: "decision", area: "career", text: "가짜 결정: 올해는 이직보다 지금 팀이 먼저예요", created_at: "2026-10-30T03:00:00Z" },
  { id: 4, kind: "preference", area: null, text: "가짜 성향: 아침보다 저녁이 편해요", created_at: "2026-10-12T03:00:00Z" },
];

export function serveStatements(items: OwnerStatementOut[] = STATEMENTS) {
  let list = items;
  const reads: number[] = [];
  server.use(http.get(`${BASE}/owner-statements`, () => (reads.push(list.length), HttpResponse.json({ items: list }))));
  return {
    reads,
    drop(id: number) {
      list = list.filter((s) => s.id !== id);
    },
  };
}
