import { agentToken, spaces } from "../../../../local/host";
import { signedIn } from "../../../../local/spaces";

/** Whether a new space's COO is up yet (its engine answers, and has made its token): ?id=. */
export async function GET(request: Request) {
  if (!(await signedIn())) return Response.json({ error: "Sign in first." }, { status: 401 });
  const space = spaces().find((s) => s.id === new URL(request.url).searchParams.get("id"));
  if (!space) return Response.json({ ready: false });
  const res = await fetch(new URL("/health", space.url), { cache: "no-store", signal: AbortSignal.timeout(3000) }).catch(() => null);
  return Response.json({ ready: Boolean(res?.ok && agentToken(space)) }, { headers: { "Cache-Control": "no-store" } });
}
