import dynamic from "next/dynamic";

// Data screens render in the browser only (spec 13.1: no server rendering of data).
const TasksScreen = dynamic(() => import("../screens/TasksScreen"), { ssr: false });

export default function Tasks() {
  return <TasksScreen />;
}
