import { checkResponse } from "../../../src/check-routes";
import { backend } from "../../../local/host";

/** A reply's test, which the chat polls while it runs. */
export const GET = (request: Request) => checkResponse(backend, request);
