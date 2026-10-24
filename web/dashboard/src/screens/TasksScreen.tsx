import { type KeyboardEvent, useCallback, useId, useRef, useState } from "react";
import type { Conditions, Today, Week } from "../api/types.gen";
import { ConditionDots } from "../components/ConditionDots";
import { StateNotice } from "../components/StateNotice";
import { TodoList, type TodoListKind } from "../components/TodoList";
import { type ApiResult, fetchApi, isConditions, isToday, isWeek } from "../lib/api";
import { useConnection } from "../lib/ConnectionProvider";
import { CONDITION_TEXT, TASKS_TEXT as T, loopLabel } from "../lib/labels";
import { usePolling } from "../lib/polling";
import { formatDay, formatKst } from "../lib/time";

type Tab = "today" | "week";
const TABS: Tab[] = ["today", "week"];
const GROUP_KIND: Record<Today["todos"][number]["group"], TodoListKind> = {
  priority: "ranked",
  scheduled: "scheduled",
  open: "open",
};
const NONE = { kind: "broken", code: "no_connection" } as const;

// States that are about the BE as a whole, not one GET: the screen shows one notice and no content.
const WHOLE_SCREEN = new Set(["offline", "unauthorized", "rate_limited", "safe_mode"]);
const sameState = (a: ApiResult<unknown>, b: ApiResult<unknown>) =>
  a.kind === b.kind && (a.kind !== "broken" || (b.kind === "broken" && a.code === b.code));

/** Consecutive runs of the same group, in the API's order (spec 6.3.2: the order is the BE's). */
function groupsOf(todos: Today["todos"]) {
  const out: { group: Today["todos"][number]["group"]; todos: Today["todos"][number]["todo"][] }[] = [];
  for (const { group, todo } of todos) {
    const last = out[out.length - 1];
    if (last && last.group === group) last.todos.push(todo);
    else out.push({ group, todos: [todo] });
  }
  return out;
}

export function TodayPanel({ today }: { today: Today }) {
  const headingId = useId();
  const groups = groupsOf(today.todos);
  return (
    <section className="panel" aria-labelledby={headingId}>
      <h2 id={headingId}>{T.today(formatDay(today.date), today.weekday)}</h2>
      {groups.length === 0 ? (
        <p className="empty">{T.noTodos}</p>
      ) : (
        <div className="tgroups">
          {groups.map((g, i) => (
            <div className="tgroup" key={`${g.group}-${i}`}>
              <h3 className="tgroup-name">{T.groups[g.group]}</h3>
              <TodoList todos={g.todos} kind={GROUP_KIND[g.group]} today={today.date} />
            </div>
          ))}
        </div>
      )}
      {today.brief && (
        <details className="brief">
          <summary>
            <span className="brief-name">{loopLabel(today.brief.loop)}</span>
            {today.brief.sent_at && <span className="meta num">{formatKst(today.brief.sent_at, "HH:mm")}</span>}
          </summary>
          <p className="brief-text">{today.brief.text}</p>
        </details>
      )}
    </section>
  );
}

export function WeekPanel({ week }: { week: Week }) {
  const headingId = useId();
  const empty = week.priorities.length === 0 && week.days.every((d) => d.todos.length === 0);
  return (
    <section className="panel" aria-labelledby={headingId}>
      <h2 id={headingId}>{T.week(formatDay(week.start), formatDay(week.end))}</h2>
      {empty && <p className="empty week-empty">{T.noTodos}</p>}
      {week.priorities.length > 0 && (
        <div className="tgroup week-prios">
          <h3 className="tgroup-name">{T.weekPriorities}</h3>
          <TodoList todos={week.priorities} kind="ranked" today={week.end} />
        </div>
      )}
      <ul className="days">
        {week.days.map((d) => {
          const id = `${headingId}-${d.date}`;
          return (
            <li key={d.date} className="day" aria-labelledby={id} aria-current={d.is_today ? "date" : undefined}>
              <span className="day-name num" id={id}>
                {formatDay(d.date)} {d.weekday}
                {d.is_today && <span className="day-today"> {T.todayMark}</span>}
              </span>
              {d.todos.length === 0 ? (
                <span className="day-empty">{T.emptyDay}</span>
              ) : (
                <TodoList todos={d.todos} kind="day" today={d.date} />
              )}
            </li>
          );
        })}
      </ul>
    </section>
  );
}

function Tabs({ tab, onChange, panelId }: { tab: Tab; onChange(t: Tab): void; panelId: string }) {
  const refs = useRef<Record<Tab, HTMLButtonElement | null>>({ today: null, week: null });
  const onKey = (e: KeyboardEvent) => {
    if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
    e.preventDefault();
    const next = TABS[(TABS.indexOf(tab) + (e.key === "ArrowRight" ? 1 : TABS.length - 1)) % TABS.length];
    onChange(next);
    refs.current[next]?.focus();
  };
  return (
    <div className="tabs" role="tablist" aria-label={T.tabsLabel} onKeyDown={onKey}>
      {TABS.map((t) => (
        <button
          key={t}
          ref={(el) => {
            refs.current[t] = el;
          }}
          type="button"
          role="tab"
          className="tab"
          aria-selected={tab === t}
          aria-controls={panelId}
          tabIndex={tab === t ? 0 : -1}
          onClick={() => onChange(t)}
        >
          {T.tabs[t]}
        </button>
      ))}
    </div>
  );
}

function Skeleton({ tall = false }: { tall?: boolean }) {
  return <div className={tall ? "panel skeleton" : "panel skeleton short"} aria-busy="true" />;
}

/** (b) 할 일 + 컨디션, spec 13.3: `/today` or `/week` by tab, `/conditions` under both. Read only. */
export function TasksScreen() {
  const { ready, conn } = useConnection();
  const [tab, setTab] = useState<Tab>("today");
  const panelId = useId();
  const key = ready && conn ? `${conn.beUrl}\n${conn.token}` : "";

  const loadTodos = useCallback(async (): Promise<ApiResult<Today | Week>> => {
    if (!conn) return NONE;
    return tab === "today" ? fetchApi(conn, "/today", isToday) : fetchApi(conn, "/week", isWeek);
  }, [conn, tab]);
  const loadConditions = useCallback(
    async (): Promise<ApiResult<Conditions>> => (conn ? fetchApi(conn, "/conditions", isConditions) : NONE),
    [conn],
  );
  const todos = usePolling(loadTodos, 60_000, `${key}\n${tab}`).result;
  const conditions = usePolling(loadConditions, 60_000, key).result;

  const whole =
    todos !== null && todos.kind !== "ok" && (WHOLE_SCREEN.has(todos.kind) || (conditions !== null && sameState(todos, conditions)));

  return (
    <>
      <h1>{T.title}</h1>
      <Tabs tab={tab} onChange={setTab} panelId={panelId} />
      {!ready || !conn ? (
        <>
          <Skeleton tall />
          <Skeleton />
        </>
      ) : whole ? (
        <StateNotice result={todos} />
      ) : (
        <>
          <div id={panelId} role="tabpanel" aria-label={T.tabs[tab]}>
            {todos === null ? (
              <Skeleton tall />
            ) : todos.kind !== "ok" ? (
              <section className="panel" aria-label={T.tabs[tab]}>
                <StateNotice result={todos} />
              </section>
            ) : "todos" in todos.data ? (
              <TodayPanel today={todos.data} />
            ) : (
              <WeekPanel week={todos.data} />
            )}
          </div>
          {conditions === null ? (
            <Skeleton />
          ) : conditions.kind === "ok" ? (
            <ConditionDots items={conditions.data.items} from={conditions.data.from} to={conditions.data.to} />
          ) : (
            <section className="panel" aria-label={CONDITION_TEXT.title(30)}>
              <h2>{CONDITION_TEXT.title(30)}</h2>
              <StateNotice result={conditions} />
            </section>
          )}
          <p className="hint meta">{T.hint}</p>
        </>
      )}
    </>
  );
}

export default TasksScreen;
