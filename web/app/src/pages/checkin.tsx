import Head from "next/head";
import { useRouter } from "next/router";
import { copy } from "../lib/copy";
import { Checkin } from "../screens/Checkin";

// `/checkin/?id=341`. Anything but a plain number is NaN, and the screen sends the person back to Today.
export default function Page() {
  const { query, isReady } = useRouter();
  if (!isReady) return null;
  const raw = typeof query.id === "string" ? query.id : "";
  const id = /^\d+$/.test(raw) ? Number(raw) : Number.NaN;
  return (
    <>
      <Head>
        <title>{copy.checkin.title}</title>
      </Head>
      <Checkin id={id} />
    </>
  );
}
