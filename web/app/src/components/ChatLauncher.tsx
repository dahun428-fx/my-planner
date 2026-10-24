import { useId } from "react";
import { copy } from "../lib/copy";
import styles from "./ChatLauncher.module.css";

/** The line under a launcher that cannot be pressed because the BE refuses (401, 429, 503). */
export function launcherReason(kind: string | undefined): string | null {
  return kind === "unauthorized" || kind === "rate_limited" || kind === "safe_mode" ? copy.chat.launcherBlocked[kind] : null;
}

// Spec 5.3: the input-shaped button floating above the tab bar. While the secretary cannot be
// reached it says so and cannot be pressed; when it is blocked (401, 429, 503) a line says why.
export function ChatLauncher({
  disabled,
  offline = false,
  reason,
  onOpen,
}: {
  disabled: boolean;
  offline?: boolean;
  reason?: string | null;
  onOpen(): void;
}) {
  const reasonId = useId();
  const why = !offline && disabled && reason ? reason : null;
  return (
    <div className={styles.dock}>
      {why && (
        <p id={reasonId} className={styles.reason}>
          {why}
        </p>
      )}
      <button type="button" className={`${styles.launcher} pressable`} disabled={disabled} aria-describedby={why ? reasonId : undefined} onClick={onOpen}>
        {offline ? copy.offline.chatLater : copy.chat.launcher}
      </button>
    </div>
  );
}
