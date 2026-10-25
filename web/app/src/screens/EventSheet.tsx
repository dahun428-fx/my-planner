import { useEffect, useId, useRef, useState } from "react";
import { useAction } from "../api/actions";
import { apiGet } from "../api/client";
import type { EventDetail, EventItem } from "../api/types.gen";
import { BlockError } from "../components/BlockError";
import { ConfirmSheet } from "../components/ConfirmSheet";
import { Segmented } from "../components/Segmented";
import { Sheet } from "../components/Sheet";
import { useToast } from "../components/Toast";
import { copy } from "../lib/copy";
import { clockOf, mdOf, WEEKDAY_KEYS, type WeekdayKey, weekdayIndex, whenOf } from "../lib/schedule";
import styles from "./EventSheet.module.css";

type Area = NonNullable<EventItem["area"]>;
type Repeat = EventItem["repeat"];
type Remind = EventItem["remind_min"];
type Scope = "one" | "following" | "all";

// 영역은 BE 열거 순서(copy.areas와 같다).
const AREAS = Object.keys(copy.areas) as Area[];
const REPEATS: Repeat[] = ["none", "daily", "weekly", "monthly"];
// 10장 "알림 고르기" 순서. 하루 종일 일정은 10·30·60분 전을 고를 수 없다(5.1, BE 422 remind_invalid).
const REMINDS: Remind[] = [0, 10, 30, 60, 1440, null];
const ALL_DAY_REMINDS: Remind[] = [0, 1440, null];
// 알림을 고르지 않았을 때(5.1): 시각 있는 일정 10분 전, 하루 종일은 그날 09:00(정시).
const defaultRemind = (allDay: boolean): Remind => (allDay ? 0 : 10);
const DEFAULT_TIME = "09:00";

const remindLabel = (r: Remind) => (r === null ? copy.schedule.remind.none : copy.schedule.remind[r]);

// ---------------------------------------------------------------------------------------------
// 상세 시트 (9.2): 줄을 누르면 연다. 고치기, 반복 일정이면 "이번만 건너뛰기"·"이후 반복 끝내기"·"모두 지우기",
// 한 번짜리면 "지우기". 지우기류는 확인 시트를 거친다. 사용자가 한 일이라 BE는 확인 없이 적용하고, 토스트에 되돌리기.
// ---------------------------------------------------------------------------------------------

export function EventDetailSheet({
  item,
  writable,
  onClose,
  onEdit,
  onChanged,
}: {
  item: EventItem | null;
  writable: boolean;
  onClose(): void;
  onEdit(event: EventDetail): void;
  onChanged(): void;
}) {
  // 닫히는 동안에도 내용이 남아 있게 마지막 줄을 둔다.
  const [shown, setShown] = useState(item);
  useEffect(() => {
    if (item) setShown(item);
  }, [item]);
  const [detail, setDetail] = useState<EventDetail | null>(null);
  // 정의를 읽지 못하면 말없이 꺼진 "고치기" 대신 그 까닭과 다시 시도를 보인다(5.4 블록 오류).
  const [failed, setFailed] = useState<string | null>(null);
  const [reads, setReads] = useState(0);
  const id = item?.event_id;
  useEffect(() => {
    setDetail(null);
    setFailed(null);
    if (id === undefined) return;
    let alive = true;
    void apiGet<EventDetail>(`/events/${id}`, "EventDetail").then((r) => {
      if (!alive) return;
      if (r.kind === "ok") setDetail(r.data);
      else setFailed(r.kind === "error" ? r.code : r.kind);
    });
    return () => {
      alive = false;
    };
  }, [id, reads]);

  const { run } = useAction();
  const [asking, setAsking] = useState<Scope | null>(null);
  const [busy, setBusy] = useState(false);

  const e = item ?? shown;
  if (!e) return null;
  const repeating = e.repeat !== "none";
  const md = mdOf(e.date);
  const summary: Record<Scope, string> = {
    one: copy.schedule.askOne(e.title, md),
    following: copy.schedule.askFollowing(e.title, md),
    all: copy.schedule.askAll(e.title),
  };
  const label: Record<Scope, string> = {
    one: copy.schedule.skipOne,
    following: copy.schedule.endFollowing,
    all: repeating ? copy.schedule.deleteAll : copy.schedule.delete,
  };

  const apply = async (scope: Scope) => {
    setBusy(true);
    try {
      const out = await run("delete_event", scope === "all" ? { id: e.event_id, scope } : { id: e.event_id, scope, date: e.date });
      if (out === null) return;
      setAsking(null);
      if (out.kind === "applied") {
        onChanged();
        onClose();
      }
    } finally {
      setBusy(false);
    }
  };

  const scopes: Scope[] = repeating ? ["one", "following", "all"] : ["all"];
  return (
    <>
      <Sheet open={item !== null && asking === null} onClose={onClose} title={e.title}>
        <div className={styles.detail}>
          <p className={styles.when}>{detail ? whenOf(detail) : `${md} ${clockOf(e)}`}</p>
          <p className={styles.meta}>
            {copy.schedule.remindLine(remindLabel(e.remind_min))}
            {e.area && ` · ${copy.areas[e.area]}`}
          </p>
          {detail?.note && <p className={styles.note}>{detail.note}</p>}
          {failed !== null && <BlockError code={failed} onRetry={() => setReads((n) => n + 1)} />}
          <div className={styles.actions}>
            <button type="button" className={styles.action} disabled={!writable || !detail} onClick={() => detail && onEdit(detail)}>
              {copy.schedule.edit}
            </button>
            {scopes.map((s) => (
              <button key={s} type="button" className={`${styles.action} ${styles.negative}`} disabled={!writable} onClick={() => setAsking(s)}>
                {label[s]}
              </button>
            ))}
          </div>
        </div>
      </Sheet>
      {asking && (
        <ConfirmSheet
          summary={summary[asking]}
          busy={busy}
          keepLabel={copy.schedule.keep}
          changeLabel={label[asking]}
          onKeep={() => setAsking(null)}
          onChange={() => void apply(asking)}
        />
      )}
    </>
  );
}

// ---------------------------------------------------------------------------------------------
// 추가·고치기 시트 (9.2): 제목, 날짜, 하루 종일, 시각, 반복(매주면 요일 일곱 토글), 알림(기본 10분 전), 영역, 메모.
// 반복 일정을 고치면 모든 날이 바뀐다(하루만 바꾸기는 없다, Q4).
// ---------------------------------------------------------------------------------------------

export function EventFormSheet({
  open,
  event,
  date,
  onClose,
  onSaved,
}: {
  open: boolean;
  /** 고칠 정의(`GET /events/{id}`). null이면 새 일정. */
  event: EventDetail | null;
  /** 새 일정의 날짜: 스케줄 탭에서 고른 날. */
  date: string;
  onClose(): void;
  onSaved(): void;
}) {
  // 열 때마다 칸을 새로 채운다.
  const [opened, setOpened] = useState(0);
  useEffect(() => {
    if (open) setOpened((n) => n + 1);
  }, [open]);
  return (
    <Sheet open={open} onClose={onClose} title={event ? copy.schedule.editTitle : copy.schedule.addTitle}>
      <EventForm key={opened} event={event} date={date} onClose={onClose} onSaved={onSaved} />
    </Sheet>
  );
}

function EventForm({ event, date, onClose, onSaved }: { event: EventDetail | null; date: string; onClose(): void; onSaved(): void }) {
  const { run } = useAction();
  const toast = useToast();
  const ids = { title: useId(), date: useId(), time: useId(), note: useId(), allDay: useId() };
  const [title, setTitle] = useState(event?.title ?? "");
  const [day, setDay] = useState(event?.date ?? date);
  const [allDay, setAllDay] = useState(event?.all_day ?? false);
  const [time, setTime] = useState(event?.time ?? DEFAULT_TIME);
  const [repeat, setRepeat] = useState<Repeat>(event?.repeat ?? "none");
  const [weekdays, setWeekdays] = useState<ReadonlySet<WeekdayKey>>(new Set(event?.weekdays ?? []));
  const [remind, setRemind] = useState<Remind>(event ? event.remind_min : defaultRemind(false));
  // 알림을 직접 고르기 전에는 하루 종일 스위치를 따라 기본값(10분 전 / 정시)이 바뀐다.
  const remindPicked = useRef(event !== null);
  const [area, setArea] = useState<Area | null>(event?.area ?? null);
  const [note, setNote] = useState(event?.note ?? "");
  const [busy, setBusy] = useState(false);
  const lock = useRef(false);

  const weekdayOf = (d: string): WeekdayKey => WEEKDAY_KEYS[weekdayIndex(d)];
  const choices = allDay ? ALL_DAY_REMINDS : REMINDS;
  const trimmed = title.trim();
  const ready = trimmed !== "" && day !== "" && (allDay || time !== "") && (repeat !== "weekly" || weekdays.size > 0);

  const changeAllDay = (on: boolean) => {
    setAllDay(on);
    if (!remindPicked.current) setRemind(defaultRemind(on));
    else if (on && !ALL_DAY_REMINDS.includes(remind)) setRemind(defaultRemind(true));
  };
  // 매주 반복의 첫 날 요일은 반복 요일에 들어 있어야 한다(5.1): 날짜나 반복을 바꾸면 그 요일을 켠다.
  const changeDay = (d: string) => {
    setDay(d);
    if (repeat === "weekly" && d) setWeekdays((s) => new Set(s).add(weekdayOf(d)));
  };
  const changeRepeat = (r: Repeat) => {
    setRepeat(r);
    if (r === "weekly" && weekdays.size === 0 && day) setWeekdays(new Set([weekdayOf(day)]));
  };
  const toggleWeekday = (k: WeekdayKey) =>
    setWeekdays((s) => {
      const next = new Set(s);
      if (!next.delete(k)) next.add(k);
      return next;
    });

  const submit = async () => {
    if (!ready || lock.current) return;
    lock.current = true;
    setBusy(true);
    try {
      const fields = {
        title: trimmed,
        date: day,
        all_day: allDay,
        time: allDay ? null : time,
        repeat,
        weekdays: repeat === "weekly" ? WEEKDAY_KEYS.filter((k) => weekdays.has(k)) : null,
        remind_min: remind,
        area,
        note: note.trim(),
      };
      const out = event ? await run("update_event", { id: event.id, ...fields }) : await run("create_event", fields);
      if (out === null) return;
      if (out.kind === "applied") {
        onSaved();
        onClose();
      } else if (out.kind === "conflict" || out.kind === "needs_confirm") {
        toast.show({ text: copy.actions.failed });
      }
    } finally {
      lock.current = false;
      setBusy(false);
    }
  };

  return (
    <form
      className={styles.form}
      onSubmit={(e) => {
        e.preventDefault();
        void submit();
      }}
    >
      <div className={styles.field}>
        <label className={styles.label} htmlFor={ids.title}>
          {copy.schedule.titleLabel}
        </label>
        <input id={ids.title} className={styles.input} type="text" maxLength={100} value={title} onChange={(e) => setTitle(e.target.value)} autoComplete="off" />
      </div>
      <div className={styles.field}>
        <label className={styles.label} htmlFor={ids.date}>
          {copy.schedule.dateLabel}
        </label>
        <input id={ids.date} className={styles.input} type="date" value={day} onChange={(e) => changeDay(e.target.value)} />
      </div>
      <label className={styles.switchRow} htmlFor={ids.allDay}>
        <span>{copy.schedule.allDay}</span>
        <input id={ids.allDay} className={styles.switch} type="checkbox" role="switch" checked={allDay} onChange={(e) => changeAllDay(e.target.checked)} />
      </label>
      {!allDay && (
        <div className={styles.field}>
          <label className={styles.label} htmlFor={ids.time}>
            {copy.schedule.timeLabel}
          </label>
          <input id={ids.time} className={styles.input} type="time" value={time} onChange={(e) => setTime(e.target.value)} />
        </div>
      )}
      <div className={styles.field}>
        <Segmented<Repeat>
          ariaLabel={copy.schedule.repeatLabel}
          value={repeat}
          onChange={changeRepeat}
          options={REPEATS.map((r) => ({ value: r, label: copy.schedule.repeat[r] }))}
        />
        {repeat === "weekly" && (
          <div role="group" aria-label={copy.schedule.weekdaysLabel} className={styles.weekdays}>
            {WEEKDAY_KEYS.map((k, i) => (
              <button
                key={k}
                type="button"
                className={`${styles.weekday} ${weekdays.has(k) ? styles.picked : ""}`}
                aria-pressed={weekdays.has(k)}
                onClick={() => toggleWeekday(k)}
              >
                {copy.schedule.weekdays[i]}
              </button>
            ))}
          </div>
        )}
      </div>
      <div className={styles.field}>
        <span className={styles.label}>{copy.schedule.remindLabel}</span>
        <div role="group" aria-label={copy.schedule.remindLabel} className={styles.pills}>
          {choices.map((r) => (
            <button
              key={String(r)}
              type="button"
              className={`${styles.pill} ${remind === r ? styles.picked : ""}`}
              aria-pressed={remind === r}
              onClick={() => {
                remindPicked.current = true;
                setRemind(r);
              }}
            >
              {remindLabel(r)}
            </button>
          ))}
        </div>
      </div>
      <div className={styles.field}>
        <span className={styles.label}>{copy.schedule.areaLabel}</span>
        <div role="group" aria-label={copy.schedule.areaLabel} className={styles.pills}>
          {AREAS.map((a) => (
            <button
              key={a}
              type="button"
              className={`${styles.pill} ${area === a ? styles.picked : ""}`}
              aria-pressed={area === a}
              onClick={() => setArea((cur) => (cur === a ? null : a))}
            >
              <span className="area-dot" data-area={a} aria-hidden="true" />
              {copy.areas[a]}
            </button>
          ))}
        </div>
      </div>
      <div className={styles.field}>
        <label className={styles.label} htmlFor={ids.note}>
          {copy.schedule.noteLabel}
        </label>
        <textarea id={ids.note} className={`${styles.input} ${styles.noteInput}`} maxLength={1000} value={note} onChange={(e) => setNote(e.target.value)} />
      </div>
      <div className={styles.buttons}>
        <button type="button" className={styles.cancel} onClick={onClose}>
          {copy.schedule.close}
        </button>
        <button type="submit" className={styles.submit} disabled={!ready || busy}>
          {event ? copy.schedule.save : copy.schedule.addSubmit}
        </button>
      </div>
    </form>
  );
}
