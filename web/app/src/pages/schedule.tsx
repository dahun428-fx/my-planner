import Head from "next/head";
import { useRouter } from "next/router";
import { TabBar } from "../components/TabBar";
import { copy } from "../lib/copy";
import { Schedule } from "../screens/Schedule";

// `/schedule/` (SP9 9.2): the schedule tab. `?date=YYYY-MM-DD` opens that day (a reminder push opens it).
// The screen waits for the address (a static export knows the query only once the router is ready), so
// a push to another week does not first read this week.
export default function Page() {
  const { isReady } = useRouter();
  return (
    <>
      <Head>
        <title>{copy.schedule.title}</title>
      </Head>
      {isReady && <Schedule />}
      <TabBar current="schedule" />
    </>
  );
}
