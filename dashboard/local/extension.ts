import "server-only";
import { agentToken, company } from "./host";

/**
 * The browser extension's calls (dashboard/extension/), passed on to the engine's
 * scripts/extension.py. They come without the owner's session: the extension proves itself with
 * the token it got for a one-time pairing code, which the engine checks.
 */

export function bearer(request: Request): string {
  const auth = request.headers.get("authorization") ?? "";
  return auth.startsWith("Bearer ") ? auth.slice(7) : "";
}

export async function engine(path: string, body: unknown): Promise<Response> {
  const res = await fetch(new URL(`/v1/extension/${path}`, process.env.AGENT_API_URL || "http://127.0.0.1:8787"), {
    method: "POST",
    headers: { Authorization: `Bearer ${agentToken() ?? ""}`, "Content-Type": "application/json" },
    body: JSON.stringify(body),
    cache: "no-store",
    signal: AbortSignal.timeout(45_000),
  }).catch(() => null);
  if (!res) return Response.json({ error: `Can't reach ${company.cooName} right now. Try again in a minute.` }, { status: 502 });
  const data = await res.json().catch(() => ({}));
  return Response.json(path === "pair" && res.ok ? { ...data, cooName: company.cooName } : data, { status: res.status, headers: { "Cache-Control": "no-store" } });
}
