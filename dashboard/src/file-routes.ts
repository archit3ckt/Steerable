import { unstable_rethrow } from "next/navigation";
import { AgentError } from "./backend/agent";
import type { CompanyBackend } from "./backend/types";

/**
 * The bodies of the host's chatFilesUrl routes, so each host's route is one line:
 *
 *   export const POST = (request: Request) => uploadResponse(getBackend, request);   // route.ts
 *   export const GET = async (_: Request, ctx) => fileResponse(getBackend, (await ctx.params).id);   // [id]/route.ts
 *
 * The backend call checks who's asking, like every page does.
 */

const MAX_BYTES = 20 * 1024 * 1024;

function failure(error: unknown, fallback: string) {
  unstable_rethrow(error); // signed out: the host's redirect to its sign-in page
  if (error instanceof AgentError) return Response.json({ error: error.message }, { status: error.status });
  console.error(error);
  return Response.json({ error: fallback }, { status: 500 });
}

export async function uploadResponse(backend: () => Promise<CompanyBackend>, request: Request): Promise<Response> {
  const name = new URL(request.url).searchParams.get("name")?.trim().slice(0, 200) || "file";
  if (Number(request.headers.get("Content-Length") ?? 0) > MAX_BYTES) {
    return Response.json({ error: "That file is too big. Attach files up to 20 MB." }, { status: 413 });
  }
  try {
    const b = await backend();
    const data = await request.arrayBuffer();
    if (data.byteLength > MAX_BYTES) return Response.json({ error: "That file is too big. Attach files up to 20 MB." }, { status: 413 });
    return Response.json(await b.uploadFile(name, data));
  } catch (error) {
    return failure(error, "That file didn't upload. Try again.");
  }
}

export async function fileResponse(backend: () => Promise<CompanyBackend>, id: string): Promise<Response> {
  try {
    const file = await (await backend()).file(id);
    return new Response(file.data, {
      headers: {
        "Content-Type": file.contentType,
        "Content-Disposition": file.disposition,
        "X-Content-Type-Options": "nosniff",
        // Pictures can't run anything, but a file someone sent shouldn't either, whatever it claims to be.
        "Content-Security-Policy": "default-src 'none'; img-src 'self'; style-src 'unsafe-inline'; sandbox",
        "Cache-Control": "private, max-age=86400",
      },
    });
  } catch (error) {
    return failure(error, "That file isn't here any more.");
  }
}
