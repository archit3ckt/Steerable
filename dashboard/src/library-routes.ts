import { unstable_rethrow } from "next/navigation";
import { AgentError } from "./backend/agent";
import type { CompanyBackend, LibraryQuery } from "./backend/types";

/**
 * The body of the host's libraryFilesUrl route, so each host's route is two lines:
 *
 *   export const GET = (request: Request) => libraryExportResponse(getBackend, request);
 *   export const POST = (request: Request) => libraryImportResponse(getBackend, request);
 *
 * GET ?table=<id>&format=csv|xlsx (+ q, sort, dir, where.<column>, archived, group): the rows as a
 * spreadsheet. POST ?name=<file name>&into=<table id>&title=<new table's name> with the file's raw
 * bytes: imports it. The backend checks who's asking, like every page does.
 */

const MAX_BYTES = 20 * 1024 * 1024;

function failure(error: unknown, fallback: string) {
  unstable_rethrow(error);
  if (error instanceof AgentError) return Response.json({ error: error.message }, { status: error.status });
  console.error(error);
  return Response.json({ error: fallback }, { status: 500 });
}

const ID = /^[\w-]{1,60}$/;

export async function libraryExportResponse(backend: () => Promise<CompanyBackend>, request: Request): Promise<Response> {
  const params = new URL(request.url).searchParams;
  const table = params.get("table") ?? "";
  if (!ID.test(table)) return Response.json({ error: "Which table?" }, { status: 400 });
  const text = (k: string) => (params.get(k) ?? "").slice(0, 200) || undefined;
  const where: Record<string, string> = {};
  for (const [k, v] of params) if (k.startsWith("where.") && k.length < 70) where[k.slice(6)] = v.slice(0, 200);
  const query: LibraryQuery = { q: text("q"), sort: text("sort"), dir: params.get("dir") === "desc" ? "desc" : "asc", where, archived: params.get("archived") === "1" };
  try {
    const file = await (await backend()).exportLibraryTable(table, query, params.get("format") === "xlsx" ? "xlsx" : "csv");
    return new Response(file.data, {
      headers: { "Content-Type": file.contentType, "Content-Disposition": file.disposition, "X-Content-Type-Options": "nosniff", "Cache-Control": "no-store" },
    });
  } catch (error) {
    return failure(error, "That table couldn't be exported. Try again.");
  }
}

export async function libraryImportResponse(backend: () => Promise<CompanyBackend>, request: Request): Promise<Response> {
  const params = new URL(request.url).searchParams;
  const name = params.get("name")?.trim().slice(0, 200) || "import.csv";
  const into = params.get("into") ?? undefined;
  if (into && !ID.test(into)) return Response.json({ error: "Which table?" }, { status: 400 });
  if (Number(request.headers.get("Content-Length") ?? 0) > MAX_BYTES) {
    return Response.json({ error: "That file is too big. Import spreadsheets up to 20 MB." }, { status: 413 });
  }
  try {
    const b = await backend();
    const data = await request.arrayBuffer();
    if (data.byteLength > MAX_BYTES) return Response.json({ error: "That file is too big. Import spreadsheets up to 20 MB." }, { status: 413 });
    return Response.json(await b.importLibrary(name, data, { into, title: params.get("title")?.trim().slice(0, 70) || undefined }));
  } catch (error) {
    return failure(error, "That file couldn't be imported. Try again.");
  }
}
