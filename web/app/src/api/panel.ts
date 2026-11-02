import type { ApiResult } from "./client";
import type { LifeReportOut, LifeReports, OwnerStatements, PanelBudget, PanelSuggestions } from "./types.gen";
import { apiGetLate } from "./validateLate";

// SP15 12장: the life manager panel's reads. Late models (schema.late.json): import this file only
// from the chat and page chunks, never from api/client.ts or the first screen. Accepting and
// dismissing a suggestion go through POST /actions (usePartAction).

/** `GET /panel/suggestions`: newest first; `state` narrows it (the restored cards ask for `proposed`). */
export function getPanelSuggestions(
  state?: string,
): Promise<ApiResult<PanelSuggestions>> {
  return apiGetLate<PanelSuggestions>(
    `/panel/suggestions${state ? `?state=${encodeURIComponent(state)}` : ""}`,
    "PanelSuggestions",
  );
}

/** `GET /panel/budget`: this week's suggestions still to come (never the cap) and whether today's full diagnosis may run. */
export function getPanelBudget(): Promise<ApiResult<PanelBudget>> {
  return apiGetLate<PanelBudget>("/panel/budget", "PanelBudget");
}

/** `GET /life-reports`: the saved life reports, newest first (id and date only). */
export function getLifeReports(): Promise<ApiResult<LifeReports>> {
  return apiGetLate<LifeReports>("/life-reports", "LifeReports");
}

/** `GET /life-reports/{id}`: one report as saved (its scores are the copy from that day). */
export function getLifeReport(id: number): Promise<ApiResult<LifeReportOut>> {
  return apiGetLate<LifeReportOut>(`/life-reports/${id}`, "LifeReportOut");
}

/** `GET /owner-statements`: what I said that the panel may lean on, not retired, newest first. */
export function getOwnerStatements(): Promise<ApiResult<OwnerStatements>> {
  return apiGetLate<OwnerStatements>("/owner-statements", "OwnerStatements");
}
