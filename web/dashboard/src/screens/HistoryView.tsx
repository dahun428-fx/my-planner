import { useCallback, useState } from "react";
import type { CurveHistory, HistoryEvent } from "../api/types.gen";
import { HistoryChapter, HistoryEvents } from "../components/HistoryChapter";
import { HistoryFilters } from "../components/HistoryFilters";
import { collapsedOnPhone, filterEvents, orderChapters, yearsText, type HistoryFilter, type HistoryOrder } from "../lib/history";
import { memory } from "../lib/curveMemory";
import { HISTORY_TEXT as T } from "../lib/labels";

/**
 * 히스토리 탭 (SP8 8.3, 8.4): the chapters as a list on the paper, newest first or oldest first, events
 * filtered by kind in the browser. Filter, sort and which folded chapters were opened live in module memory
 * (never storage). `isPhone` folds all but the newest four chapters.
 */
export function HistoryView({ history: h, isPhone }: { history: CurveHistory; isPhone: boolean }) {
  const [filter, setFilterState] = useState<HistoryFilter>(memory.filter);
  const [order, setOrderState] = useState<HistoryOrder>(memory.order);
  const [expanded, setExpanded] = useState<Set<number>>(memory.expanded);
  const [selectedId, setSelectedId] = useState<number | null>(null);

  const setFilter = (f: HistoryFilter) => {
    memory.filter = f;
    setFilterState(f);
  };
  const setOrder = (o: HistoryOrder) => {
    memory.order = o;
    setOrderState(o);
  };
  const expand = (id: number) => {
    const next = new Set(expanded).add(id);
    memory.expanded = next;
    setExpanded(next);
  };
  const select = useCallback((e: HistoryEvent) => setSelectedId(e.id), []);
  const close = useCallback(() => {
    setSelectedId((id) => {
      if (id !== null) document.querySelector<HTMLButtonElement>(`.history-event[data-event-id="${id}"] .history-event-row`)?.focus();
      return null;
    });
  }, []);

  const folded = isPhone ? collapsedOnPhone(h.chapters, expanded) : new Set<number>();
  const items = orderChapters(h, order);
  const nothing = h.chapters.length === 0 && h.unassigned.events.length === 0;
  const narrowed = filter !== "all";
  const pick = (events: HistoryEvent[]) => {
    const kept = filterEvents(events, filter);
    return order === "recent" ? kept : [...kept].reverse();
  };

  return (
    <section className="history" aria-label={T.tabs.history}>
      <p className="meta history-subtitle">{T.subtitle(h.summary.chapters, h.summary.events, h.since_year)}</p>
      <HistoryFilters filter={filter} order={order} onFilter={setFilter} onOrder={setOrder} />
      {nothing ? (
        <p className="empty">{T.empty}</p>
      ) : (
        items.map((item) => {
          if (item === "unassigned") {
            return (
              <section key="unassigned" className="history-chapter" aria-labelledby="history-unassigned">
                <div className="history-chapter-head">
                  <h2 id="history-unassigned" className="history-chapter-title">
                    {T.unassigned}
                  </h2>
                </div>
                <HistoryEvents events={pick(h.unassigned.events)} filtered={narrowed} selected={selectedId} onSelect={select} onClose={close} />
              </section>
            );
          }
          if (folded.has(item.id)) {
            return (
              <div key={item.id} className="history-chapter history-folded">
                <button type="button" className="text-button" aria-expanded="false" onClick={() => expand(item.id)}>
                  {T.more(item.title, yearsText(item.start, item.end))}
                </button>
              </div>
            );
          }
          return <HistoryChapter key={item.id} chapter={item} events={pick(item.events)} filtered={narrowed} selected={selectedId} onSelect={select} onClose={close} />;
        })
      )}
    </section>
  );
}

export default HistoryView;
