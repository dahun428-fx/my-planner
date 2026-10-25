import Head from "next/head";
import { TabBar } from "../components/TabBar";
import { copy } from "../lib/copy";
import { Schedule } from "../screens/Schedule";

// `/schedule/` (SP9 9.2): the schedule tab. `?date=YYYY-MM-DD` opens that day (a reminder push opens it).
export default function Page() {
  return (
    <>
      <Head>
        <title>{copy.schedule.title}</title>
      </Head>
      <Schedule />
      <TabBar current="schedule" />
    </>
  );
}
