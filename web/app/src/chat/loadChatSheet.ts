// The chat sheet's chunk (the AI SDK with it) is loaded the first time the sheet opens, so it stays
// out of the first screen's bundle (spec 9: 180KB). An object so a test can make the import fail.
export const chatSheetChunk = {
  load: () => import("./ChatSheet"),
};
