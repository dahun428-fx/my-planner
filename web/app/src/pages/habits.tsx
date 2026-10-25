import Head from "next/head";
import { copy } from "../lib/copy";
import { Habits } from "../screens/Habits";

// `/habits/` (SP7 6.2): off the tabs, like the check-in detail, so no tab bar.
export default function Page() {
  return (
    <>
      <Head>
        <title>{copy.habits.heading}</title>
      </Head>
      <Habits />
    </>
  );
}
