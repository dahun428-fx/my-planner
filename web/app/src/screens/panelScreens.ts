// SP15: the life manager's two late screens in one chunk (the life report page and the more screen's
// "내가 한 말" list), loaded by a bare import(). Their stylesheets then come with that chunk as a <link>
// (CSP style-src 'self'), never with _app; and one chunk is one entry in the webpack runtime's maps, which
// are part of the first screen's load (the 180KB budget), where two chunks would be two.
export { LifeReport } from "./LifeReport";
export { OwnerStatements } from "./OwnerStatements";
