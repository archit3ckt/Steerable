import { planResponse } from "../../../src/plan-routes";
import { backend } from "../../../local/host";

/** A plan's version, for the chat: the plans a reply saved open beside it. */
export const GET = (request: Request) => planResponse(backend, request);
