import Head from "next/head";
import { TabBar } from "../components/TabBar";
import { copy } from "../lib/copy";
import { Today } from "../screens/Today";

export default function Page() {
  return (
    <>
      <Head>
        <title>{copy.tabs.today}</title>
      </Head>
      <Today />
      <TabBar current="today" />
    </>
  );
}
