import { CURVE_TEXT } from "../lib/labels";
import { reviewDayLabel } from "../lib/reviews";

const T = CURVE_TEXT.upcoming;

export interface UpcomingMark {
  /** The review day, `YYYY-MM-DD` in Korea. */
  day: string;
  what: string;
}

/**
 * DU-05: the reviews that will start drawing an empty curve, each on its day ("10월 25일(일) 첫 사다리").
 * Only dates: no percentages, no countdown, no count of days.
 */
export function Upcoming({ marks }: { marks: UpcomingMark[] }) {
  if (marks.length === 0) return null;
  return (
    <ol className="upcoming" aria-label={T.label}>
      {marks.map((m) => (
        <li key={`${m.day} ${m.what}`} className="upcoming-mark">
          <time className="upcoming-day num" dateTime={m.day}>
            {reviewDayLabel(m.day)}
          </time>
          <span className="upcoming-what">{m.what}</span>
        </li>
      ))}
    </ol>
  );
}
