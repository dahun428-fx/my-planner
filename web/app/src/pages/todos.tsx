import Head from "next/head";
import { LargeTitle } from "../components/LargeTitle";
import { TabBar } from "../components/TabBar";
import { copy } from "../lib/copy";
import page from "../styles/page.module.css";

export default function Page() {
  return (
    <>
      <Head>
        <title>{copy.tabs.todos}</title>
      </Head>
      <main className={page.main}>
        <LargeTitle title={copy.tabs.todos} />
      </main>
      <TabBar current="todos" />
    </>
  );
}
