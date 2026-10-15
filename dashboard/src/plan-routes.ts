import { unstable_rethrow } from "next/navigation";
import { AgentError } from "./backend/agent";
import type { CompanyBackend } from "./backend/types";

/**
 * The body of the host's plansUrl route (GET ?id=<plan>&v=<version>), which the chat fetches when the
 * owner opens a plan a reply saved: that version's text and what it changed, the plan's title and its
 * current version (it may have changed since).
 *
 *   export const GET = (request: Request) => planResponse(getBackend, request);
 */
export async function planResponse(backend: () => Promise<CompanyBackend>, request: Request): Promise<Response> {
  const params = new URL(request.url).searchParams;
  const id = params.get("id") ?? "";
  if (!/^pl[0-9a-f]{4,20}$/.test(id)) return Response.json({ error: "Which plan?" }, { status: 400 });
  try {
    const b = await backend();
    const plan = await b.plan(id);
    if (!plan) return Response.json({ error: "That plan was removed." }, { status: 404 });
    const asked = Math.trunc(Number(params.get("v")));
    const version = await b.planVersion(id, asked > 0 ? asked : plan.version);
    if (!version) return Response.json({ error: "There's no such version." }, { status: 404 });
    return Response.json({ id, title: plan.title, current: plan.version, version }, { headers: { "Cache-Control": "no-store" } });
  } catch (error) {
    unstable_rethrow(error); // signed out: the host's redirect to its sign-in page
    if (error instanceof AgentError) return Response.json({ error: error.message }, { status: error.status });
    throw error;
  }
}
