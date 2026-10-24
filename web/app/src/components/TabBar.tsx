import Link from "next/link";
import { copy } from "../lib/copy";
import { Icon } from "./icons";
import styles from "./TabBar.module.css";

export type TabName = "today" | "todos" | "activity" | "settings";

const TABS: { name: TabName; href: string }[] = [
  { name: "today", href: "/" },
  { name: "todos", href: "/todos/" },
  { name: "activity", href: "/activity/" },
  { name: "settings", href: "/settings/" },
];

// Spec 5.3: four bottom tabs; the current one is darker text only (no coloured pill).
export function TabBar({ current }: { current: TabName }) {
  return (
    <nav className={styles.bar} aria-label={copy.tabs.navLabel}>
      <ul className={styles.list}>
        {TABS.map(({ name, href }) => (
          <li key={name} className={styles.item}>
            <Link
              href={href}
              className={styles.tab}
              aria-current={name === current ? "page" : undefined}
            >
              <Icon name={name} />
              <span className={styles.label}>{copy.tabs[name]}</span>
            </Link>
          </li>
        ))}
      </ul>
    </nav>
  );
}
