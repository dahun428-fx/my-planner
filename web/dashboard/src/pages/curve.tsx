import dynamic from "next/dynamic";

// Data screens render in the browser only (spec 13.1); Recharts is loaded with the screen, never on a server.
const CurveScreen = dynamic(() => import("../screens/CurveScreen"), { ssr: false });

export default function LifeCurve() {
  return <CurveScreen />;
}
