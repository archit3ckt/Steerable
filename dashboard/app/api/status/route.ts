import { backend } from "../../../local/host";

/** What the COO is doing in the background. The status panel polls it while it's open. */
export async function GET() {
  try {
    return Response.json(await (await backend()).status(), { headers: { "Cache-Control": "no-store" } });
  } catch {
    return Response.json({ error: "unavailable" }, { status: 503 }); // signed out, or the engine is away
  }
}
