import Head from "next/head";
import { standingCopy } from "../../lib/copyStanding";
import { Standing } from "../../screens/Standing";

// `/status/standing/` (SP13 10.3): off the tabs, reached from the status screen. Its own page chunk,
// so the first screen's load does not carry it; only its stylesheet comes with _app (CSP).
export default function Page() {
  return (
    <>
      <Head>
        <title>{standingCopy.title}</title>
      </Head>
      <Standing />
    </>
  );
}
