import { copyPanel, type ReportAxis } from "../../lib/copyPanel";

// SP15 10장: the six axes a report scores and a lever moves (the BE's LEVER_AXES order). The three
// innate axes are in the stored scores too, but not on this screen (the status screen shows them).
export const REPORT_AXES = Object.keys(copyPanel.report.axes) as ReportAxis[];
export const axisLabel = (axis: ReportAxis) => copyPanel.report.axes[axis];
