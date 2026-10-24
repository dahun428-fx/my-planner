import Head from "next/head";
import { LargeTitle } from "../components/LargeTitle";
import { TabBar } from "../components/TabBar";
import { copy } from "../lib/copy";
import page from "../styles/page.module.css";

export default function Page() {
  return (
    <>
      <Head>
        <title>{copy.tabs.activity}</title>
      </Head>
      <main className={page.main}>
        <LargeTitle title={copy.tabs.activity} />
      </main>
      <TabBar current="activity" />
    </>
  );
}
