import { runChangesResponse } from "../../../../src/run-routes";
import { backend } from "../../../../local/host";

/** What a routine run or chat turn changed in the library, a page of rows at a time. */
export const GET = (request: Request) => runChangesResponse(backend, request);
