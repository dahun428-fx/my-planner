import { setupServer } from "msw/node";
import { handlers } from "./handlers";

export { BASE, ORIGIN } from "./handlers";
export const server = setupServer(...handlers);
