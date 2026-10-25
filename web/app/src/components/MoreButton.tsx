import Link from "next/link";
import { copy } from "../lib/copy";
import { IconMore } from "./icons";
import styles from "./MoreButton.module.css";

// SP9 9.1: the same round 32px button at the right of every tab's large title, to /more/.
export function MoreButton() {
  return (
    <Link href="/more/" className={`${styles.more} pressable`} aria-label={copy.more.title}>
      <IconMore />
    </Link>
  );
}
