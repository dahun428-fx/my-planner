import Head from "next/head";
import { useRouter } from "next/router";
import { useState } from "react";
import { copy } from "../../lib/copy";
import { MemoEditor } from "../../screens/MemoEditor";

// `/memos/view/?id=7`, a new memo `/memos/view/?new=1` (SP9 9.4). Off the tab bar: the tool row
// sits at the bottom, above the keyboard. Anything but a plain number is a memo that is not there.
// A new memo, once made, moves the address to ?id= (shallow); the screen stays the same one.
export default function Page() {
  const { query, isReady } = useRouter();
  const [created, setCreated] = useState<number | null>(null);
  if (!isReady) return null;
  const raw = typeof query.id === "string" ? query.id : "";
  const id = /^\d+$/.test(raw) ? Number(raw) : query.new === "1" ? null : Number.NaN;
  const key = id === null || id === created ? "new" : String(id);
  return (
    <>
      <Head>
        <title>{copy.memos.title}</title>
      </Head>
      <MemoEditor key={key} id={key === "new" ? null : id} onCreated={setCreated} />
    </>
  );
}
