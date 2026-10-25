import type { HistoryFilter, HistoryOrder } from "../lib/history";
import { HISTORY_TEXT as T } from "../lib/labels";
import { Pictogram, type PictogramName } from "./pictograms.gen";

const FILTERS: Array<{ id: HistoryFilter; icon: PictogramName }> = [
  { id: "all", icon: "list" },
  { id: "high", icon: "high" },
  { id: "low", icon: "low" },
  { id: "turning_point", icon: "turning_point" },
];

/** 거르기 pills (one at a time, 44px) and the sort word button (SP8 8.3, 8.4). */
export function HistoryFilters({
  filter,
  order,
  onFilter,
  onOrder,
}: {
  filter: HistoryFilter;
  order: HistoryOrder;
  onFilter(f: HistoryFilter): void;
  onOrder(o: HistoryOrder): void;
}) {
  return (
    <div className="history-controls">
      <div className="tabs history-filters" role="group" aria-label={T.filterLabel}>
        {FILTERS.map((f) => (
          <button key={f.id} type="button" className="tab with-icon" aria-pressed={f.id === filter} onClick={() => onFilter(f.id)}>
            <Pictogram name={f.icon} size={16} />
            {T.filters[f.id]}
          </button>
        ))}
      </div>
      <button type="button" className="text-button" onClick={() => onOrder(order === "recent" ? "oldest" : "recent")}>
        {T.sort[order]}
      </button>
    </div>
  );
}
