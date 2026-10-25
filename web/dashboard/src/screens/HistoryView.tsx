import { useCallback, useMemo, useState, type ReactNode } from "react";
import type { CurveHistory, HistoryEvent } from "../api/types.gen";
import { GlanceStrip } from "../components/GlanceStrip";
import { HistoryChapter, HistoryEvents } from "../components/HistoryChapter";
import { HistoryFilters } from "../components/HistoryFilters";
import { HistorySummary } from "../components/HistorySummary";
import { applySensitive, collapsedOnPhone, filterEvents, orderChapters, UNASSIGNED_ID, yearsText, type HistoryFilter, type HistoryOrder } from "../lib/history";
import { memory } from "../lib/curveMemory";
import { HISTORY_TEXT as T } from "../lib/labels";
import { useWidth } from "../lib/useWidth";

/**
 * 히스토리 탭 (SP8 8.3 to 8.6): the chapters as a list on the paper, newest first or oldest first, events
 * filtered by kind in the browser, the glance strip and the side summary. Filter, sort, which folded chapters
 * were opened and which chapters had their hidden events shown live in module memory (never storage).
 * `isPhone` folds all but the newest four chapters and puts the summary after the list; wider, the strip and
 * the summary are a column at the side.
 *
 * `history` may hold sensitive events (the page asked for them); only those of an opened chapter, or all while
 * "민감한 사건 가림" is off, are shown, drawn or counted. `onNeedSensitive` asks the page to fetch them;
 * `onDropSensitive` tells it nothing is open any more, so it can let go of them.
 */
export function HistoryView({
  history,
  isPhone,
  onNeedSensitive,
  onDropSensitive,
}: {
  history: CurveHistory;
  isPhone: boolean;
  onNeedSensitive?: () => void;
  onDropSensitive?: () => void;
}) {
  const [filter, setFilterState] = useState<HistoryFilter>(memory.filter);
  const [order, setOrderState] = useState<HistoryOrder>(memory.order);
  const [foldedOpened, setFoldedOpened] = useState<Set<number>>(memory.foldedOpened);
  const [sensitiveOpened, setSensitiveOpened] = useState<Set<number>>(memory.sensitiveOpened);
  const [showAll, setShowAllState] = useState(memory.sensitive);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const glance = useWidth<HTMLDivElement>();

  const h = useMemo(() => applySensitive(history, sensitiveOpened, showAll), [history, sensitiveOpened, showAll]);

  const setFilter = (f: HistoryFilter) => {
    memory.filter = f;
    setFilterState(f);
  };
  const setOrder = (o: HistoryOrder) => {
    memory.order = o;
    setOrderState(o);
  };
  const openFolded = (id: number) => {
    const next = new Set(foldedOpened).add(id);
    memory.foldedOpened = next;
    setFoldedOpened(next);
  };
  const showHidden = (id: number) => {
    const next = new Set(sensitiveOpened).add(id);
    memory.sensitiveOpened = next;
    setSensitiveOpened(next);
    onNeedSensitive?.();
  };
  const hideAgain = (id: number) => {
    const next = new Set(sensitiveOpened);
    next.delete(id);
    memory.sensitiveOpened = next;
    setSensitiveOpened(next);
    setSelectedId(null);
    if (next.size === 0 && !showAll) onDropSensitive?.();
  };
  const hideSensitive = (hide: boolean) => {
    memory.sensitive = !hide;
    setShowAllState(!hide);
    if (!hide) {
      onNeedSensitive?.();
      return;
    }
    // hiding again folds every chapter, also the ones opened one by one
    const none = new Set<number>();
    memory.sensitiveOpened = none;
    setSensitiveOpened(none);
    setSelectedId(null);
    onDropSensitive?.();
  };
  const select = useCallback((e: HistoryEvent) => setSelectedId(e.id), []);
  const close = useCallback(() => {
    setSelectedId((id) => {
      if (id !== null) document.querySelector<HTMLButtonElement>(`.history-event[data-event-id="${id}"] .history-event-row`)?.focus();
      return null;
    });
  }, []);

  const folded = isPhone ? collapsedOnPhone(h.chapters, foldedOpened) : new Set<number>();
  const items = orderChapters(h, order);
  const nothing = h.chapters.length === 0 && h.unassigned.events.length === 0 && h.unassigned.hidden_sensitive.count === 0;
  const narrowed = filter !== "all";
  const pick = (events: HistoryEvent[]) => {
    const kept = filterEvents(events, filter);
    return order === "recent" ? kept : [...kept].reverse();
  };

  const strip = (
    <div ref={glance.ref}>
      <GlanceStrip history={h} width={glance.width} />
    </div>
  );
  const filters = <HistoryFilters filter={filter} order={order} onFilter={setFilter} onOrder={setOrder} hideSensitive={!showAll} onHideSensitive={hideSensitive} />;
  const list = nothing ? (
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
            <HistoryEvents
              events={pick(h.unassigned.events)}
              filtered={narrowed}
              selected={selectedId}
              onSelect={select}
              onClose={close}
              hidden={h.unassigned.hidden_sensitive}
              onShow={() => showHidden(UNASSIGNED_ID)}
              onHide={showAll ? undefined : () => hideAgain(UNASSIGNED_ID)}
            />
          </section>
        );
      }
      if (folded.has(item.id)) {
        return (
          <div key={item.id} className="history-chapter history-folded">
            <button type="button" className="text-button" aria-expanded="false" onClick={() => openFolded(item.id)}>
              {T.more(item.title, yearsText(item.start, item.end))}
            </button>
          </div>
        );
      }
      return (
        <HistoryChapter
          key={item.id}
          chapter={item}
          events={pick(item.events)}
          filtered={narrowed}
          selected={selectedId}
          onSelect={select}
          onClose={close}
          onShow={() => showHidden(item.id)}
          onHide={showAll ? undefined : () => hideAgain(item.id)}
        />
      );
    })
  );
  const summary = <HistorySummary summary={h.summary} />;

  const body: ReactNode = isPhone ? (
    <>
      {strip}
      {filters}
      {list}
      {summary}
    </>
  ) : (
    <div className="history-layout">
      <div className="history-main">
        {filters}
        {list}
      </div>
      <aside className="history-side" aria-label={T.summary.asideLabel}>
        {strip}
        {summary}
      </aside>
    </div>
  );

  return (
    <section className="history" aria-label={T.tabs.history}>
      <p className="meta history-subtitle">{T.subtitle(h.summary.chapters, h.summary.events, h.since_year)}</p>
      {body}
    </section>
  );
}

export default HistoryView;
