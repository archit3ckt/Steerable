import { cookies } from "next/headers";
import { COOKIE, validSession } from "../../local/auth";
import { agentToken } from "../../local/host";

/**
 * Your company as one file (company.tar.gz): memory, routines, tasks, skills, logs, drafts and
 * the board, without secrets or sessions. Keep it as a backup, or bring it to another machine
 * (`get.sh --import`) or to Steerable Cloud.
 */
export async function GET() {
  if (!validSession((await cookies()).get(COOKIE)?.value, Date.now())) return new Response("Sign in first.", { status: 401 });
  const res = await fetch(new URL("/v1/export", process.env.AGENT_API_URL || "http://127.0.0.1:8787"), {
    headers: { Authorization: `Bearer ${agentToken() ?? ""}` },
    cache: "no-store",
  }).catch(() => null);
  if (!res?.ok || !res.body) return new Response("Your COO didn't answer. Try again in a minute.", { status: 502 });
  const day = new Date().toISOString().slice(0, 10);
  return new Response(res.body, {
    headers: { "Content-Type": "application/gzip", "Content-Disposition": `attachment; filename="company-${day}.tar.gz"` },
  });
}
