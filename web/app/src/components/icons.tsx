import styles from "./icons.module.css";

export type IconName = "today" | "todos" | "activity" | "settings" | "plus" | "check" | "chevron" | "close" | "send" | "schedule" | "memo" | "more";

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
};

const STROKE: Partial<Record<IconName, string>> = { schedule: "1.75", memo: "1.75", more: "1.75" };

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
        <path key={d} d={d} />
      ))}
    </svg>
  );
}

type NamedIconProps = { label?: string };
/** SP9 9.1: the more screen's button (and later tickets' tabs) use these by name. */
export const IconMore = (p: NamedIconProps) => <Icon name="more" {...p} />;
export const IconSchedule = (p: NamedIconProps) => <Icon name="schedule" {...p} />;
export const IconMemo = (p: NamedIconProps) => <Icon name="memo" {...p} />;
