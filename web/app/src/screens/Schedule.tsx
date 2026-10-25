import { useRouter } from "next/router";
import { type PointerEvent as ReactPointerEvent, useCallback, useEffect, useRef, useState } from "react";
import { useAction } from "../api/actions";
import { apiGet } from "../api/client";
import type { EventDetail, EventItem, EventList } from "../api/types.gen";
import { useChatSheet } from "../chat/sheetContext";
import { BlockError } from "../components/BlockError";
import { ChatLauncher, launcherReason } from "../components/ChatLauncher";
import { Group } from "../components/Group";
import { Icon } from "../components/icons";
import { LargeTitle } from "../components/LargeTitle";
import { MoreButton } from "../components/MoreButton";
import { OfflineNotice } from "../components/OfflineNotice";
import { RepeatMark } from "../components/RepeatMark";
import { Skeleton } from "../components/Skeleton";
import { StatusDot } from "../components/StatusDot";
import { SwipeRow } from "../components/SwipeRow";
import { useToast } from "../components/Toast";
import { useConnection, useWritable } from "../lib/ConnectionProvider";
import { copy } from "../lib/copy";
import { usePolling } from "../lib/polling";
import { addDays } from "../lib/time";
import { clockOf, dayName, dayOrder, isDate, localToday, weekOf } from "../lib/schedule";
import page from "../styles/page.module.css";
import { EventDetailSheet, EventFormSheet } from "./EventSheet";
import { MonthCalendar } from "./MonthCalendar";
import styles from "./Schedule.module.css";

// 좌우로 이만큼 넘게, 세로보다 많이 밀어야 주가 바뀐다(살짝 밀린 탭은 그날 고르기).
const SWIPE_PX = 50;

const eventsPath = (week: string[]) => `/events?start=${week[0]}&end=${week[6]}`;

/** 스케줄 탭의 주소(9.2). 푸시도 이 모양으로 연다(5.3). */
export const scheduleHref = (date: string) => `/schedule/?date=${date}`;

// SP9 9.2: 큰 제목은 보고 있는 달(누르면 한 달 달력), 한 주 띠(월~일, 오늘은 잉크 원, 고른 날은 테두리,
// 일정 있는 날은 점 하나), 좌우로 밀면 앞뒤 주, 그 아래 고른 날의 목록. 고른 날은 주소 `?date=`에 남는다.
// 오프라인이면 마지막으로 받은 그 주를 읽기만 한다.
export function Schedule() {
  const router = useRouter();
  const { state, recheck } = useConnection();
  const toast = useToast();
  const { run } = useAction();
  const chat = useChatSheet();

  const asked = router.isReady && isDate(router.query.date) ? router.query.date : null;
  const [selected, setSelected] = useState(() => asked ?? localToday());
  // 주소가 바뀌면(이 화면을 보는 중에 누른 푸시) 그 날로 간다.
  useEffect(() => {
    if (asked) setSelected(asked);
  }, [asked]);

  const pick = useCallback(
    (date: string) => {
      setSelected(date);
      void router.replace(scheduleHref(date), undefined, { shallow: true, scroll: false });
    },
    [router],
  );

  const week = weekOf(selected);
  const weekRef = useRef(week);
  weekRef.current = week;
  const { result, refresh } = usePolling<EventList>(() => apiGet<EventList>(eventsPath(weekRef.current), "EventList"));
  const weekStart = week[0];
  const firstWeek = useRef(weekStart);
  useEffect(() => {
    if (weekStart === firstWeek.current) return; // 첫 주는 usePolling이 처음에 읽는다
    firstWeek.current = weekStart;
    void refresh();
  }, [weekStart, refresh]);

  // 받은 주를 기억해 둔다: 다른 주를 읽는 동안이나 오프라인이면 이것을 보인다(그 주일 때만).
  const [last, setLast] = useState<{ data: EventList; at: string } | null>(null);
  useEffect(() => {
    if (result?.kind === "ok") setLast({ data: result.data, at: new Date().toISOString() });
  }, [result]);

  useEffect(() => toast.onUndone(() => void refresh()), [toast, refresh]);
  // 비서가 시트에서 일정을 만들었을 수 있다(create_event).
  useEffect(() => chat.onClosed(() => void refresh()), [chat, refresh]);

  const offline = state?.kind === "offline" || result?.kind === "offline";
  const live = result?.kind === "ok" && !offline;
  const writable = useWritable(live);
  const canAdd = useWritable(!offline);
  const canChat = useWritable(!offline, { strict: true });

  const data =
    result?.kind === "ok" && result.data.start === weekStart ? result.data : last?.data.start === weekStart ? last.data : null;
  const marked = new Set(data?.items.map((e) => e.date));
  const today = localToday();

  // ---- 시트 ----
  const [detail, setDetail] = useState<EventItem | null>(null);
  const [form, setForm] = useState<{ event: EventDetail | null } | null>(null);

  // ---- 한 주 띠: 좌우로 밀기 ----
  const swipe = useRef<{ id: number; x: number; y: number } | null>(null);
  const swallowClick = useRef(false);
  const onDown = (e: ReactPointerEvent<HTMLDivElement>) => {
    swipe.current = { id: e.pointerId, x: e.clientX, y: e.clientY };
  };
  const onUp = (e: ReactPointerEvent<HTMLDivElement>) => {
    const s = swipe.current;
    swipe.current = null;
    if (!s || s.id !== e.pointerId) return;
    const dx = e.clientX - s.x;
    if (Math.abs(dx) < SWIPE_PX || Math.abs(dx) <= Math.abs(e.clientY - s.y)) return;
    swallowClick.current = true;
    setTimeout(() => (swallowClick.current = false), 0);
    pick(addDays(selected, dx < 0 ? 7 : -7));
  };

  // ---- 달력 ----
  const [monthOpen, setMonthOpen] = useState(false);
  const [, month] = selected.split("-").map(Number);

  // 줄을 밀어 바로 건너뛰기·지우기(9.2). 사용자가 한 일이라 확인 없이 적용하고 토스트에 되돌리기.
  const remove = async (e: EventItem) => {
    const args = e.repeat === "none" ? { id: e.event_id, scope: "all" } : { id: e.event_id, scope: "one", date: e.date };
    if (await run("delete_event", args)) await refresh();
  };

  const row = (e: EventItem) => (
    <li key={`${e.event_id}:${e.date}`} className={styles.item}>
      <SwipeRow
        disabled={!writable}
        menuTitle={e.title}
        moreLabel={copy.today.moreActions(e.title)}
        actions={[
          e.repeat === "none"
            ? { label: copy.schedule.delete, tone: "negative", onPress: () => void remove(e) }
            : { label: copy.schedule.skip, tone: "negative", onPress: () => void remove(e) },
        ]}
      >
        <button type="button" className={styles.row} onClick={() => setDetail(e)}>
          <span className={`${styles.clock} tnum`}>{clockOf(e)}</span>
          <span className={styles.text}>
            <span className={styles.title}>{e.title}</span>
            {e.repeat !== "none" && <RepeatMark className={styles.repeat} />}
            {e.origin === "chat" && <span className={styles.secretary}>{copy.schedule.bySecretary}</span>}
          </span>
          {e.area && (
            <span className="area-dot" data-area={e.area}>
              <span className="visually-hidden">{copy.areas[e.area]}</span>
            </span>
          )}
        </button>
      </SwipeRow>
    </li>
  );

  let body: React.ReactNode;
  if (data) {
    const items = dayOrder(data.items.filter((e) => e.date === selected));
    body =
      items.length === 0 ? (
        <p className={styles.line}>{copy.schedule.empty}</p>
      ) : (
        <Group paper>
          <ul className={styles.list} aria-label={dayName(selected)}>
            {items.map(row)}
          </ul>
        </Group>
      );
  } else if (result === null || result.kind === "ok" || result.kind === "offline") {
    body = offline ? null : (
      <Group paper>
        {[0, 1].map((i) => (
          <Skeleton key={i} size="row" />
        ))}
      </Group>
    );
  } else {
    body = (
      <Group paper>
        <BlockError code={result.kind === "error" ? result.code : result.kind} onRetry={() => void refresh()} />
      </Group>
    );
  }

  return (
    <main className={`${page.main} ${styles.main}`}>
      <LargeTitle
        title={
          <button type="button" className={styles.monthToggle} aria-expanded={monthOpen} onClick={() => setMonthOpen((o) => !o)}>
            {copy.schedule.month(month)}
          </button>
        }
        trailing={
          <span className={styles.trailing}>
            {state && <StatusDot state={state} />}
            <button
              type="button"
              className={`${styles.add} pressable`}
              aria-label={copy.schedule.add}
              disabled={!canAdd}
              onClick={() => setForm({ event: null })}
            >
              <Icon name="plus" />
            </button>
            <MoreButton />
          </span>
        }
      />
      {monthOpen && (
        <MonthCalendar
          selected={selected}
          today={today}
          onPick={(d) => {
            pick(d);
            setMonthOpen(false);
          }}
        />
      )}
      <div
        role="group"
        aria-label={copy.schedule.week}
        className={styles.strip}
        onPointerDown={onDown}
        onPointerUp={onUp}
        onPointerCancel={() => (swipe.current = null)}
        onClickCapture={(e) => {
          if (!swallowClick.current) return;
          swallowClick.current = false;
          e.preventDefault();
          e.stopPropagation();
        }}
      >
        {week.map((d) => (
          <button
            key={d}
            type="button"
            className={styles.day}
            aria-label={marked.has(d) ? copy.schedule.hasEvents(dayName(d)) : dayName(d)}
            aria-pressed={d === selected}
            aria-current={d === today ? "date" : undefined}
            data-events={marked.has(d) ? "true" : undefined}
            onClick={() => pick(d)}
          >
            <span className={styles.weekday} aria-hidden="true">
              {copy.schedule.weekdays[week.indexOf(d)]}
            </span>
            <span className={`${styles.date} tnum`} aria-hidden="true">
              {Number(d.slice(8))}
            </span>
            <span className={styles.dot} aria-hidden="true" />
          </button>
        ))}
      </div>
      {offline && <OfflineNotice savedAt={last?.at ?? null} onRetry={() => void recheck()} />}
      {body}
      <ChatLauncher disabled={!canChat} offline={state?.kind === "offline"} reason={launcherReason(state?.kind)} onOpen={chat.open} />
      <EventDetailSheet
        item={detail}
        writable={writable}
        onClose={() => setDetail(null)}
        onEdit={(event) => {
          setDetail(null);
          setForm({ event });
        }}
        onChanged={() => void refresh()}
      />
      <EventFormSheet
        open={form !== null}
        event={form?.event ?? null}
        date={selected}
        onClose={() => setForm(null)}
        onSaved={() => void refresh()}
      />
    </main>
  );
}
