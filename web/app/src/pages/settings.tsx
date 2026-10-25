import Head from "next/head";
import { TabBar } from "../components/TabBar";
import { copy } from "../lib/copy";
import { Settings } from "../screens/Settings";

// `/settings/` (SP9 9.1): off the tabs since SP9-07, reached from the more screen. No tab marked.
export default function Page() {
  return (
    <>
      <Head>
        <title>{copy.settings.title}</title>
      </Head>
      <Settings />
      <TabBar />
    </>
  );
}
