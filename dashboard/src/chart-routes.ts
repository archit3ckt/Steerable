import { unstable_rethrow } from "next/navigation";
import { AgentError } from "./backend/agent";
import type { CompanyBackend } from "./backend/types";
import { chartWords } from "./dashboard-format";

/**
 * The body of the host's chartsUrl route (GET ?w=<the block's JSON>), which a ```chart block in a
 * message fetches when it's shown, so it's counted from the library as it is now:
 *
 *   export const GET = (request: Request) => chartResponse(getBackend, request);
 */
export async function chartResponse(backend: () => Promise<CompanyBackend>, request: Request): Promise<Response> {
  const block = new URL(request.url).searchParams.get("w") ?? "";
  if (!block || block.length > 8000) return Response.json({ error: "Which chart?" }, { status: 400 });
  try {
    const chart = await (await backend()).chart(block);
    return Response.json(chart, { headers: { "Cache-Control": "no-store" } });
  } catch (error) {
    unstable_rethrow(error); // signed out: the host's redirect to its sign-in page
    if (error instanceof AgentError) return Response.json({ error: error.message }, { status: error.status });
    throw error;
  }
}

const CHART_BLOCK = /```chart[ \t]*\n([\s\S]*?)\n?```/g;

/**
 * A message for somewhere that can't draw charts (Telegram): each ```chart block becomes a line of what
 * it shows, or goes, if it can't be counted.
 */
export async function chartsAsWords(backend: CompanyBackend, text: string): Promise<string> {
  const blocks = [...text.matchAll(CHART_BLOCK)];
  if (!blocks.length) return text;
  const lines = await Promise.all(
    blocks.map(async ([, block]) => {
      try {
        const chart = await backend.chart(block);
        return "error" in chart ? "" : chartWords(chart);
      } catch {
        return "";
      }
    }),
  );
  let i = 0;
  return text.replace(CHART_BLOCK, () => lines[i++]).replace(/\n{3,}/g, "\n\n").trim();
}
