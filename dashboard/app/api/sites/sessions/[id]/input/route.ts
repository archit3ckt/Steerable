import { bodyOf, forward } from "../../../../../../local/sites";

/** A click, typing, a key or a scroll on the page. */
export async function POST(request: Request, { params }: RouteContext<"/api/sites/sessions/[id]/input">) {
  return forward("POST", `/sessions/${encodeURIComponent((await params).id)}/input`, await bodyOf(request));
}
