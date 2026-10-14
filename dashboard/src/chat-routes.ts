import { unstable_rethrow } from "next/navigation";
import { AgentError } from "./backend/agent";
import type { CompanyBackend } from "./backend/types";

/**
 * The body of the host's chatPageUrl route (GET ?before=|after=|around=<id>&limit=), which the
 * chat fetches as the owner scrolls up and while it waits for a reply:
 *
 *   export const GET = (request: Request) => chatPageResponse(getBackend, request);
 */
export async function chatPageResponse(backend: () => Promise<CompanyBackend>, request: Request): Promise<Response> {
  const params = new URL(request.url).searchParams;
  const id = (name: string) => (/^[\w-]{1,40}$/.test(params.get(name) ?? "") ? params.get(name)! : undefined);
  const limit = Math.min(200, Math.max(1, Number(params.get("limit")) || 50));
  try {
    const page = await (await backend()).chatPage({ before: id("before"), after: id("after"), around: id("around"), limit });
    return Response.json(page, { headers: { "Cache-Control": "no-store" } });
  } catch (error) {
    unstable_rethrow(error); // signed out: the host's redirect to its sign-in page
    if (error instanceof AgentError) return Response.json({ error: error.message }, { status: error.status });
    throw error;
  }
}
