import { traceResponse } from "../../../src/trace-routes";
import { backend } from "../../../local/host";

/** A practice or watched run, step by step (?id=), and its pictures (&shot=). */
export const GET = (request: Request) => traceResponse(backend, request);
