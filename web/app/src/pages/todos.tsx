import Head from "next/head";
import { useRouter } from "next/router";
import { TabBar } from "../components/TabBar";
import { copy } from "../lib/copy";
import { Todos, type TodosTab } from "../screens/Todos";

const TABS: readonly string[] = ["day", "week", "month", "quarter", "year"];

export default function Page() {
  const { query } = useRouter();
  const q = typeof query.tab === "string" ? query.tab : "week";
  const tab = (TABS.includes(q) ? q : "week") as TodosTab;
  return (
    <>
      <Head>
        <title>{copy.tabs.todos}</title>
      </Head>
      <Todos tab={tab} />
      <TabBar current="todos" />
    </>
  );
}
