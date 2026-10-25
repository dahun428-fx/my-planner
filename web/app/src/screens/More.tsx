import { Group } from "../components/Group";
import { Icon } from "../components/icons";
import { LargeTitle } from "../components/LargeTitle";
import { Row } from "../components/Row";
import { copy } from "../lib/copy";
import { HAS_STATUS_PAGE } from "../lib/nav";
import page from "../styles/page.module.css";

// SP9 9.1: off the tabs, large title "더보기" and no back link; one grouped list. "상태창" only
// while the build has /status/ (SP8). Each screen under it goes back with "‹ 더보기".
export function More({ hasStatus = HAS_STATUS_PAGE }: { hasStatus?: boolean }) {
  const rows: { title: string; href: string }[] = [
    { title: copy.more.settings, href: "/settings/" },
    { title: copy.more.activity, href: "/activity/" },
    { title: copy.more.habits, href: "/habits/" },
    ...(hasStatus ? [{ title: copy.more.status, href: "/status/" }] : []),
    { title: copy.more.connect, href: "/connect/" },
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
