import Head from "next/head";
import { TabBar } from "../components/TabBar";
import { copy } from "../lib/copy";
import { Activity } from "../screens/Activity";

export default function Page() {
  return (
    <>
      <Head>
        <title>{copy.tabs.activity}</title>
      </Head>
      <Activity />
      <TabBar current="activity" />
    </>
  );
}
