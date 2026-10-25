import { Icon } from "../components/icons";
import { copy } from "../lib/copy";
import type { Chip } from "./quickChips";
import styles from "./QuickChips.module.css";

// SP9 9.5 퀵 칩 줄: 입력창 바로 위, 가로로 밀기, 칩 = 작은 아이콘 + 라벨(높이 32px, 누르는 곳 44px). 누르면 정해진
// 문장을 내 말로 보낸다. 읽기 전용(오프라인, 답 오는 중)이면 흐리게, 누를 수 없다.
export function QuickChips({ chips, disabled, onSend }: { chips: readonly Chip[]; disabled: boolean; onSend(chip: Chip): void }) {
  return (
    <div className={styles.row} role="group" aria-label={copy.chat.chipsLabel}>
      {chips.map((c) => (
        <button key={c.key} type="button" className={`${styles.chip} pressable`} disabled={disabled} onClick={() => onSend(c)}>
          <span className={styles.mark} aria-hidden="true">
            <Icon name={c.icon} />
          </span>
          {c.label}
        </button>
      ))}
    </div>
  );
}
