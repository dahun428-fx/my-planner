import { useRouter } from "next/router";
import { type ComponentType, useEffect, useId, useState } from "react";
import { type ApiResult, getAgentNotes } from "../api/client";
import type { AgentNotes } from "../api/types.gen";
import { AgentNoteLines } from "../components/AgentNoteLines";
import { BlockError } from "../components/BlockError";
import { Group } from "../components/Group";
import { Icon } from "../components/icons";
import { LargeTitle } from "../components/LargeTitle";
import { Row } from "../components/Row";
import { Skeleton } from "../components/Skeleton";
import { copy } from "../lib/copy";
import { copyPanel } from "../lib/copyPanel";
import { useConnection } from "../lib/ConnectionProvider";
import { HAS_STATUS_PAGE } from "../lib/nav";
import page from "../styles/page.module.css";
import styles from "./More.module.css";

const MATE_KEY = "mp.mate";

// "2026-10-31" -> "10/31".
const monthDay = (day: string) => {
  const [, m, d] = day.split("-");
  return `${Number(m)}/${Number(d)}`;
};

// SP14 10장: "비서 메모" opens in place (no page of its own): the partners' notes of the last 7 days.
function AgentNotesRow() {
  const [open, setOpen] = useState(false);
  const [result, setResult] = useState<ApiResult<AgentNotes> | null>(null);
  const id = useId();
  const read = () => {
    setResult(null);
    void getAgentNotes(7).then(setResult);
  };
  const toggle = () => {
    if (!open) read();
    setOpen((o) => !o);
  };
  let panel: React.ReactNode = null;
  if (open) {
    if (result === null) panel = <Skeleton size="row" />;
    else if (result.kind !== "ok") panel = <BlockError code={result.kind === "error" ? result.code : result.kind} onRetry={read} />;
    else if (result.data.notes.length === 0) panel = <p className={styles.empty}>{copy.more.agentNotesEmpty}</p>;
    else panel = <AgentNoteLines notes={result.data.notes.map((n) => ({ agent: n.agent, text: n.text, meta: monthDay(n.day) }))} />;
  }
  return (
    <>
      <Row
        title={copy.more.agentNotes}
        onPress={toggle}
        expanded={open}
        controls={open ? id : undefined}
        trailing={
          <span className={`${styles.chevron} ${open ? styles.open : ""}`}>
            <Icon name="chevron" />
          </span>
        }
      />
      {/* Only while open, so the rows around a closed one keep their hairline (Row: .row + .row). */}
      {open && (
        <div id={id} className={styles.panel}>
          {panel}
        </div>
      )}
    </>
  );
}

// SP15 5.4: the list is its own chunk, loaded on the first open, so its stylesheet comes with it as a
// <link> (CSP style-src 'self') and never adds to _app (the first screen's budget). An object so a
// test can make the import fail.
export const statementsChunk = {
  load: () => import("./panelScreens"),
};
const STATEMENTS_HASH = "#statements";
const atStatements = (asPath: string) =>
  asPath.endsWith(STATEMENTS_HASH) || (typeof window !== "undefined" && window.location.hash === STATEMENTS_HASH);

// SP15 5.4: "내가 한 말" opens in place like "비서 메모". An evidence link (`/more/#statements`) comes in
// with it open; `id="statements"` sits on the row's title, so the move scrolls to the row.
function StatementsRow() {
  const { asPath } = useRouter();
  const [open, setOpen] = useState(() => atStatements(asPath));
  const [List, setList] = useState<ComponentType | null>(null);
  const [failed, setFailed] = useState(false);
  const id = useId();
  useEffect(() => {
    if (!atStatements(asPath)) return;
    setOpen(true);
    // On a cold start the row comes after /health, too late for the browser's own jump to the hash.
    document.getElementById("statements")?.scrollIntoView?.({ block: "center" });
  }, [asPath]);
  useEffect(() => {
    if (!open || List || failed) return;
    let live = true;
    statementsChunk
      .load()
      .then((m) => live && setList(() => m.OwnerStatements))
      .catch(() => live && setFailed(true));
    return () => {
      live = false;
    };
  }, [open, List, failed]);
  let panel: React.ReactNode = <Skeleton size="row" />;
  if (List) panel = <List />;
  else if (failed) panel = <BlockError code="chunk" onRetry={() => setFailed(false)} />;
  return (
    <>
      <Row
        title={<span id="statements">{copyPanel.statements.title}</span>}
        onPress={() => setOpen((o) => !o)}
        expanded={open}
        controls={open ? id : undefined}
        trailing={
          <span className={`${styles.chevron} ${open ? styles.open : ""}`}>
            <Icon name="chevron" />
          </span>
        }
      />
      {open && (
        <div id={id} className={styles.panel}>
          {panel}
        </div>
      )}
    </>
  );
}

// SP9 9.1: off the tabs, large title "더보기" and no back link; one grouped list. "상태창" only
// while the build has /status/ (SP8). Each screen under it goes back with "‹ 더보기".
export function More({ hasStatus = HAS_STATUS_PAGE }: { hasStatus?: boolean }) {
  // SP12 11.2: "운동" only while the BE has the workout mate (`features`); offline keeps the last answer's.
  const { state } = useConnection();
  // The last answer is kept on the device, so a cold start without the laptop still shows the row (and the saved screen).
  const [storedMate, setStoredMate] = useState(() => {
    try {
      return localStorage.getItem(MATE_KEY) === "1";
    } catch {
      return false;
    }
  });
  // SP14 10장: "비서 메모" only while the BE says `agent_notes` (the notes are read live, so offline has no row).
  const hasNotes = state?.kind === "online" && (state.health.features?.includes("agent_notes") ?? false);
  // SP15 5.4: "내가 한 말" only while the BE has the life manager (read live, like the notes).
  const hasStatements = state?.kind === "online" && (state.health.features?.includes("manager") ?? false);
  // Online, the live answer decides in the same render as "비서 메모" (no frame with notes but no "운동").
  const hasMate = state?.kind === "online" ? (state.health.features?.includes("mate") ?? false) : storedMate;
  useEffect(() => {
    if (state?.kind !== "online") return;
    const has = state.health.features?.includes("mate") ?? false;
    setStoredMate(has);
    try {
      if (has) localStorage.setItem(MATE_KEY, "1");
      else localStorage.removeItem(MATE_KEY);
    } catch {
      // blocked storage: the row only follows the live answer
    }
  }, [state]);
  const link = (title: string, href: string) => <Row key={href} title={title} href={href} trailing={<Icon name="chevron" />} />;
  return (
    <main className={page.main}>
      <LargeTitle title={copy.more.title} />
      <Group>
        {link(copy.more.settings, "/settings/")}
        {link(copy.more.activity, "/activity/")}
        {link(copy.more.habits, "/habits/")}
        {hasStatus && link(copy.more.status, "/status/")}
        {hasMate && link(copy.more.workout, "/workout/")}
        {hasNotes && <AgentNotesRow />}
        {hasStatements && <StatementsRow />}
        {link(copy.more.connect, "/connect/")}
        {link(copy.more.devices, "/devices/") /* device pairing spec 5.1 */}
      </Group>
    </main>
  );
}
