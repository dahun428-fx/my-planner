import styles from "./icons.module.css";

export type IconName = "today" | "todos" | "activity" | "settings" | "plus" | "check" | "chevron" | "close" | "send" | "schedule" | "memo" | "more" | "list" | "compose" | "stop" | "clear" | "camera" | "photo";

// Hand-drawn 24px icons, 1.7px stroke, currentColor (spec 4.3). SP9 9.1's three (schedule, memo,
// more) follow the SP8 pictogram rule: 24px, 1.75 stroke, round ends, no emoji.
const PATHS: Record<IconName, string[]> = {
  today: ["M4 6.5h16v13H4z", "M4 10.5h16", "M8.5 4v4", "M15.5 4v4"],
  todos: ["M9 7h11", "M9 12h11", "M9 17h11", "M4 7l1 1 2-2", "M4 12l1 1 2-2", "M4 17l1 1 2-2"],
  activity: ["M12 4a8 8 0 1 0 8 8", "M12 8v4l3 2", "M17 4.5l3 .5-.5 3"],
  settings: [
    "M12 9a3 3 0 1 0 0 6 3 3 0 0 0 0-6z",
    "M12 3v2.5M12 18.5V21M3 12h2.5M18.5 12H21M5.6 5.6l1.8 1.8M16.6 16.6l1.8 1.8M5.6 18.4l1.8-1.8M16.6 7.4l1.8-1.8",
  ],
  plus: ["M12 5v14", "M5 12h14"],
  check: ["M5 12.5l4.5 4.5L19 7.5"],
  chevron: ["M9.5 6l6 6-6 6"],
  close: ["M6 6l12 12", "M18 6L6 18"],
  send: ["M12 19V5", "M6 11l6-6 6 6"],
  // A clock face: the time-bound plans (SP9 9.2).
  schedule: ["M12 4a8 8 0 1 0 0 16 8 8 0 0 0 0-16z", "M12 8v4l2.5 2"],
  // A page with a folded corner and two lines (SP9 9.4).
  memo: ["M6.5 4h8l3 3v13h-11z", "M14.5 4v3h3", "M9.5 11.5h5", "M9.5 15h3.5"],
  // Three dots in a row (SP9 9.1).
  more: [
    "M6.5 10.75a1.25 1.25 0 1 0 0 2.5 1.25 1.25 0 0 0 0-2.5z",
    "M12 10.75a1.25 1.25 0 1 0 0 2.5 1.25 1.25 0 0 0 0-2.5z",
    "M17.5 10.75a1.25 1.25 0 1 0 0 2.5 1.25 1.25 0 0 0 0-2.5z",
  ],
  // SP9 9.5, the chat sheet's head: the conversation list (three lines with a dot each) and a new
  // conversation (a page with a pencil). Same pictogram rule as the three above.
  list: ["M9.5 7h10", "M9.5 12h10", "M9.5 17h10", "M5 7h.01", "M5 12h.01", "M5 17h.01"],
  compose: ["M11 5H6.5A1.5 1.5 0 0 0 5 6.5v11A1.5 1.5 0 0 0 6.5 19h11a1.5 1.5 0 0 0 1.5-1.5V13", "M16.5 4.5l3 3L12 15H9v-3z"],
  // A filled square: stop the answer that is coming (the chat's send button while busy). Same pictogram rule.
  stop: ["M8 8h8v8H8z"],
  // A small ×: empty the chat field (smaller than `close`, it sits inside the field). Same pictogram rule.
  clear: ["M8 8l8 8", "M16 8l-8 8"],
  // SP10 7.5, the chat's two photo buttons. A camera body with its lens: take one now.
  camera: [
    "M4 8.5A1.5 1.5 0 0 1 5.5 7H8l1.5-2h5L16 7h2.5A1.5 1.5 0 0 1 20 8.5v9a1.5 1.5 0 0 1-1.5 1.5h-13A1.5 1.5 0 0 1 4 17.5z",
    "M12 9.5a3.5 3.5 0 1 0 0 7 3.5 3.5 0 0 0 0-7z",
  ],
  // A picture with a hill and the sun: pick from the library. Same pictogram rule.
  photo: [
    "M5.5 5h13A1.5 1.5 0 0 1 20 6.5v11a1.5 1.5 0 0 1-1.5 1.5h-13A1.5 1.5 0 0 1 4 17.5v-11A1.5 1.5 0 0 1 5.5 5z",
    "M4 16l4.5-4.5 4 4 2.5-2.5L20 18",
    "M15.5 8a1.25 1.25 0 1 0 0 2.5 1.25 1.25 0 0 0 0-2.5z",
  ],
};

const STROKE: Partial<Record<IconName, string>> = { schedule: "1.75", memo: "1.75", more: "1.75", list: "1.75", compose: "1.75", stop: "1.75", clear: "1.75", camera: "1.75", photo: "1.75" };
// Drawn filled as well as stroked (the stroke's round joins round its corners).
const FILLED: Partial<Record<IconName, true>> = { stop: true };

export function Icon({ name, label }: { name: IconName; label?: string }) {
  return (
    <svg
      className={styles.icon}
      width="24"
      height="24"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={STROKE[name] ?? "1.7"}
      strokeLinecap="round"
      strokeLinejoin="round"
      role={label ? "img" : undefined}
      aria-label={label}
      aria-hidden={label ? undefined : true}
      focusable="false"
    >
      {PATHS[name].map((d) => (
        <path key={d} d={d} fill={FILLED[name] ? "currentColor" : undefined} />
      ))}
    </svg>
  );
}

type NamedIconProps = { label?: string };
/** SP9 9.1: the more screen's button (and later tickets' tabs) use these by name. */
export const IconMore = (p: NamedIconProps) => <Icon name="more" {...p} />;
export const IconSchedule = (p: NamedIconProps) => <Icon name="schedule" {...p} />;
export const IconMemo = (p: NamedIconProps) => <Icon name="memo" {...p} />;
