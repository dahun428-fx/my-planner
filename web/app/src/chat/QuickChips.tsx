import { Icon } from "../components/icons";
import { Pictogram } from "../components/pictograms.gen";
import { copy } from "../lib/copy";
import { type Chip, isWriteKey } from "./quickChips";
import styles from "./QuickChips.module.css";

// SP9 9.5 퀵 칩 줄: 입력창 바로 위, 가로로 밀기, 칩 = 작은 아이콘 + 라벨(높이 32px, 누르는 곳 44px). 누르면 정해진
// 문장을 내 말로 보낸다. 읽기 전용(오프라인, 답 오는 중)이면 흐리게, 누를 수 없다.
/** 한 줄 쓰기 표시의 글: 입력창이 `aria-describedby`로 가리킨다(시트에 하나뿐). */
export const WRITING_ID = "chat-writing";

// SP9c 3: 한 줄 쓰기 중(`writing`)에는 줄 대신 그 자리에 작은 표시(종류 아이콘 + 머리표 + 닫기 버튼)가 선다.
export function QuickChips({
  chips,
  disabled,
  writing = null,
  onPress,
  onCloseWrite,
}: {
  chips: readonly Chip[];
  disabled: boolean;
  writing?: Chip | null;
  onPress(chip: Chip): void;
  onCloseWrite?(): void;
}) {
  if (writing && isWriteKey(writing.key)) {
    return (
      <div className={styles.writing}>
        <span className={styles.mark} aria-hidden="true">
          <Icon name={writing.icon} />
        </span>
        <span id={WRITING_ID} className={styles.writingLabel}>{copy.chat.chipLabel[writing.key]}</span>
        <button type="button" className={styles.closeWrite} aria-label={copy.chat.closeWrite} onClick={onCloseWrite}>
          <Icon name="close" />
        </button>
      </div>
    );
  }
  return (
    <div className={styles.row} role="group" aria-label={copy.chat.chipsLabel}>
      {chips.map((c) => (
        <button key={c.key} type="button" className={`${styles.chip} pressable`} disabled={disabled || c.disabled === true} onClick={() => onPress(c)}>
          <span className={styles.mark} aria-hidden="true">
            {c.pictogram ? <Pictogram name={c.pictogram} size={16} /> : <Icon name={c.icon} />}
          </span>
          {c.label}
        </button>
      ))}
    </div>
  );
}
