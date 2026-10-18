import "server-only";
import { agentToken, spaces, type Space } from "./host";

/**
 * The browser extension's calls (dashboard/extension/), passed on to the engine's
 * scripts/extension.py. They come without the owner's session: the extension proves itself with
 * the token it got for a one-time pairing code, which the engine checks.
 */

export function bearer(request: Request): string {
  const auth = request.headers.get("authorization") ?? "";
  return auth.startsWith("Bearer ") ? auth.slice(7) : "";
}

/**
 * Pass the call to the engine it belongs to. Extension calls carry no session, so with several
 * spaces each engine is asked in turn: only the one that made the pairing code, or the
 * extension's token, accepts it.
 */
export async function engine(path: string, body: unknown): Promise<Response> {
  let first: { res: Response | null; space: Space } | null = null;
  for (const space of spaces()) {
    const res = await fetch(new URL(`/v1/extension/${path}`, space.url), {
      method: "POST",
      headers: { Authorization: `Bearer ${agentToken(space) ?? ""}`, "Content-Type": "application/json" },
      body: JSON.stringify(body),
      cache: "no-store",
      signal: AbortSignal.timeout(45_000),
    }).catch(() => null);
    if (res?.ok) return reply(path, res, space);
    first ??= { res, space };
  }
  if (!first?.res) return Response.json({ error: `Can't reach ${first?.space.cooName ?? "your COO"} right now. Try again in a minute.` }, { status: 502 });
  return reply(path, first.res, first.space);
}

async function reply(path: string, res: Response, space: Space): Promise<Response> {
  const data = await res.json().catch(() => ({}));
  return Response.json(path === "pair" && res.ok ? { ...data, cooName: space.cooName } : data, { status: res.status, headers: { "Cache-Control": "no-store" } });
}
