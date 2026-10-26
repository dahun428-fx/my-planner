import Head from "next/head";
import { TabBar } from "../components/TabBar";
import { copy } from "../lib/copy";
import { More } from "../screens/More";

// `/more/` (SP9 9.1): off the tabs, but the tab bar shows, with no tab marked.
export default function Page() {
  return (
    <>
      <Head>
        <title>{copy.more.title}</title>
      </Head>
      <More />
      <TabBar />
    </>
  );
}
