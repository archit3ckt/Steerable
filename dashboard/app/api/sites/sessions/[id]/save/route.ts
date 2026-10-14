import { bodyOf, forward } from "../../../../../../local/sites";

/** Keep the logged-in session; {site}. */
export async function POST(request: Request, { params }: RouteContext<"/api/sites/sessions/[id]/save">) {
  const { name } = await bodyOf(request);
  return forward("POST", `/sessions/${encodeURIComponent((await params).id)}/save`, { name });
}
