import type { EventItem } from "../../api/types.gen";
import { RepeatMark } from "../../components/RepeatMark";
import { copy } from "../../lib/copy";
import { clockOf, dayName } from "../../lib/schedule";
import styles from "../chat/cards.module.css";
import type { PartProps } from "../types";
import { Part } from "./Part";

type Props = { items: EventItem[] };

// SP9 9.8 완성 카드 `ui_events`: 그날 일정 1~10개(시각, 제목, 영역 점, 반복 표시). 날마다 작은 머리 아래 줄.
// 줄을 누르면 스케줄 탭의 그날로 간다(채팅 시트는 닫힌다). 갈 곳이 없는 자리(체크인 상세)에서는 읽기만.
// 고정 카드가 될 수 없어(BE PINNABLE_COMPONENTS) 채팅 묶음과 함께 레지스트리에 든다.
export function Events({ props, ctx }: PartProps<Props>) {
  const days = [...new Set(props.items.map((e) => e.date))];
  const open = ctx.onOpenPath;
  return (
    <Part>
      <div className={styles.period}>
        {days.map((d) => (
          <div key={d} className={styles.dayGroup}>
            <p className={styles.dayHead} aria-hidden="true">
              {dayName(d)}
            </p>
            <ul className={styles.events} aria-label={dayName(d)}>
              {props.items
                .filter((e) => e.date === d)
                .map((e) => {
                  const line = (
                    <>
                      <span className={`${styles.eventAt} tnum`}>{clockOf(e)}</span>
                      <span className={styles.eventTitle}>{e.title}</span>
                      {e.repeat !== "none" && <RepeatMark className={styles.eventRepeat} />}
                      {e.area && (
                        <span className="area-dot" data-area={e.area}>
                          <span className="visually-hidden">{copy.areas[e.area]}</span>
                        </span>
                      )}
                    </>
                  );
                  return (
                    <li key={`${e.event_id}:${e.date}`}>
                      {open ? (
                        <button type="button" className={`${styles.eventRow} ${styles.eventButton}`} onClick={() => open(`/schedule/?date=${e.date}`)}>
                          {line}
                        </button>
                      ) : (
                        <div className={styles.eventRow}>{line}</div>
                      )}
                    </li>
                  );
                })}
            </ul>
          </div>
        ))}
      </div>
    </Part>
  );
}
