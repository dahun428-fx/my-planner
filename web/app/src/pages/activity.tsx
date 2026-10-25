import Head from "next/head";
import { TabBar } from "../components/TabBar";
import { copy } from "../lib/copy";
import { Activity } from "../screens/Activity";

// `/activity/` (SP9 9.1): off the tabs since SP9-04, reached from the more screen. The tab bar
// shows with no tab marked.
export default function Page() {
  return (
    <>
      <Head>
        <title>{copy.activity.title}</title>
      </Head>
      <Activity />
      <TabBar />
    </>
  );
}
