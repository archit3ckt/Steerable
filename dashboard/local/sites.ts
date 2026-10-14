import "server-only";
import { cookies } from "next/headers";
import { COOKIE, validSession } from "./auth";
import { agentToken } from "./host";

/**
 * Website logins (the engine's scripts/sites.py): the live-login screen's routes pass the
 * owner's clicks and typing to the engine's browser and its picture back. Only for the
 * signed-in owner.
 */

const AGENT = () => process.env.AGENT_API_URL || "http://127.0.0.1:8787";

/** Forward one request to the engine's /v1/sites API, as the response the browser gets. */
export async function forward(method: "GET" | "POST", path: string, body?: unknown): Promise<Response> {
  if (!validSession((await cookies()).get(COOKIE)?.value, Date.now())) return Response.json({ error: "Sign in first." }, { status: 401 });
  const res = await fetch(new URL(`/v1/sites${path}`, AGENT()), {
    method,
    headers: { Authorization: `Bearer ${agentToken() ?? ""}`, "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
    cache: "no-store",
    signal: AbortSignal.timeout(90_000),
  }).catch(() => null);
  if (!res) return Response.json({ error: "Your COO didn't answer. Try again in a minute." }, { status: 502 });
  return new Response(res.body, { status: res.status, headers: { "Content-Type": res.headers.get("Content-Type") ?? "application/json", "Cache-Control": "no-store" } });
}

/** Read the request's JSON body, or {} if there isn't one. */
export async function bodyOf(request: Request): Promise<Record<string, unknown>> {
  return (await request.json().catch(() => ({}))) as Record<string, unknown>;
}
