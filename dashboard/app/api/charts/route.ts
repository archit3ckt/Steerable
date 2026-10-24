import { chartResponse } from "../../../src/chart-routes";
import { backend } from "../../../local/host";

/** A chart in a reply or a plan (a ```chart block), counted from the library now. */
export const GET = (request: Request) => chartResponse(backend, request);
