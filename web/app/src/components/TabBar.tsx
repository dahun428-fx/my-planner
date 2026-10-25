import Link from "next/link";
import { copy } from "../lib/copy";
import { Icon, type IconName } from "./icons";
import styles from "./TabBar.module.css";

export type TabName = "today" | "todos" | "memos" | "settings";

// SP9 9.1: memos took the activity slot in SP9-04 (activity moved under the more screen); the
// schedule tab replaces settings in SP9-07.
const TABS: { name: TabName; href: string; icon: IconName }[] = [
  { name: "today", href: "/", icon: "today" },
  { name: "todos", href: "/todos/", icon: "todos" },
  { name: "memos", href: "/memos/", icon: "memo" },
  { name: "settings", href: "/settings/", icon: "settings" },
];

// Spec 5.3: four bottom tabs; the current one is darker text only (no coloured pill). Without
// `current` (the more screen and the screens under it, SP9 9.1) no tab is marked.
export function TabBar({ current }: { current?: TabName }) {
  return (
    <nav className={styles.bar} aria-label={copy.tabs.navLabel}>
      <ul className={styles.list}>
        {TABS.map(({ name, href, icon }) => (
          <li key={name} className={styles.item}>
            <Link
              href={href}
              className={styles.tab}
              aria-current={name === current ? "page" : undefined}
            >
              <Icon name={icon} />
              <span className={styles.label}>{copy.tabs[name]}</span>
            </Link>
          </li>
        ))}
      </ul>
    </nav>
  );
}
