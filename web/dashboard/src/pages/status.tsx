import dynamic from "next/dynamic";

// Data screens render in the browser only (spec 13.1: no server rendering of data).
const StatusScreen = dynamic(() => import("../screens/StatusScreen"), { ssr: false });

export default function StatusWindow() {
  return <StatusScreen />;
}
