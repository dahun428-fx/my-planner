import type { Zoom } from "./curveLayout";
import type { HistoryFilter, HistoryOrder } from "./history";

/**
 * What the life curve screen remembers while this tab has the dashboard open (SP3-4 13.4, SP8 8.4): module
 * memory, never storage. Leaving for another screen and coming back keeps it; a reload or a new tab starts over.
 * "민감한 사건 보기" is one state for the curve and the history tab.
 */
export const memory: { zoom: Zoom; sensitive: boolean; filter: HistoryFilter; order: HistoryOrder; expanded: Set<number> } = {
  zoom: "month",
  sensitive: false,
  filter: "all",
  order: "recent",
  expanded: new Set(),
};

/** For tests: start again as a fresh tab would. */
export function resetMemory() {
  memory.zoom = "month";
  memory.sensitive = false;
  memory.filter = "all";
  memory.order = "recent";
  memory.expanded = new Set();
}
