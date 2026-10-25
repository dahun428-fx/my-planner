import type { HiddenSensitive, HistoryChapter as ChapterData, HistoryEvent } from "../api/types.gen";
import { eventDateText, ladderText, yearsText } from "../lib/history";
import { AREA_LABELS, CURVE_TEXT, HISTORY_TEXT as T } from "../lib/labels";
import { MilestonePopover } from "./MilestonePopover";
import { Pictogram } from "./pictograms.gen";

/** One event line (52px or more): kind in a 36px circle, title, date, note, then its tags. Tapping opens the popover. */
function EventRow({
  event: e,
  open,
  onSelect,
  onClose,
  onHide,
}: {
  event: HistoryEvent;
  open: boolean;
  onSelect(e: HistoryEvent): void;
  onClose(): void;
  onHide?(): void;
}) {
  const kind = CURVE_TEXT.kinds[e.kind];
  return (
    <li className="history-event" data-event-id={e.id}>
      <div className="history-event-line">
      <button type="button" className="history-event-row" aria-expanded={open} onClick={() => (open ? onClose() : onSelect(e))}>
        <span className="history-kind">
          <Pictogram name={e.kind} size={20} />
        </span>
        <span className="history-event-body">
          <span className="history-event-top">
            <span className="history-event-title">{e.title}</span>
            <span className="meta num">
              {e.certainty === "estimate" && `${T.estimate} `}
              {eventDateText(e.date, e.precision)}
            </span>
          </span>
          {e.note && <span className="meta">{e.note}</span>}
          <span className="history-tags">
            <span className="tag">{e.kind_certainty === "estimate" ? T.kindEstimate(kind) : kind}</span>
            {e.area && (
              <span className="stat-name" data-area={e.area}>
                <Pictogram name={e.area} size={16} />
                {AREA_LABELS[e.area]}
              </span>
            )}
            {e.origin === "chat" && (
              <span className="tag history-assistant">
                <Pictogram name="assistant" size={16} />
                {T.assistantMade}
              </span>
            )}
            {e.sensitive && (
              <span className="tag">
                <Pictogram name="eye" size={16} />
                {T.sensitive}
              </span>
            )}
          </span>
        </span>
      </button>
      {e.sensitive && onHide && (
        <button type="button" className="text-button history-hide" onClick={onHide}>
          {T.hideAgain}
        </button>
      )}
      </div>
      {open && <MilestonePopover milestone={e} onClose={onClose} />}
    </li>
  );
}

/** "가려 둔 사건 {n}개 · {해들}" with "보기" (SP8 8.5): the count and years only, never a title. */
function HiddenLine({ hidden, onShow }: { hidden: HiddenSensitive; onShow(): void }) {
  return (
    <p className="meta history-hidden">
      <Pictogram name="eyeoff" size={16} />
      <span>{T.hidden(hidden.count, hidden.years)}</span>
      <button type="button" className="text-button" onClick={onShow}>
        {T.showHidden}
      </button>
    </p>
  );
}

/**
 * The events of one group, then the line for the sensitive ones kept hidden. A kind filter that leaves none says
 * so, so the way walked does not look cut. `onHide` folds an opened sensitive event's group again.
 */
export function HistoryEvents({
  events,
  filtered,
  selected,
  onSelect,
  onClose,
  hidden,
  onShow,
  onHide,
}: {
  events: HistoryEvent[];
  filtered: boolean;
  selected: number | null;
  onSelect(e: HistoryEvent): void;
  onClose(): void;
  hidden?: HiddenSensitive;
  onShow?(): void;
  onHide?(): void;
}) {
  return (
    <>
      {events.length === 0 ? (
        filtered && <p className="empty history-none">{T.noneOfKind}</p>
      ) : (
        <ul className="history-events">
          {events.map((e) => (
            <EventRow key={e.id} event={e} open={selected === e.id} onSelect={onSelect} onClose={onClose} onHide={onHide} />
          ))}
        </ul>
      )}
      {hidden && hidden.count > 0 && onShow && <HiddenLine hidden={hidden} onShow={onShow} />}
    </>
  );
}

/** The two lines under a chapter's title: the ladder it was remembered or recorded at, and the event count. */
function SecondLine({ chapter: c }: { chapter: ChapterData }) {
  return (
    <p className="meta history-caption">
      {c.ladder && (
        <>
          <Pictogram name="ladder" size={16} />
          {c.ladder.source === "remembered" ? T.ladderRemembered(ladderText(c.ladder.value)) : T.ladderRecorded(ladderText(c.ladder.value))}
          {" · "}
        </>
      )}
      {T.eventCount(c.events.length)}
    </p>
  );
}

/** A chapter of the way walked: a list on the paper, no box (SP8 8.3). `events` are the ones left after the filter. */
export function HistoryChapter({
  chapter: c,
  events,
  filtered,
  selected,
  onSelect,
  onClose,
  onShow,
  onHide,
}: {
  chapter: ChapterData;
  events: HistoryEvent[];
  filtered: boolean;
  selected: number | null;
  onSelect(e: HistoryEvent): void;
  onClose(): void;
  onShow(): void;
  onHide?(): void;
}) {
  const estimate = c.certainty === "estimate";
  const memo = c.sketch ?? (estimate ? T.estimateSketch : null);
  return (
    <section className="history-chapter" aria-labelledby={`history-chapter-${c.id}`} data-chapter-id={c.id}>
      <div className="history-chapter-head">
        <Pictogram name="chapter" size={20} />
        <h2 id={`history-chapter-${c.id}`} className="history-chapter-title">
          {c.title}
        </h2>
        <span className="meta num">{yearsText(c.start, c.end)}</span>
        {estimate && (
          <span className="tag">
            <Pictogram name="estimate" size={16} />
            {T.estimate}
          </span>
        )}
      </div>
      <SecondLine chapter={c} />
      {memo && <p className="history-memo">{memo}</p>}
      <HistoryEvents events={events} filtered={filtered} selected={selected} onSelect={onSelect} onClose={onClose} hidden={c.hidden_sensitive} onShow={onShow} onHide={onHide} />
    </section>
  );
}
