import Head from "next/head";
import { TabBar } from "../components/TabBar";
import { copy } from "../lib/copy";
import { Memos } from "../screens/Memos";

// `/memos/` (SP9 9.4): the memos tab.
export default function Page() {
  return (
    <>
      <Head>
        <title>{copy.memos.title}</title>
      </Head>
      <Memos />
      <TabBar current="memos" />
    </>
  );
}
