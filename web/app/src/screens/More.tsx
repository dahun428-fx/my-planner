import { useEffect, useState } from "react";
import { Group } from "../components/Group";
import { Icon } from "../components/icons";
import { LargeTitle } from "../components/LargeTitle";
import { Row } from "../components/Row";
import { copy } from "../lib/copy";
import { useConnection } from "../lib/ConnectionProvider";
import { HAS_STATUS_PAGE } from "../lib/nav";
import page from "../styles/page.module.css";

const MATE_KEY = "mp.mate";

// SP9 9.1: off the tabs, large title "더보기" and no back link; one grouped list. "상태창" only
// while the build has /status/ (SP8). Each screen under it goes back with "‹ 더보기".
export function More({ hasStatus = HAS_STATUS_PAGE }: { hasStatus?: boolean }) {
  // SP12 11.2: "운동" only while the BE has the workout mate (`features`); offline keeps the last answer's.
  const { state } = useConnection();
  // The last answer is kept on the device, so a cold start without the laptop still shows the row (and the saved screen).
  const [hasMate, setHasMate] = useState(() => {
    try {
      return localStorage.getItem(MATE_KEY) === "1";
    } catch {
      return false;
    }
  });
  useEffect(() => {
    if (state?.kind !== "online") return;
    const has = state.health.features?.includes("mate") ?? false;
    setHasMate(has);
    try {
      if (has) localStorage.setItem(MATE_KEY, "1");
      else localStorage.removeItem(MATE_KEY);
    } catch {
      // blocked storage: the row only follows the live answer
    }
  }, [state]);
  const rows: { title: string; href: string }[] = [
    { title: copy.more.settings, href: "/settings/" },
    { title: copy.more.activity, href: "/activity/" },
    { title: copy.more.habits, href: "/habits/" },
    ...(hasStatus ? [{ title: copy.more.status, href: "/status/" }] : []),
    ...(hasMate ? [{ title: copy.more.workout, href: "/workout/" }] : []),
    { title: copy.more.connect, href: "/connect/" },
    { title: copy.more.devices, href: "/devices/" }, // device pairing spec 5.1
  ];
  return (
    <main className={page.main}>
      <LargeTitle title={copy.more.title} />
      <Group>
        {rows.map((r) => (
          <Row key={r.href} title={r.title} href={r.href} trailing={<Icon name="chevron" />} />
        ))}
      </Group>
    </main>
  );
}
