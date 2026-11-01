import Link from "next/link";
import { useState } from "react";
import { apiGet } from "../api/client";
import type { InnateItem, StandingArea, Status as StatusData, StatusStat } from "../api/types.gen";
import { BlockError } from "../components/BlockError";
import { Group } from "../components/Group";
import { LargeTitle } from "../components/LargeTitle";
import { OfflineNotice } from "../components/OfflineNotice";
import { Pictogram } from "../components/pictograms.gen";
import { Skeleton } from "../components/Skeleton";
import { useConnection } from "../lib/ConnectionProvider";
import { copy } from "../lib/copy";
import { usePolling } from "../lib/polling";
import page from "../styles/page.module.css";
import styles from "./Status.module.css";
import { StatusMoments } from "./StatusMoments";

const T = copy.statusScreen;
const AREAS: StatusStat["area"][] = ["career", "finance", "health", "relationships", "learning", "quality_of_life"];

/** The effective score as the dashboard writes it: a decimal only while a bonus is on it. */
const scoreText = (s: StatusStat): string => (s.effective_score === null || s.score === null ? T.noScore : s.bonus > 0 ? s.effective_score.toFixed(1) : String(s.effective_score));

function Level({ data }: { data: StatusData }) {
  const ratio = data.xp_for_next > 0 ? Math.min(1, Math.max(0, data.xp_into_level / data.xp_for_next)) : 0;
  return (
    <section className={styles.level}>
      <div className={styles.levelHead}>
        <span className={styles.levelName}>
          <Pictogram name="level" size={20} />
          {T.level(data.level)}
        </span>
        <span className={styles.meta}>{T.xp(data.xp_into_level, data.xp_for_next)}</span>
      </div>
      {/* An SVG bar: the CSP has no inline style attribute, so the width is a drawing attribute. */}
      <svg className={styles.xp} viewBox="0 0 100 6" preserveAspectRatio="none" role="img" aria-label={T.xpBar(data.xp_into_level, data.xp_for_next)}>
        <rect className={styles.track} x="0" y="0" width="100" height="6" rx="1" ry="3" />
        {ratio > 0 && <rect className={styles.fill} x="0" y="0" width={ratio * 100} height="6" rx="1" ry="3" />}
      </svg>
    </section>
  );
}

/**
 * SP13 10.1: the area's objective position beside its satisfaction, and under the name the drift
 * marks and a position debuff. With no position, "위치 —" opens the hint that says what fills it.
 */
function Position({ st, open, onToggle }: { st: StandingArea; open: boolean; onToggle(): void }) {
  if (st.score === null) {
    return (
      <button type="button" className={styles.posNone} aria-expanded={open} onClick={onToggle}>
        {T.posNone}
      </button>
    );
  }
  return <span className={styles.pos}>{T.pos(st.score, st.peer_score, st.reliability)}</span>;
}

function StandingLines({ st, open }: { st: StandingArea; open: boolean }) {
  return (
    <>
      {st.drift.map((d) => (
        <span key={`${d.kind}${d.delta}`} className={`${styles.meta} ${d.kind === "world" ? styles.world : styles.mine}`}>
          {T.drift(d)}
        </span>
      ))}
      {st.debuff && <span className={`${styles.meta} ${styles.debuff}`}>{T.posDebuff(st.recovery_quest)}</span>}
      {open && st.score === null && st.hint && <span className={styles.meta}>{st.hint}</span>}
    </>
  );
}

function Stats({ stats, body }: { stats: StatusStat[]; body: StatusData["body"] }) {
  const [open, setOpen] = useState<ReadonlySet<string>>(new Set());
  const toggle = (area: string) =>
    setOpen((prev) => {
      const next = new Set(prev);
      if (!next.delete(area)) next.add(area);
      return next;
    });
  return (
    <Group heading={T.statsHeading}>
      <ul className={styles.list}>
        {stats.map((s) => {
          const st = s.standing ?? null;
          return (
            <li key={s.area} className={styles.item} data-area={s.area}>
              <span className={styles.face}>
                <Pictogram name={s.area} size={20} />
              </span>
              <span className={styles.text}>
                <span className={styles.name}>{s.label}</span>
                <span className={styles.meta}>{s.score !== null ? T.statSub(s.score, s.bonus) : T.statSubNoBase(s.bonus)}</span>
                {s.area === "health" &&
                  (body === null ? (
                    <span className={styles.meta}>{T.bodyConnect}</span>
                  ) : (
                    <>
                      {T.bodyLine(body) !== "" && <span className={styles.meta}>{T.bodyLine(body)}</span>}
                      <span className={styles.meta}>{T.bodyLast(body.last_date)}</span>
                    </>
                  ))}
                {st && <StandingLines st={st} open={open.has(s.area)} />}
              </span>
              {st ? (
                <span className={styles.numbers}>
                  <span className={`${styles.value} ${s.score === null ? styles.none : ""}`}>{T.sat(scoreText(s))}</span>
                  <Position st={st} open={open.has(s.area)} onToggle={() => toggle(s.area)} />
                </span>
              ) : (
                <span className={`${styles.value} ${s.score === null ? styles.none : ""}`}>{scoreText(s)}</span>
              )}
            </li>
          );
        })}
      </ul>
    </Group>
  );
}

/** SP13 10.2: the three axes that are a starting point, never scored again; then the line to the detail screen. */
function Innate({ items }: { items: InnateItem[] }) {
  return (
    <Group heading={T.innateHeading}>
      <p className={styles.innate}>{items.map((i) => T.innateItem(i.label, i.score)).join(" · ")}</p>
      <p className={styles.innateNote}>{T.innateNote}</p>
      <Link href="/status/standing/" className={styles.detail}>
        {T.standingLink}
      </Link>
    </Group>
  );
}

function Recent({ stats }: { stats: StatusStat[] }) {
  const rows = stats
    .filter((s) => s.bonus > 0)
    .sort((a, b) => b.bonus - a.bonus || AREAS.indexOf(a.area) - AREAS.indexOf(b.area));
  return (
    <Group
      heading={
        <span className={styles.headWithIcon}>
          <Pictogram name="status" size={16} />
          {T.recentHeading}
        </span>
      }
    >
      {rows.length === 0 ? (
        <p className={styles.empty}>{T.recentAreasEmpty}</p>
      ) : (
        <ul className={styles.list}>
          {rows.map((s) => (
            <li key={s.area} className={styles.item} data-area={s.area}>
              <span className={styles.face}>
                <Pictogram name={s.area} size={20} />
              </span>
              <span className={styles.text}>
                <span className={styles.name}>{s.label}</span>
                <span className={styles.meta}>{T.recentCounts(s.activity)}</span>
              </span>
              <span className={styles.value}>{T.recentLine(s.bonus)}</span>
            </li>
          ))}
        </ul>
      )}
    </Group>
  );
}

// SP8 10.2: what have I been putting my hands to? Off the tabs, reached from the more screen ("‹ 더보기").
// Not kept in the offline snapshot (SP5 keeps `GET /today` only): offline says so in words.
export function Status() {
  const { state, recheck } = useConnection();
  const { result, refresh } = usePolling<StatusData>(() => apiGet<StatusData>("/status", "Status"));
  const offline = state?.kind === "offline" || result?.kind === "offline";

  let body;
  if (result?.kind === "ok" && !offline) {
    body = (
      <>
        <Level data={result.data} />
        <Stats stats={result.data.stats} body={result.data.body} />
        {result.data.innate && <Innate items={result.data.innate} />}
        <Recent stats={result.data.stats} />
        <StatusMoments moments={result.data.moments} hiddenCount={result.data.moments_hidden} onChanged={() => void refresh()} />
      </>
    );
  } else if (offline) {
    body = <p className={styles.empty}>{T.offline}</p>;
  } else if (result === null) {
    body = (
      <Group>
        <Skeleton size="row" />
        <Skeleton size="row" />
      </Group>
    );
  } else {
    body = (
      <Group>
        <BlockError code={result.kind === "error" ? result.code : result.kind} onRetry={() => void refresh()} />
      </Group>
    );
  }

  return (
    <main className={`${page.main} ${styles.main}`}>
      <nav className={styles.bar}>
        <Link href="/more/" className={styles.back}>
          {T.back}
        </Link>
      </nav>
      <LargeTitle title={T.heading} />
      {offline && <OfflineNotice savedAt={null} onRetry={() => void recheck()} />}
      {body}
    </main>
  );
}
