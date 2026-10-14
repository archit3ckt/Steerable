import { unstable_rethrow } from "next/navigation";
import { AgentError } from "./backend/agent";
import type { CompanyBackend } from "./backend/types";

/**
 * The body of the host's runChangesUrl route (GET ?run=<id>&table=<id>&after=<n>&limit=), which a
 * run's change table fetches a page at a time as the owner opens it and asks for more:
 *
 *   export const GET = (request: Request) => runChangesResponse(getBackend, request);
 */
export async function runChangesResponse(backend: () => Promise<CompanyBackend>, request: Request): Promise<Response> {
  const params = new URL(request.url).searchParams;
  const run = params.get("run") ?? "";
  if (!/^[\w-]{1,60}$/.test(run)) return Response.json({ error: "Which run?" }, { status: 400 });
  const table = /^[\w-]{1,40}$/.test(params.get("table") ?? "") ? params.get("table")! : undefined;
  const after = Math.max(0, Math.floor(Number(params.get("after")) || 0));
  const limit = Math.min(200, Math.max(1, Number(params.get("limit")) || 50));
  try {
    const changes = await (await backend()).runChanges(run, { table, after: after || undefined, limit });
    return Response.json(changes, { headers: { "Cache-Control": "no-store" } });
  } catch (error) {
    unstable_rethrow(error); // signed out: the host's redirect to its sign-in page
    if (error instanceof AgentError) return Response.json({ error: error.message }, { status: error.status });
    throw error;
  }
}
