import Head from "next/head";
import { TabBar } from "../components/TabBar";
import { copy } from "../lib/copy";
import { Devices } from "../screens/Devices";

// `/devices/` (device pairing spec 5.1): reached from the more screen, like settings. No tab marked.
export default function Page() {
  return (
    <>
      <Head>
        <title>{copy.devices.title}</title>
      </Head>
      <Devices />
      <TabBar />
    </>
  );
}
