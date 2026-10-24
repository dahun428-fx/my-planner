import Head from "next/head";
import Link from "next/link";
import { LargeTitle } from "../components/LargeTitle";
import { copy } from "../lib/copy";
import page from "../styles/page.module.css";

// Own 404 so the export has no Next default page (it carries inline styles, which CSP blocks).
export default function NotFound() {
  return (
    <>
      <Head>
        <title>{copy.appName}</title>
      </Head>
      <main className={page.main}>
        <LargeTitle title={copy.errors.notFound} />
        <p className={page.lead}>
          <Link href="/">{copy.errors.goToday}</Link>
        </p>
      </main>
    </>
  );
}
