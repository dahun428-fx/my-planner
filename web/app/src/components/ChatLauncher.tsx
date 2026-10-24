import { copy } from "../lib/copy";
import styles from "./ChatLauncher.module.css";

// Spec 5.3: the input-shaped button floating above the tab bar (the one thing in the app with a
// shadow). While the secretary cannot be reached it says so and cannot be pressed. A05 wires `onOpen`.
export function ChatLauncher({ disabled, offline = false, onOpen }: { disabled: boolean; offline?: boolean; onOpen(): void }) {
  return (
    <div className={styles.dock}>
      <button type="button" className={styles.launcher} disabled={disabled} onClick={onOpen}>
        {offline ? copy.offline.chatLater : copy.chat.launcher}
      </button>
    </div>
  );
}
