import dynamic from "next/dynamic";

// Data screens render in the browser only (spec 13.1: no server rendering of data).
const HealthScreen = dynamic(() => import("../screens/HealthScreen"), { ssr: false });

export default function Home() {
  return <HealthScreen />;
}
