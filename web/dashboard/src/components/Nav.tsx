import Link from "next/link";
import { useRouter } from "next/router";
import { NAV_TEXT } from "../lib/labels";

const LINKS = [
  { href: "/", label: NAV_TEXT.status },
  { href: "/settings/", label: NAV_TEXT.settings },
] as const;

const same = (a: string, b: string) => a.replace(/\/+$/, "") === b.replace(/\/+$/, "");

/** Wordmark and the screens. Later screens (할 일, 인생곡선, 상태창) add a link each. */
export function Nav() {
  const { asPath } = useRouter();
  const path = asPath.split(/[?#]/)[0];
  return (
    <nav className="nav" aria-label={NAV_TEXT.label}>
      <Link href="/" className="wordmark">
        <svg className="mark" viewBox="0 0 16 16" aria-hidden="true" focusable="false">
          <rect x="1" y="1" width="14" height="14" rx="4" />
          <path d="M4.5 10.5 7 8l2 2 2.5-4" />
        </svg>
        {NAV_TEXT.brand}
      </Link>
      <ul>
        {LINKS.map((l) => (
          <li key={l.href}>
            <Link href={l.href} aria-current={same(path, l.href) ? "page" : undefined}>
              {l.label}
            </Link>
          </li>
        ))}
      </ul>
    </nav>
  );
}
