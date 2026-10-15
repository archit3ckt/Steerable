import { unstable_rethrow } from "next/navigation";
import { AgentError } from "./backend/agent";
import type { CompanyBackend } from "./backend/types";

/**
 * The body of the host's checksUrl route (GET ?message=<id>), which the chat polls while a reply is
 * being tested: the backend's check() as JSON.
 *
 *   export const GET = (request: Request) => checkResponse(getBackend, request);
 */
export async function checkResponse(backend: () => Promise<CompanyBackend>, request: Request): Promise<Response> {
  const message = new URL(request.url).searchParams.get("message") ?? "";
  if (!/^[\w-]{1,40}$/.test(message)) return Response.json({ error: "Which message?" }, { status: 400 });
  try {
    const check = await (await backend()).check(message);
    return Response.json(check, { headers: { "Cache-Control": "no-store" } });
  } catch (error) {
    unstable_rethrow(error); // signed out: the host's redirect to its sign-in page
    if (error instanceof AgentError) return Response.json({ error: error.message }, { status: error.status });
    throw error;
  }
}
