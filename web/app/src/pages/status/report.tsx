import Head from "next/head";
import { type ComponentType, useEffect, useState } from "react";
import { BlockError } from "../../components/BlockError";
import { Group } from "../../components/Group";
import { Skeleton } from "../../components/Skeleton";
import { copyPanel } from "../../lib/copyPanel";
import page from "../../styles/page.module.css";

// The screen and its stylesheet are one chunk, loaded by a bare import() (as the chat sheet's): its
// CSS then arrives as a <link> (CSP style-src 'self'), not as the inline <style> a page's own CSS
// becomes on a client move, and LifeReport.module.css stays out of _app (the first screen's budget).
const reportChunk = {
  load: () => import("../../screens/panelScreens"),
};

// `/status/report/` (SP15 10장): off the tabs, reached from the status screen's "인생 리포트" line.
export default function Page() {
  const [Screen, setScreen] = useState<ComponentType | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    if (Screen || failed) return;
    let live = true;
    reportChunk
      .load()
      .then((m) => live && setScreen(() => m.LifeReport))
      .catch(() => live && setFailed(true));
    return () => {
      live = false;
    };
  }, [Screen, failed]);
  return (
    <>
      <Head>
        <title>{copyPanel.report.title}</title>
      </Head>
      {Screen ? (
        <Screen />
      ) : (
        <main className={page.main}>
          <Group>{failed ? <BlockError code="chunk" onRetry={() => setFailed(false)} /> : <Skeleton size="row" />}</Group>
        </main>
      )}
    </>
  );
}
