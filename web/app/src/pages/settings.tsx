import Head from "next/head";
import { TabBar } from "../components/TabBar";
import { copy } from "../lib/copy";
import { Settings } from "../screens/Settings";

export default function Page() {
  return (
    <>
      <Head>
        <title>{copy.tabs.settings}</title>
      </Head>
      <Settings />
      <TabBar current="settings" />
    </>
  );
}
