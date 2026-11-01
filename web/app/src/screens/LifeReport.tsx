import Link from "next/link";
import { type ReactNode, useCallback, useEffect, useState } from "react";
import type { ApiResult } from "../api/client";
import { getLifeReport, getLifeReports, getPanelSuggestions } from "../api/panel";
import type { LifeReportBody, LifeReportOut, LifeReports } from "../api/types.gen";
import { BlockError } from "../components/BlockError";
import { Group } from "../components/Group";
import { LargeTitle } from "../components/LargeTitle";
import { OfflineNotice } from "../components/OfflineNotice";
import { Skeleton } from "../components/Skeleton";
import { useConnection } from "../lib/ConnectionProvider";
import { copy } from "../lib/copy";
import { copyPanel } from "../lib/copyPanel";
import { standingCopy } from "../lib/copyStanding";
import { formatKst } from "../lib/time";
import page from "../styles/page.module.css";
import styles from "./LifeReport.module.css";
import { LeverMap } from "./report/LeverMap";
import { Radar } from "./report/Radar";
import { Roadmap } from "./report/Roadmap";
import { ScoreDumbbell } from "./report/ScoreDumbbell";

const T = copyPanel.report;
const S = T.sections;

// "2026-10-31T11:00:00Z" -> "2026.10.31" (the day in Seoul).
const dateOf = (iso: string) => formatKst(iso, "date").replaceAll("-", ".");
const errCode = (r: ApiResult<unknown>) => (r.kind === "error" ? r.code : r.kind);

function Body({ r, titles, today }: { r: LifeReportBody; titles: ReadonlyMap<number, string>; today: string }) {
  // "이번 주": the suggestions' titles, in the report's order; an id the BE no longer lists drops its line.
  const week = r.this_week.flatMap((id) => {
    const t = titles.get(id);
    return t === undefined ? [] : [{ id, t }];
  });
  return (
    <>
      <Group heading={S.summary}>
        <div className={styles.block}>
          <p className={styles.lead}>{r.summary.line}</p>
          <ol className={styles.bullets}>
            {r.summary.paths.map((p, i) => (
              <li key={i}>{p}</li>
            ))}
          </ol>
        </div>
      </Group>
      <Group heading={S.scores}>
        <ScoreDumbbell scores={r.scores} />
        <div className={styles.chartBox}>
          <Radar scores={r.scores} />
          <p className={styles.legend}>
            <span className={styles.keyNational} aria-hidden="true" />
            {standingCopy.legendNational}
            <span className={styles.keyPeer} aria-hidden="true" />
            {standingCopy.legendPeer}
          </p>
        </div>
      </Group>
      <Group heading={S.levers}>
        <div className={styles.block}>
          <LeverMap levers={r.levers} />
        </div>
      </Group>
      <Group heading={S.experts}>
        {r.experts.map((e) => (
          <details key={e.expert} className={styles.expert} data-expert={e.expert}>
            <summary>
              <span className={styles.expertName}>{copyPanel.experts[e.expert]}</span>
              <span className={styles.name}>{e.line}</span>
            </summary>
            <div className={styles.expertBody}>
              <ul className={styles.bullets}>
                {e.prescriptions.map((p, i) => (
                  <li key={i}>{p}</li>
                ))}
              </ul>
              <p className={styles.sub}>{T.avoid}</p>
              <ul className={styles.bullets}>
                {e.avoid.map((p, i) => (
                  <li key={i}>{p}</li>
                ))}
              </ul>
            </div>
          </details>
        ))}
      </Group>
      <Group heading={S.scenario}>
        <div className={`${styles.block} ${styles.scenario}`}>
          {r.scenario.estimate && (
            <span>
              <span className={styles.tag}>{T.estimate}</span>
            </span>
          )}
          <div>
            <h3>{T.doIt}</h3>
            <p>{r.scenario.do}</p>
          </div>
          <div>
            <h3>{T.dontDo}</h3>
            <p>{r.scenario.dont}</p>
          </div>
        </div>
      </Group>
      <Group heading={S.roadmap}>
        <Roadmap tracks={r.roadmap} today={today} />
      </Group>
      {week.length > 0 && (
        <Group heading={S.thisWeek}>
          <ul className={styles.list}>
            {week.map((w) => (
              <li key={w.id} className={styles.row}>
                <span className={styles.name}>{w.t}</span>
              </li>
            ))}
          </ul>
        </Group>
      )}
      {r.questions.length > 0 && (
        <Group heading={S.questions}>
          <ul className={styles.list}>
            {r.questions.map((q, i) => (
              <li key={i} className={styles.row}>
                <span className={styles.name}>{q}</span>
              </li>
            ))}
          </ul>
        </Group>
      )}
      <p className={styles.closing}>{r.closing}</p>
    </>
  );
}

function Past({ list, current, onPick }: { list: LifeReports["items"]; current: number; onPick(id: number): void }) {
  return (
    <Group heading={T.past}>
      <ul className={styles.list}>
        {list.map((it) => (
          <li key={it.id}>
            <button
              type="button"
              className={styles.date}
              aria-current={it.id === current ? "true" : undefined}
              onClick={() => it.id !== current && onPick(it.id)}
            >
              {dateOf(it.created_at)}
            </button>
          </li>
        ))}
      </ul>
    </Group>
  );
}

// SP15 10장 `/status/report/`: the newest life report (or a past one picked from the list). The score
// numbers are the copy saved with the report. Off the tabs, reached from the status screen; like it, not
// kept offline. This screen is its own chunk (pages/status/report.tsx loads it), stylesheet included.
export function LifeReport() {
  const { state, recheck } = useConnection();
  const [list, setList] = useState<ApiResult<LifeReports> | null>(null);
  const [current, setCurrent] = useState<number | null>(null);
  const [report, setReport] = useState<ApiResult<LifeReportOut> | null>(null);
  const [titles, setTitles] = useState<ReadonlyMap<number, string> | null>(null);

  const readList = useCallback(() => {
    setList(null);
    void getLifeReports().then((r) => {
      setList(r);
      if (r.kind === "ok" && r.data.items.length > 0) setCurrent((c) => c ?? r.data.items[0].id);
    });
  }, []);
  useEffect(readList, [readList]);

  const readReport = useCallback((id: number) => {
    setReport(null);
    void getLifeReport(id).then(setReport);
  }, []);
  useEffect(() => {
    if (current !== null) readReport(current);
  }, [current, readReport]);

  // The "이번 주" titles: GET /panel/suggestions once, the first time a report names any.
  const needsTitles = report?.kind === "ok" && report.data.report.this_week.length > 0 && titles === null;
  useEffect(() => {
    if (!needsTitles) return;
    void getPanelSuggestions().then((r) => setTitles(new Map(r.kind === "ok" ? r.data.items.map((s) => [s.id, s.title]) : [])));
  }, [needsTitles]);

  const offline = state?.kind === "offline" || list?.kind === "offline";
  let body: ReactNode;
  if (offline) body = <p className={styles.empty}>{copy.statusScreen.offline}</p>;
  else if (list === null) body = <Skeleton size="row" />;
  else if (list.kind !== "ok") body = <Group><BlockError code={errCode(list)} onRetry={readList} /></Group>;
  else if (list.data.items.length === 0) body = <p className={styles.empty}>{T.empty}</p>;
  else {
    let main: ReactNode;
    if (report === null || needsTitles) main = <Skeleton size="row" />;
    else if (report.kind !== "ok") main = <Group><BlockError code={errCode(report)} onRetry={() => current !== null && readReport(current)} /></Group>;
    else main = <Body r={report.data.report} titles={titles ?? new Map()} today={formatKst(new Date().toISOString(), "date")} />;
    body = (
      <>
        {main}
        {current !== null && <Past list={list.data.items} current={current} onPick={setCurrent} />}
      </>
    );
  }

  return (
    <main className={`${page.main} ${styles.main}`}>
      <nav className={styles.nav}>
        <Link href="/status/" className={styles.back}>
          {standingCopy.back}
        </Link>
      </nav>
      <LargeTitle title={T.title} />
      {offline && <OfflineNotice savedAt={null} onRetry={() => void recheck()} />}
      {body}
    </main>
  );
}
