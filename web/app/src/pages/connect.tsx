import Head from "next/head";
import { copy } from "../lib/copy";
import { Connect } from "../screens/Connect";

export default function Page() {
  return (
    <>
      <Head>
        <title>{copy.connect.title}</title>
      </Head>
      <Connect />
    </>
  );
}
