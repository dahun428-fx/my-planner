import Head from "next/head";
import { copy } from "../lib/copy";
import { Workout } from "../screens/Workout";

// `/workout/` (SP12 11.2): off the tabs, reached from the more screen, so no tab bar.
export default function Page() {
  return (
    <>
      <Head>
        <title>{copy.workout.title}</title>
      </Head>
      <Workout />
    </>
  );
}
