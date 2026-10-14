import { unstable_rethrow } from "next/navigation";
import { AgentError } from "./backend/agent";
import type { CompanyBackend } from "./backend/types";

/**
 * The body of the host's tracesUrl route: GET ?id=<trace> answers backend.trace() as JSON, and
 * ?id=<trace>&shot=<n>.jpg one of its pictures.
 *
 *   export const GET = (request: Request) => traceResponse(getBackend, request);
 */
export async function traceResponse(backend: () => Promise<CompanyBackend>, request: Request): Promise<Response> {
  const params = new URL(request.url).searchParams;
  const id = params.get("id") ?? "";
  if (!/^[\w-]{1,60}$/.test(id)) return Response.json({ error: "Which run?" }, { status: 400 });
  const shot = params.get("shot");
  try {
    const b = await backend();
    if (shot !== null) {
      if (!/^\d{1,4}\.jpg$/.test(shot)) return Response.json({ error: "No such picture." }, { status: 400 });
      const picture = await b.traceShot(id, shot);
      return new Response(picture.data, {
        headers: {
          "Content-Type": "image/jpeg",
          "Content-Disposition": "inline",
          "X-Content-Type-Options": "nosniff",
          "Cache-Control": "private, max-age=86400",
        },
      });
    }
    const trace = await b.trace(id);
    if (!trace) return Response.json({ error: "That run's record is gone. Practice and watched runs are kept 30 days." }, { status: 404 });
    return Response.json(trace, { headers: { "Cache-Control": "no-store" } });
  } catch (error) {
    unstable_rethrow(error); // signed out: the host's redirect to its sign-in page
    if (error instanceof AgentError) return Response.json({ error: error.message }, { status: error.status });
    throw error;
  }
}
