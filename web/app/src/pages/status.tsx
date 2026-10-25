import Head from "next/head";
import { copy } from "../lib/copy";
import { Status } from "../screens/Status";

// `/status/` (SP8 10.2): off the tabs, like the habits screen, so no tab bar. Reached from the more screen.
export default function Page() {
  return (
    <>
      <Head>
        <title>{copy.statusScreen.heading}</title>
      </Head>
      <Status />
    </>
  );
}
