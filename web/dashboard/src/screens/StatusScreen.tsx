import { Fragment, useCallback, useId } from "react";
import type { Status, StatusStat } from "../api/types.gen";
import { RecentAreas } from "../components/RecentAreas";
import { StatBar, rampStep } from "../components/StatBar";
import { StateNotice } from "../components/StateNotice";
import { HpCells } from "../components/HpCells";
import { XpBar } from "../components/XpBar";
import { type ApiResult, fetchApi, isStatus } from "../lib/api";
import { useConnection } from "../lib/ConnectionProvider";
import { STATUS_TEXT as T } from "../lib/labels";
import { usePolling } from "../lib/polling";

const NONE = { kind: "broken", code: "no_connection" } as const;

/** "Q3" when the earlier quarter is in the same year as the score, else the whole "2025-Q4". */
function shortPeriod(prev: string, current: string | null): string {
  return current !== null && prev.slice(0, 4) === current.slice(0, 4) ? prev.slice(5) : prev;
}

function StatRow({ stat: s, latest }: { stat: StatusStat; latest: string | null }) {
  const older = s.score !== null && s.period !== null && s.period !== latest;
  return (
    <li className="stat" data-area={s.area} data-debuff={s.debuff || undefined}>
      <span className="stat-name">
        <span className="area-dot" aria-hidden="true" />
        {s.label}
      </span>
      <StatBar label={s.label} score={s.score} bonus={s.bonus} />
      <span className="stat-value num">
        {s.score !== null && <span className="stat-step" data-step={rampStep(s.score)} aria-hidden="true" />}
        {s.score === null || s.effective_score === null ? (
          <span className="meta">{T.noScore}</span>
        ) : s.bonus > 0 ? (
          s.effective_score.toFixed(1)
        ) : (
          s.effective_score
        )}
        {older && <span className="meta"> {T.olderPeriod(s.period!)}</span>}
      </span>
      {(s.score !== null || s.bonus > 0) && (
        <span className="stat-sub meta">{s.score !== null ? T.statSub(s.score, s.bonus) : T.statSubNoBase(s.bonus)}</span>
      )}
      {s.debuff && s.prev_score !== null && s.prev_period !== null && (
        <span className="stat-debuff">{T.debuff(shortPeriod(s.prev_period, s.period), s.prev_score)}</span>
      )}
      {s.debuff && s.recovery_quest && <span className="stat-quest">{T.recovery(s.recovery_quest)}</span>}
    </li>
  );
}

function Joined({ items }: { items: string[] }) {
  return (
    <>
      {items.map((t, i) => (
        <Fragment key={i}>
          {i > 0 && " · "}
          <span className="part">{t}</span>
        </Fragment>
      ))}
    </>
  );
}

export function StatusView({ status: s }: { status: Status }) {
  const statsId = useId();
  const questsId = useId();
  const recentId = useId();
  const scored = s.stats.filter((x) => x.score !== null && x.period !== null);
  const latest = scored.length > 0 ? scored.map((x) => x.period!).sort().at(-1)! : null;
  const offersQuest = s.daily_quests.length > 0 || s.stats.some((x) => x.debuff && x.recovery_quest);
  return (
    <div className="panels">
      <section className="panel panel-wide hero" aria-label={T.level(s.level)}>
        <XpBar level={s.level} into={s.xp_into_level} forNext={s.xp_for_next} />
        <HpCells score={s.hp.score} />
      </section>

      <section className="panel" aria-labelledby={statsId}>
        <h2 id={statsId}>{T.stats(latest)}</h2>
        {latest === null ? (
          <p className="empty">{T.statsEmpty}</p>
        ) : (
          <ul className="stats">
            {s.stats.map((x) => (
              <StatRow key={x.area} stat={x} latest={latest} />
            ))}
          </ul>
        )}
      </section>

      <RecentAreas stats={s.stats} headingId={recentId} />

      <section className="panel" aria-labelledby={questsId}>
        <h2 id={questsId}>{T.mainQuests}</h2>
        {s.main_quests.length === 0 ? (
          <p className="empty">{T.mainEmpty}</p>
        ) : (
          <ol className="quests">
            {s.main_quests.map((q) => (
              <li key={q.task_id} className="quest">
                <span className="todo-lead num">{q.rank}.</span>
                <span className="quest-title">{q.title}</span>
                <span className="quest-steps meta num">{T.firstSteps(q.first_steps.done, q.first_steps.done + q.first_steps.open)}</span>
              </li>
            ))}
          </ol>
        )}
        <h3 className="sub-heading">{T.dailyQuests}</h3>
        {s.daily_quests.length === 0 ? (
          <p className="empty">{T.dailyEmpty}</p>
        ) : (
          <ul className="quests daily">
            {s.daily_quests.map((q) => (
              <li key={q.task_id} className="quest">
                <span className="quest-dot" aria-hidden="true" />
                <span className="quest-title">
                  {T.daily(q.title)}
                  {q.parent_title && <span className="quest-parent meta">{q.parent_title}</span>}
                </span>
              </li>
            ))}
          </ul>
        )}
        {offersQuest && <p className="hint meta">{T.take}</p>}
      </section>

      <section className="panel panel-wide" aria-label={`${T.titles}, ${T.recentXp}`}>
        <div className="row">
          <h2>{T.titles}</h2>
          {s.titles.length === 0 ? <p className="empty">{T.titlesEmpty}</p> : <p className="line">{s.titles.map((t) => t.title).join(" · ")}</p>}
        </div>
        <div className="row">
          <h2>{T.recentXp}</h2>
          {s.recent_xp.length === 0 ? (
            <p className="empty">{T.recentEmpty}</p>
          ) : (
            <p className="line num">
              <Joined items={s.recent_xp.map((x) => T.xpGain(x.amount, x.label))} />
            </p>
          )}
        </div>
      </section>
    </div>
  );
}

function Loading() {
  return (
    <div aria-busy="true">
      <div className="panel skeleton short" />
      <div className="panel skeleton" />
      <div className="panel skeleton short" />
    </div>
  );
}

/** (d) 게임형 상태창, spec 13.5: `GET /status` (the same snapshot as Telegram `/status`). Read only. */
export function StatusScreen() {
  const { ready, conn, backOnline } = useConnection();
  const key = ready && conn ? `${conn.beUrl}\n${conn.token}` : "";
  const load = useCallback(async (): Promise<ApiResult<Status>> => (conn ? fetchApi(conn, "/status", isStatus) : NONE), [conn]);
  const { result } = usePolling(load, 60_000, key, { wake: backOnline });
  return (
    <>
      <h1>{T.title}</h1>
      {!ready || !conn || result === null ? <Loading /> : result.kind === "ok" ? <StatusView status={result.data} /> : <StateNotice result={result} />}
    </>
  );
}

export default StatusScreen;
