import { setupServer } from "msw/node";
import { handlers } from "./handlers";

export { BASE } from "./handlers";
export const server = setupServer(...handlers);
